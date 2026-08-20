"""webapp.py — pywebview host for the CAT8k-SYNC web console.

Serves gui/web via a local HTTP server (same-origin so sprite fetch works),
bridges the UI to the existing Engine + src.db + src.vault backend.

Run:  python gui/webapp.py            (live desktop window, edgechromium)
      python gui/webapp.py --no-window (headless API smoke test)
"""
import ipaddress
import json
import os
import re
import sys
import threading
import time
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

from src import db, vault                      # noqa: E402
from src import vpn as vpnlib                   # noqa: E402
from src import automation                      # noqa: E402
from src import device_mode                     # noqa: E402
from src.restconf_client import get_restconf_device  # noqa: E402
from gui.engine import Engine, BASELINE_PATH, _dev_name as _device_name  # noqa: E402

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
PORT = 17771
AUTO_COLLECT_S = 30

TELEMETRY_PATHS = {
    "interfaces": "Cisco-IOS-XE-interfaces-oper:interfaces",
    "arp": "Cisco-IOS-XE-arp-oper:arp-data",
    "ospf": "Cisco-IOS-XE-ospf-oper:ospf-oper-data",
    "bgp": "Cisco-IOS-XE-bgp-oper:bgp-state-data",
    "pkt-dist": "Cisco-IOS-XE-controllers-oper:controllers/controller",
}

# IOS XE controllers-oper packet-size buckets (see Tutorial: Packet size distribution)
PKT_BUCKETS = ("rx-pkts-64-octets", "rx-pkts-65-127-octets", "rx-pkts-128-255-octets",
               "rx-pkts-256-511-octets", "rx-pkts-512-1023-octets",
               "rx-pkts-1024-1518-octets", "rx-pkts-1519-max-octets")
PKT_LABELS = ("64", "65-127", "128-255", "256-511", "512-1023", "1024-1518", "1519+")
# Fallback packet-mix slices when controllers-oper is not served by the device
MIX_KEYS = (("in-unicast-pkts", "out-unicast-pkts"),
            ("in-multicast-pkts", "out-multicast-pkts"),
            ("in-broadcast-pkts", "out-broadcast-pkts"),
            ("in-unknown-protos", "out-unknown-protos"))

VLAN_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
IPV4_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
SUBNET_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}/\d{1,2}$")

# IOS-XE enumerated if-state strings (see gui/topo.py — the reference mapping)
OPER_OK = "if-oper-state-ready"
ADMIN_UP = "if-state-up"
OPER_WARN = ("if-oper-state-dormant", "if-oper-state-present",
             "if-oper-state-unknown", "")


def _iface_state(e):
    """Real oper-status strings ('if-oper-state-ready' / 'if-state-up')
    -> 'up' | 'warn' | 'down'. Never treat a ready link as down."""
    oper = (e.get("oper-status") or "").lower()
    admin = (e.get("admin-status") or "").lower()
    if oper == OPER_OK and admin == ADMIN_UP:
        return "up"
    if admin != ADMIN_UP:
        return "down"
    if oper in OPER_WARN:
        return "warn"
    return "down"


def _iface_speed(iface):
    v = iface.get("speed")
    try:
        v = int(v)
    except (TypeError, ValueError):
        return str(v) if v else "?"
    if v >= 10 ** 9:
        return f"{v // 10 ** 9} Gbps"
    if v >= 10 ** 6:
        return f"{v // 10 ** 6} Mbps"

def _valid_ip(s):
    return bool(IPV4_RE.match(s)) and all(0 <= int(p) <= 255 for p in s.split("."))


def _u(e, k, d=0):
    """Coerce a leaf to int. IOS XE serves counters as JSON strings, so
    numeric strings count too; anything else (None/bool/absent) -> d."""
    v = e.get(k, d) if isinstance(e, dict) else d
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return v
    if isinstance(v, str):
        try:
            return int(v)
        except ValueError:
            return d
    return d


def _s(e, k, d=""):
    v = e.get(k, d) if isinstance(e, dict) else d
    return v if isinstance(v, str) else d


def _pkt_dist_entries(root):
    """controllers/controller payload -> per-interface 7-bucket rx/tx rows.
    Aggregates across control-plane-protocol entries (Cat8kv lists an
    interface several times — one per protocol)."""
    agg = {}
    for e in (root or {}).get("controller") or []:
        name = _s(e, "name", "?")
        rx = [_u(e, k) for k in PKT_BUCKETS]
        tx = [_u(e, "tx-" + k[3:]) for k in PKT_BUCKETS]
        if not any(rx + tx):
            continue
        row = agg.setdefault(name, ([0] * 7, [0] * 7))
        for i in range(7):
            row[0][i] += rx[i]
            row[1][i] += tx[i]
    return [{"name": n, "rx": r, "tx": t, "total_rx": sum(r), "total_tx": sum(t)}
            for n, (r, t) in agg.items()]


def _mix_entries(root):
    """interfaces-oper statistics -> per-interface packet-mix rows
    (unicast/multicast/broadcast/unknown shares + average packet size)."""
    out = []
    for e in (root or {}).get("interface") or []:
        st = e.get("statistics") or {}
        rx = [_u(st, k) for k, _ in MIX_KEYS]
        tx = [_u(st, k2) for _, k2 in MIX_KEYS]
        if not any(rx + tx):
            continue
        in_pkts, out_pkts = sum(rx), sum(tx)
        out.append({
            "name": _s(e, "name", "?"), "rx": rx, "tx": tx,
            "total_rx": in_pkts, "total_tx": out_pkts,
            "avg_rx": round(_u(st, "in-octets") / in_pkts) if in_pkts else 0,
            "avg_tx": round(_u(st, "out-octets") / out_pkts) if out_pkts else 0,
        })
    return out


def _clamped_delta(prev_entries, cur_entries):
    """Per-name per-bucket counter delta (cur - prev), negatives clamped
    (counters are cumulative since boot; a wrap reads as no growth)."""
    by = {e["name"]: e for e in prev_entries}
    out = {}
    for e in cur_entries:
        p = by.get(e["name"])
        if not p:
            continue
        out[e["name"]] = {
            "rx": [max(0, c - a) for c, a in zip(e["rx"], p["rx"])],
            "tx": [max(0, c - a) for c, a in zip(e["tx"], p["tx"])],
        }
    return out


def _pkt_root(text):
    try:
        return json.loads(text).get("Cisco-IOS-XE-controllers-oper:controllers", {})
    except (ValueError, TypeError, AttributeError):
        return {}


def _if_root(text):
    try:
        return json.loads(text).get("Cisco-IOS-XE-interfaces-oper:interfaces", {})
    except (ValueError, TypeError, AttributeError):
        return {}


class Api:
    """Exposed to the webview as pywebview.api — every method must be JSON-safe."""

    def __init__(self):
        db.init()
        # NOTE: must stay underscore-prefixed — pywebview recursively introspects
        # every public attr of the js_api object, and `window` → `native` → the
        # .NET Form graph is cyclic (AccessibilityObject.Bounds.Empty…) and blows
        # Python's recursion limit on every page load.
        self._window = None
        self.engine = Engine(self._on_done, self._on_start)
        self._health = {"ok": None, "host": None, "at": None}
        self._posture = None
        self._posture_ts = 0.0
        self._nc_mods = None
        self._nc_mods_ts = 0.0
        self._vlan_scan = None
        self._vlan_scan_ts = 0.0
        self._collector_started = False
        self._collect_busy = False
        self._collect_ok = 0
        self._collect_fail = 0

    # ---------------- js bridge ----------------

    def _ensure_collector(self):
        """Background live snapshot collector for the ANALYTICS window.

        Starts once any LIVE API call hits the server: a daemon appends a
        real device snapshot every AUTO_COLLECT_S so the long-term series
        advance over time without manual scans. Demo mode never calls the
        live endpoints, so it never starts. Skip-if-busy guards slow devices;
        failures are silent and retried next cycle."""
        if self._collector_started:
            return
        self._collector_started = True

        def collect_once():
            if self._collect_busy:
                return
            self._collect_busy = True
            try:
                _, rc = get_restconf_device(None)
                snap = automation.device_snapshot(rc)
                if snap.get("hostname") != "?":
                    db.save_snapshot(snap)
                    self._collect_ok += 1
                else:
                    self._collect_fail += 1
            except Exception:  # noqa: BLE001 - device offline; retry next cycle
                self._collect_fail += 1
            finally:
                self._collect_busy = False

        def loop():
            collect_once()
            while True:
                time.sleep(AUTO_COLLECT_S)
                collect_once()

        threading.Thread(target=loop, daemon=True, name="auto-snapshot").start()

    def set_window(self, w):
        self._window = w

    def _push(self, js):
        if self._window is None:
            return
        try:
            self._window.evaluate_js(js)
        except Exception as e:  # noqa: BLE001 - window may be mid-teardown
            print("[push] evaluate_js failed:", e)

    def _on_start(self, label):
        self._push(f"window.Company && window.Company.onTask({json.dumps({'id': label, 'state': 'running'})})")

    def _on_done(self, label, text, result):
        ok = "FATAL" not in text
        payload = json.dumps({"id": label, "state": "done" if ok else "failed",
                              "output": text[-4000:]})
        self._push(f"window.Company && window.Company.onTask({payload})")
        if label == "PING":
            self._health = {"ok": bool(result), "host": result or "",
                            "at": time.strftime("%H:%M:%S")}
            self._push(f"window.Company && window.Company.onHealth({json.dumps(self._health)})")
        if ok and result is not None:
            r = json.dumps({"id": label, "data": result})
            self._push(f"window.Company && window.Company.onResult({r})")

    # ---------------- live fabric health ----------------

    def health(self):
        """Last known reachability result (no network I/O)."""
        return self._health

    def checkHealth(self):
        """Queue an async RESTCONF hostname probe; result arrives via onHealth."""
        self.engine.ping_backend()
        return {"ok": True, "queued": True}

    # ---------------- state / auth ----------------

    def state(self):
        user = db.get_user()
        mode = db.get_setting("mode", "")
        creds = self._masked_creds()
        return {
            "mode": mode,
            "configured": bool(creds and creds.get("host")),
            "session": db.get_setting("session", "") or None,
            "theme": "mission",
            "profile": {
                "full_name": user["display_name"] if user else "",
                "role": db.get_setting("profile.role", ""),
                "site": db.get_setting("profile.site", ""),
            },
            "creds": creds,
            "vpn": self._masked_vpn(),
            "res_creds": self._masked_res(),
            "backend": device_mode.active_info(),
            "identity": {
                "instance": db.get_setting("device.identity", ""),
                "at": db.get_setting("device.identity_at", ""),
                "preference": db.get_setting("device.backend", "auto"),
            },
            "version": {"app": "CAT8k-SYNC", "build": "0.4.0-web", "core": "pywebview"},
        }

    def _masked_res(self):
        """Reservation companion credential sets (defaults applied, masked)."""
        try:
            sets = db.get_res_creds()
        except Exception:  # noqa: BLE001
            return {}
        return {
            slug: {
                "slug": slug,
                "label": s.get("label", slug),
                "desc": s.get("desc", ""),
                "host": s.get("host", ""),
                "port": s.get("port", ""),
                "username": s.get("username", ""),
                "password": vault.mask(s.get("password", "")) if s.get("password") else "",
                "updated": s.get("updated", ""),
            }
            for slug, s in sets.items()
        }

    def _masked_creds(self):
        try:
            dev = db.get_device_plain() or {}
        except Exception:  # noqa: BLE001
            dev = {}
        if not dev:
            return None
        return {
            "host": dev.get("host", ""),
            "username": dev.get("username", ""),
            "password": vault.mask(dev.get("password", "")) if dev.get("password") else "",
            "secret": vault.mask(dev.get("secret", "")) if dev.get("secret") else "",
        }

    def _masked_vpn(self):
        try:
            vpn = db.get_vpn_plain() or {}
        except Exception:  # noqa: BLE001
            vpn = {}
        if not vpn:
            return None
        return {
            "address": vpn.get("address", ""),
            "username": vpn.get("username", ""),
            "password": vault.mask(vpn.get("password", "")) if vpn.get("password") else "",
            "device_host": vpn.get("device_host", ""),
            "device_username": vpn.get("device_username", ""),
            "device_password": (vault.mask(vpn.get("device_password", ""))
                                if vpn.get("device_password") else ""),
            "updated": vpn.get("updated", ""),
        }

    def setMode(self, mode):
        db.set_setting("mode", mode)
        db.log_event("INFO", "SETUP", f"operation mode -> {mode}")
        db.log_ledger("SETTINGS", db.get_setting("session", ""), "set-mode",
                      payload={"mode": mode})
        return self.state()

    def updateProfile(self, p):
        p = p or {}
        user = db.get_user()
        username = user["username"] if user else "operator"
        db.save_user(username, display_name=(p.get("full_name") or ""))
        db.set_setting("profile.role", p.get("role", ""))
        db.set_setting("profile.site", p.get("site", ""))
        db.log_ledger("SETTINGS", username, "update-profile", payload=p)
        return True

    def testCreds(self, c):
        """Probe the device with ad-hoc credentials BEFORE saving anything.
        Returns {ok, hostname, user} or {ok, error} with a classified reason."""
        c = c or {}
        host = str(c.get("host") or "").strip()
        username = str(c.get("username") or "").strip()
        password = str(c.get("password") or "")
        if not host or not username or not password:
            return {"ok": False, "error": "host, username and password are all required"}
        res = self.engine.test_credentials(host, username, password)
        db.log_ledger("VAULT", db.get_setting("session", ""),
                      "credentials-test",
                      payload={"host": host, "ok": bool(res.get("ok"))})
        return res

    def updateCreds(self, c):
        c = c or {}
        db.save_device({
            "name": "Cat8000", "host": c.get("host", ""),
            "username": c.get("username", ""),
            "password": c.get("password", ""),
            "secret": c.get("secret", ""),
            "port": 22, "https": True, "verify_ssl": False, "restconf_port": 443,
        })
        db.log_event("OK", "VAULT", "credentials sealed in fernet vault")
        db.log_ledger("VAULT", db.get_setting("session", ""),
                      "credentials-update",
                      payload={"host": c.get("host", "")})
        return True

    def saveVpn(self, c):
        c = c or {}
        db.save_vpn({
            "address": str(c.get("address") or "").strip(),
            "username": str(c.get("username") or "").strip(),
            "password": str(c.get("password") or ""),
            "device_host": str(c.get("device_host") or "").strip(),
            "device_username": str(c.get("device_username") or "").strip(),
            "device_password": str(c.get("device_password") or ""),
        })
        device_mode.invalidate()
        db.log_event("OK", "PROFILE", "vpn access sealed in fernet vault")
        db.log_ledger("SETTINGS", db.get_setting("session", ""), "save-vpn",
                      payload={"address": str(c.get("address") or "")})
        return True

    def setBackend(self, mode):
        """Switch the device backend: 'auto' | 'normal' | 'reservation'."""
        try:
            info = device_mode.set_backend(str(mode or ""))
        except ValueError as e:
            return {"ok": False, "error": str(e)[:120]}
        db.log_event("INFO", "PROFILE", f"device backend -> {info.get('mode')}")
        db.log_ledger("SETTINGS", db.get_setting("session", ""), "set-backend",
                      payload={"mode": info.get("mode")})
        return {"ok": True, "backend": info}

    def saveRes(self, slug, rec):
        """Save one reservation companion credential set (devbox/xrv/nexus)."""
        slug = str(slug or "").strip()
        rec = rec or {}
        try:
            db.save_res_cred(slug, {
                "host": str(rec.get("host") or "").strip(),
                "port": str(rec.get("port") or "22").strip(),
                "username": str(rec.get("username") or "").strip(),
                "password": str(rec.get("password") or ""),
            })
        except ValueError as e:
            return {"ok": False, "error": str(e)[:120]}
        device_mode.invalidate()
        db.log_event("OK", "PROFILE", f"reservation companion sealed -> {slug}")
        db.log_ledger("SETTINGS", db.get_setting("session", ""), "save-res-cred",
                      payload={"slug": slug})
        return {"ok": True, "set": self._masked_res().get(slug)}

    def vpnStatus(self):
        active = device_mode.active_device()
        dev = active or db.get_device_plain() or {}
        st = vpnlib.vpn_state(
            device_host=dev.get("host", ""),
            device_port=int(dev.get("restconf_port") or 443),
        )
        rec = db.get_vpn_plain() or {}
        st["address"] = rec.get("address", "")
        st["backend"] = device_mode.active_info()
        return st

    def vpnConnect(self):
        rec = db.get_vpn_plain() or {}
        address, username, password = (rec.get("address") or "",
                                       rec.get("username") or "",
                                       rec.get("password") or "")
        if not (address and username and password):
            return {"ok": False, "error": "vpn-credentials-missing"}
        res = vpnlib.vpn_connect(address, username, password)
        device_mode.invalidate()
        db.log_event("OK" if res.get("ok") else "WARN", "VPN",
                     "vpn connect " + ("ok" if res.get("ok") else res.get("error", "failed")))
        db.log_ledger("SETTINGS", db.get_setting("session", ""), "vpn-connect",
                      payload={"endpoint": address, "ok": bool(res.get("ok"))})
        res["backend"] = device_mode.active_info()
        return res

    def vpnDisconnect(self):
        res = vpnlib.vpn_disconnect()
        device_mode.invalidate()
        db.log_event("OK" if res.get("ok") else "WARN", "VPN",
                     "vpn disconnect " + ("ok" if res.get("ok") else res.get("error", "failed")))
        db.log_ledger("SETTINGS", db.get_setting("session", ""), "vpn-disconnect",
                      payload={"ok": bool(res.get("ok"))})
        return res

    def login(self, username, password):
        user = db.get_user()
        if user and username != user.get("username"):
            return {"ok": False, "error": "unknown operator"}
        if not db.verify_password(user, password):
            db.log_ledger("AUTH", str(username or ""), "login:failed",
                          payload={"reason": "bad credentials"})
            return {"ok": False, "error": "bad credentials"}
        db.set_setting("session", username)
        db.log_event("OK", "AUTH", f"session open :: {username}")
        db.log_ledger("AUTH", str(username or ""), "login", payload={})
        return {"ok": True, "session": username}

    def logout(self):
        actor = db.get_setting("session", "")
        db.set_setting("session", "")
        db.log_event("INFO", "AUTH", "session closed")
        db.log_ledger("AUTH", actor, "logout", payload={})
        return {"ok": True}

    # ---------------- validation (mirrors legacy app._field_errors) ----------------

    def fields(self):
        return {
            "site_name": {"required": True, "max": 32},
            "department_vlan": {"required": True, "max": 32},
            "vlan_id": {"required": True, "min": 2, "max": 4094},
            "vlan_name": {"required": True, "max": 32, "pattern": r"^[A-Za-z0-9_-]{1,32}$"},
            "department_subnet": {"required": True, "type": "ipv4cidr"},
            "gateway": {"required": True, "type": "ipv4"},
            "router_wan_ip": {"required": False, "type": "ipv4"},
            "router_trunk_port": {"required": False, "max": 24},
            "port": {"required": False, "max": 24},
            "pc_ip": {"required": False, "type": "ipv4"},
        }

    def validate(self, form):
        """Same rules as the legacy Tk app._field_errors."""
        form = form or {}
        errs = {}
        action = form.get("action", "add_branch")
        raw_vlan = str(form.get("vlan_id") or "").strip()
        try:
            vlan = int(raw_vlan)
            if not 2 <= vlan <= 4094:
                errs["vlan_id"] = "VLAN must be 2-4094"
        except (TypeError, ValueError):
            errs["vlan_id"] = "VLAN must be a number 2-4094"
        if action != "delete_branch" and not VLAN_RE.match(str(form.get("vlan_name", ""))):
            errs["vlan_name"] = "a-z 0-9 - _ only, max 32"
        if not str(form.get("site_name", "")).strip():
            errs["site_name"] = "Site name is required"
        if action == "add_branch":
            if not _valid_ip(str(form.get("gateway", ""))):
                errs["gateway"] = "Bad IPv4"
            if not SUBNET_RE.match(str(form.get("department_subnet", ""))):
                errs["department_subnet"] = "Expect 192.168.30.0/24"
            if not _valid_ip(str(form.get("router_wan_ip", ""))):
                errs["router_wan_ip"] = "Bad IPv4 (/30)"
        elif action == "add_pc":
            if not _valid_ip(str(form.get("pc_ip", ""))):
                errs["pc_ip"] = "Bad IPv4"
            elif db.host_ip_taken(str(form.get("pc_ip", "")).strip()):
                errs["pc_ip"] = "IP already registered"
            nt = str(form.get("node_type") or "pc").strip().lower()
            if nt not in ("pc", "laptop", "server", "printer", "phone"):
                errs["node_type"] = "Type must be pc, laptop, server, printer or phone"
        return errs

    # ---------------- data endpoints ----------------

    def hostRegistry(self):
        return {"ok": True, "hosts": db.list_hosts(limit=100)}

    def series(self):
        out = {}
        for kind in ("cpu", "mem", "up", "errors"):
            pts = db.series(kind, limit=20)
            out[kind] = {"vals": [p[1] for p in pts], "x": [p[0] for p in pts]}
        return out

    def trends(self):
        pts = db.series("up", limit=20)
        return {"x": [p[0] for p in pts], "values": [p[1] for p in pts]}

    def stats(self):
        self._ensure_collector()
        s = db.stats_overview()
        s["compliance"] = self._compliance_score()
        s["drift"] = db.recent_events and len(db.drift_history(5)) or 0
        if s.get("first_snapshot"):
            try:
                f = datetime.strptime(s["first_snapshot"], "%Y-%m-%d %H:%M:%S")
                s["uptime_days"] = max(0, (datetime.now() - f).days)
            except (ValueError, TypeError):
                s["uptime_days"] = 0
        else:
            s["uptime_days"] = 0
        return s

    def _compliance_score(self):
        audits = db.audit_history(1)
        if not audits:
            return 100
        a = audits[0]
        total = a["pass_count"] + a["fail_count"] + a["warn_count"]
        return round(100 * a["pass_count"] / total) if total else 100

    def analyticsDeep(self, span=200):
        """Long-term, time-mapped analytics for the ANALYTICS page.

        Every series below is drawn from SQL history (snapshot_history,
        iface_history, series, audit_history, drift, telemetry) — nothing
        is fetched live. `span` caps how many trailing collections are
        included so the UI can offer 1D/1W/1M/ALL sample windows."""
        try:
            cap = int(span)
        except (TypeError, ValueError):
            cap = 200
        cap = min(max(cap, 10), 1000)
        self._ensure_collector()
        out = {"span": cap}

        # ---------- resource series (cpu / mem / up / errors) ----------
        for kind in ("cpu", "mem", "up", "errors"):
            pts = db.series(kind, limit=cap)
            out[kind] = {"x": [p[0] for p in pts], "vals": [p[1] for p in pts]}

        # ---------- availability + ARP scale per snapshot ----------
        snaps = db.snapshot_timeline(limit=cap)
        avail = {"x": [], "vals": [], "up": [], "down": []}
        arp = {"x": [], "vals": []}
        for s in reversed(snaps):
            ts = str(s.get("ts", ""))[:16]
            if not ts:
                continue
            up = int(s.get("iface_up") or 0)
            down = int(s.get("iface_down") or 0)
            total = up + down
            avail["x"].append(ts)
            avail["vals"].append(round(100.0 * up / total, 1) if total else None)
            avail["up"].append(up)
            avail["down"].append(down)
            arp["x"].append(ts)
            arp["vals"].append(int(s.get("arp_count") or 0))
        out["avail"] = avail
        out["arp"] = arp

        # ---------- throughput + error / flap totals per snapshot ----------
        rows = db.iface_history(limit=cap * 24)
        rx_tot, tx_tot = {}, {}
        e_in, e_out, crc, flap = {}, {}, {}, {}
        per_if = {}
        order = []
        for r in rows:
            ts = str(r.get("ts", ""))[:16]
            if not ts:
                continue
            if ts not in rx_tot:
                order.append(ts)
            rx_tot[ts] = rx_tot.get(ts, 0) + int(r.get("rx_kbps") or 0)
            tx_tot[ts] = tx_tot.get(ts, 0) + int(r.get("tx_kbps") or 0)
            e_in[ts] = e_in.get(ts, 0) + int(r.get("in_errors") or 0)
            e_out[ts] = e_out.get(ts, 0) + int(r.get("out_errors") or 0)
            crc[ts] = crc.get(ts, 0) + int(r.get("crc_errors") or 0)
            flap[ts] = flap.get(ts, 0) + int(r.get("flaps") or 0)
            per_if.setdefault(r["if_name"], {})[ts] = {
                "rx": int(r.get("rx_kbps") or 0), "tx": int(r.get("tx_kbps") or 0),
                "state": r.get("state", "?")}
        order.reverse()  # iface_history returns newest-first

        def series_of(m):
            return [m.get(t, 0) for t in order]

        out["thr"] = {"x": order, "rx": series_of(rx_tot), "tx": series_of(tx_tot)}
        out["errs"] = {"x": order, "in_errors": series_of(e_in),
                       "out_errors": series_of(e_out), "crc": series_of(crc),
                       "flaps": series_of(flap)}

        # ---------- top talkers + problem interfaces (latest snapshot) ----------
        talkers, probs, speeds = [], [], {}
        if rows:
            last_ts = str(rows[0].get("ts", ""))[:16]
            latest = [(nm, d[last_ts]) for nm, d in per_if.items() if last_ts in d]
            latest.sort(key=lambda t: t[1]["rx"], reverse=True)
            for nm, cur in latest[:8]:
                talkers.append({
                    "name": nm, "state": cur["state"],
                    "rx": cur["rx"], "tx": cur["tx"],
                    "vals": [per_if[nm].get(t, {}).get("rx", 0) for t in order],
                })
            for r in rows:
                if str(r.get("ts", ""))[:16] != last_ts:
                    continue
                sp = str(r.get("speed") or "")
                if sp:
                    speeds[sp] = speeds.get(sp, 0) + 1
                f = int(r.get("flaps") or 0)
                c = int(r.get("crc_errors") or 0)
                ei = int(r.get("in_errors") or 0)
                if f or c or ei:
                    probs.append({
                        "name": r.get("if_name", "?"), "state": r.get("state", "?"),
                        "speed": sp, "rx": int(r.get("rx_kbps") or 0),
                        "tx": int(r.get("tx_kbps") or 0), "flaps": f, "crc": c,
                        "in_errors": ei, "out_errors": int(r.get("out_errors") or 0)})
            probs.sort(key=lambda p: p["flaps"] + p["crc"] + p["in_errors"],
                       reverse=True)
        out["talkers"] = talkers
        out["problems"] = probs
        out["speeds"] = speeds

        # ---------- compliance score history ----------
        audits = db.audit_history(limit=cap)
        at = {"x": [], "pass": [], "fail": [], "warn": [], "score": []}
        for a in reversed(audits):
            total = a["pass_count"] + a["fail_count"] + a["warn_count"]
            at["x"].append(str(a["ts"])[5:16])
            at["pass"].append(a["pass_count"])
            at["fail"].append(a["fail_count"])
            at["warn"].append(a["warn_count"])
            at["score"].append(round(100 * a["pass_count"] / total) if total else 100)
        out["audit"] = at

        # ---------- latest packet-size distribution ----------
        pk = db.telemetry_history("pkt-dist", limit=1)
        if pk:
            try:
                out["pkt"] = {"labels": list(PKT_LABELS),
                              "entries": _pkt_dist_entries(_pkt_root(pk[0]["payload"]))}
            except Exception:  # noqa: BLE001
                out["pkt"] = {"labels": list(PKT_LABELS), "entries": []}
        else:
            out["pkt"] = {"labels": list(PKT_LABELS), "entries": []}

        # ---------- 24h event activity profile ----------
        hr = [0] * 24
        for e in db.recent_events(400):
            try:
                hh = int(e["ts"][11:13])
            except (TypeError, ValueError):
                continue
            if 0 <= hh <= 23:
                hr[hh] += 1
        out["hourly"] = hr
        return out

    def dashboard(self):
        """One-shot payload for the home dashboard: SQL history trends +
        stats, plus a fresh live telemetry sample when reachable."""
        from collections import Counter
        stats = self.stats()
        d = {"stats": stats, "series": {}, "audit_trend": {}, "traffic": [],
             "hourly": [0] * 24, "events": [], "drift_trend": {}}
        for k in ("cpu", "mem", "up", "errors"):
            pts = db.series(k, limit=24)
            d["series"][k] = {"x": [p[0] for p in pts], "vals": [p[1] for p in pts]}
        audits = db.audit_history(limit=10)
        at = {"x": [], "pass": [], "fail": [], "warn": [], "score": []}
        for a in reversed(audits):
            at["x"].append(a["ts"][5:16])
            at["pass"].append(a["pass_count"])
            at["fail"].append(a["fail_count"])
            at["warn"].append(a["warn_count"])
            total = a["pass_count"] + a["fail_count"] + a["warn_count"]
            at["score"].append(round(100 * a["pass_count"] / total) if total else 100)
        d["audit_trend"] = at
        rows = db.iface_history(limit=500)
        if rows:
            sid = rows[0]["snapshot_id"]
            latest = [r for r in rows if r["snapshot_id"] == sid]
            latest.sort(key=lambda r: (r["rx_kbps"] or 0) + (r["tx_kbps"] or 0),
                        reverse=True)
            d["traffic"] = [
                {"name": r["if_name"], "rx": r["rx_kbps"] or 0, "tx": r["tx_kbps"] or 0,
                 "state": r["state"]}
                for r in latest[:8]]
        evs = db.recent_events(300)
        d["events"] = [
            {"ts": e["ts"], "level": e["level"], "source": e["source"],
             "msg": e["message"]}
            for e in evs[:12]]
        for e in evs:
            try:
                hh = int(e["ts"][11:13])
            except (ValueError, TypeError):
                continue
            if 0 <= hh <= 23:
                d["hourly"][hh] += 1
        dt = {"x": [], "status": []}
        for dr in reversed(db.drift_history(limit=10)):
            dt["x"].append(dr["ts"][5:16])
            dt["status"].append(dr["status"])
        d["drift_trend"] = dt
        return d

    def hosts(self):
        return [{"hostname": self.engine.device_host(), "up": True}]

    def topology(self):
        center = {
            "id": "core", "hostname": self.engine.device_host() or "CORE-EDGE",
            "role": "core", "kind": "router", "up": True,
            "model": "", "ios": "", "ipv4": "", "subnet": "",
        }
        devices, links = [], []
        rows = db.telemetry_history("interfaces", limit=1)
        if rows:
            try:
                data = json.loads(rows[0]["payload"])
                root = data.get("Cisco-IOS-XE-interfaces-oper:interfaces", {})
                for e in root.get("interface") or []:
                    if not isinstance(e, dict):
                        continue
                    dev = self._topo_device(e)
                    if dev is None:
                        continue
                    devices.append(dev)
                    up = dev["state"] == "up"
                    links.append({
                        "id": f"c-{dev['id']}", "from": "core", "to": dev["id"],
                        "up": up, "state": dev["state"],
                        "iface": dev.get("iface", ""), "vlan": dev.get("vlan", "") or "",
                    })
            except (ValueError, KeyError, AttributeError):
                pass
        branch_vlans = {d.get("vlan") for d in devices if d.get("role") == "branch"}
        for h in db.list_hosts(limit=100):
            hid = f"h-{h['id']}"
            node_type = (h.get("node_type") or "pc").strip().lower() or "pc"
            devices.append({
                "id": hid, "role": "host", "kind": node_type,
                "hostname": h.get("label") or h.get("ip"),
                "site": h.get("label") or "", "node_type": node_type,
                "vlan": h.get("vlan_id") or 0, "ipv4": h.get("ip") or "",
                "cidr": f"{h.get('ip')}/32" if h.get("ip") else "",
                "subnet": h.get("subnet") or "", "iface": h.get("port") or "",
                "state": "up", "up": True,
                "meta": {"desc": f"registered {node_type} · {h.get('gateway') or ''}".strip()},
            })
            parent = f"br-{h.get('vlan_id')}" if h.get("vlan_id") in branch_vlans else "core"
            links.append({
                "id": f"{hid}-lnk", "from": parent, "to": hid,
                "up": True, "state": "up",
                "iface": h.get("port") or "", "vlan": h.get("vlan_id") or "",
            })
        return {"center": center, "devices": devices, "links": links}

    def _topo_device(self, e):
        name = (e.get("name") or "").strip()
        state = _iface_state(e)
        ip = e.get("ipv4") or ""
        mask = e.get("ipv4-subnet-mask") or ""
        subnet, cidr = "", ""
        if ip and mask and ip != "0.0.0.0":
            try:
                cidr = f"{ip}/{ipaddress.ip_network(f'{ip}/{mask}', strict=False).prefixlen}"
                subnet = str(ipaddress.ip_network(f"{ip}/{mask}", strict=False))
            except ValueError:
                cidr, subnet = ip, ip
        meta = {
            "iface": name, "speed": _iface_speed(e), "duplex": e.get("duplex") or "",
            "mtu": e.get("mtu") or "", "mac": e.get("phys-address") or "",
            "desc": e.get("description") or "",
        }
        base = {
            "ipv4": ip, "cidr": cidr, "subnet": subnet, "state": state,
            "iface": name, "meta": meta,
        }
        if "." in name:
            tag = name.split(".")[-1]
            site = (e.get("description") or "").split(" ")[0] or f"VLAN {tag}"
            return {"id": f"br-{tag}", "role": "branch", "kind": "network",
                    "hostname": f"BR-{tag.upper()}", "site": site,
                    "vlan": int(tag) if tag.isdigit() else 0, **base}
        if name.lower().startswith("loopback"):
            num = name.lower().replace("loopback", "")
            return {"id": f"lb-{num}", "role": "loop", "kind": "server",
                    "hostname": f"LOOPBACK{num}", "site": "ROUTER ID", **base}
        if ip and ip != "0.0.0.0":            # physical L3 uplink -> cloud
            return {"id": "wan", "role": "wan", "kind": "cloud",
                    "hostname": "WAN-UPLINK", "site": "SP UPLINK", **base}
        return None                            # empty unused port (0.0.0.0)

    def topologyRaw(self):
        rows = db.telemetry_history("interfaces", limit=1)
        if not rows:
            return {}
        text = rows[0]["payload"]
        try:
            raw = json.dumps(json.loads(text), indent=2)
        except ValueError:
            raw = text
        return {"raw": raw, "ts": rows[0]["ts"]}

    def telemetry(self, kind):
        rows = db.telemetry_history(kind, limit=2)
        if not rows:
            return {}
        text = rows[0]["payload"]
        out = {"raw": text, "ts": rows[0]["ts"]}
        try:
            data = json.loads(text)
            if kind == "interfaces":
                root = data.get("Cisco-IOS-XE-interfaces-oper:interfaces", {})
                entries = root.get("interface") or []

                def _f(e, k, d=""):
                    v = e.get(k, d)
                    return v if isinstance(v, str) else d

                out["entries"] = [
                    {
                        "name": _f(e, "name", "?"),
                        "status": _iface_state(e),
                        "speed": _iface_speed(e),
                        "duplex": _f(e, "duplex"),
                        "ip": (f"{_f(e, 'ipv4')}/{_f(e, 'ipv4-subnet-mask')}"
                               if (_f(e, "ipv4") and _f(e, "ipv4") != "0.0.0.0") else ""),
                        "vlan": _f(e, "name").split(".")[-1] if "." in _f(e, "name") else "",
                    }
                    for e in entries
                ]
                out["count"] = len(entries)
            elif kind == "arp":
                root = data.get("Cisco-IOS-XE-arp-oper:arp-data", {})
                rows, seen = [], set()
                for vrf in root.get("arp-vrf") or []:
                    for e in (vrf.get("arp-oper") or []) + (vrf.get("arp-entry") or []):
                        key = (e.get("address", ""), e.get("interface", ""))
                        if key in seen:
                            continue
                        seen.add(key)
                        rows.append({
                            "ip": e.get("address", "?"),
                            "mac": e.get("hardware", "—"),
                            "interface": e.get("interface", "—"),
                            "mode": str(e.get("mode", "")).replace("ios-arp-mode-", ""),
                            "type": str(e.get("type", "")).replace("ios-linktype-", ""),
                            "age": str(e.get("time", "")).replace("T", " ").replace("+00:00", "")[:19],
                        })
                out["entries"] = rows
                out["count"] = len(rows)
            elif kind == "ospf":
                root = data.get("Cisco-IOS-XE-ospf-oper:ospf-oper-data", {})
                st = root.get("ospf-state") or {}
                op_mode = str(st.get("op-mode", "")).replace("ospf-", "")
                procs = st.get("ospf-process")
                if not isinstance(procs, list):
                    procs = []
                rows = []
                for p in procs:
                    area = "—"
                    al = (p.get("areas") or {}).get("area") or []
                    if al and isinstance(al[0], dict):
                        area = al[0].get("area-id", "—")
                    rows.append({
                        "process-id": p.get("process-id", "?"),
                        "router-id": p.get("router-id", "—"),
                        "state": p.get("state") or p.get("oper-status") or "—",
                        "area": area,
                    })
                state_meta = {
                    "ships-in-the-night": (
                        "OSPF SITN // V2 + V3 INDEPENDENT",
                        "OSPFv2 and OSPFv3 run as two separate, isolated processes on this device — like ships passing in the night. They keep their own router-IDs, configs and neighbor tables, and never share state. If no process rows appear below, OSPF is enabled in this mode but no process is currently running."),
                    "native": (
                        "OSPF NATIVE // SHARED ROUTER-ID",
                        "OSPFv2 and OSPFv3 share one process and one router-ID, managed together. Below are the OSPF processes detected on the device."),
                }.get(op_mode)
                if state_meta is None:
                    state_meta = (op_mode.replace("-", " ").upper() or "UNKNOWN",
                                  "OSPF operational mode reported by the device.")
                out["state"] = op_mode
                out["state_label"] = state_meta[0]
                out["state_hint"] = state_meta[1]
                out["summary"] = state_meta[0] + ("" if procs else " — no OSPF process running")
                out["entries"] = rows
                out["count"] = len(rows)
            elif kind == "bgp":
                root = data.get("Cisco-IOS-XE-bgp-oper:bgp-state-data", {})
                rows = []
                for vrf in root.get("bgp-route-vrfs", {}).get("bgp-route-vrf") or []:
                    afis = vrf.get("bgp-route-afs", {}).get("bgp-route-af") or []
                    af_names = [str(a.get("afi-safi", "")).replace("ipv4-", "").replace("ipv6-", "")
                                for a in afis]
                    rows.append({
                        "vrf": vrf.get("vrf", "?"),
                        "address-families": ", ".join(af_names[:4]) or "—",
                        "af-count": len(af_names),
                    })
                rds = root.get("bgp-route-rds", {}).get("bgp-route-rd") or []
                out["rd-count"] = len(rds)
                out["summary"] = f"{len(rows)} route vrfs · {len(rds)} route rds"
                out["entries"] = rows
                out["count"] = len(rows)
            elif kind == "pkt-dist":
                # Tutorial "Packet size distribution": per-interface packet-size
                # buckets. Primary: controllers-oper (7 rx/tx buckets). If the
                # device does not serve that model (always-on Cat8kv 17.12
                # returns 404), fall back to interface counters as a packet-mix.
                entries = _pkt_dist_entries(_pkt_root(text))
                if entries:
                    out["mode"] = "buckets"
                    out["labels"] = list(PKT_LABELS)
                    out["entries"] = entries
                    out["count"] = len(entries)
                    if len(rows) > 1:
                        prev = _pkt_dist_entries(_pkt_root(rows[1]["payload"]))
                        if prev:
                            out["delta"] = _clamped_delta(prev, entries)
                            out["prev_ts"] = rows[1]["ts"]
                else:
                    if_rows = db.telemetry_history("interfaces", limit=2)
                    if if_rows:
                        cur = _mix_entries(_if_root(if_rows[0]["payload"]))
                        if cur:
                            out["mode"] = "mix"
                            out["labels"] = ["unicast", "multicast", "broadcast",
                                             "unknown"]
                            out["entries"] = cur
                            out["count"] = len(cur)
                            out["fallback"] = True
                            if len(if_rows) > 1:
                                prev = _mix_entries(_if_root(if_rows[1]["payload"]))
                                if prev:
                                    out["delta"] = _clamped_delta(prev, cur)
                                    out["prev_ts"] = if_rows[1]["ts"]
        except (ValueError, KeyError, TypeError):
            pass
        return out

    def telemetryRaw(self):
        rows = db.telemetry_history("interfaces", limit=1)
        return rows[0]["payload"] if rows else ""

    def collectTelemetry(self, kind):
        """Queue a live RESTCONF pull for one telemetry kind (async via engine)."""
        kind = kind or "interfaces"
        path = TELEMETRY_PATHS.get(kind)
        if not path:
            return {"ok": False, "queued": False, "error": "unknown telemetry kind"}
        self.engine.telemetry_raw(path)
        return {"ok": True, "queued": True, "kind": kind}

    def pickup(self):
        try:
            return json.loads(db.get_setting("pickup", "{}"))
        except (ValueError, TypeError):
            return {}

    def setPickup(self, key, value):
        cur = self.pickup()
        cur[key] = value
        db.set_setting("pickup", json.dumps(cur))
        return cur

    def profile(self):
        return self.state()["profile"]

    def creds(self):
        return self._masked_creds()

    def logs(self):
        return [
            {"ts": r["ts"], "level": r["level"], "source": r["source"], "msg": r["message"]}
            for r in db.recent_events(60)
        ]

    def audit(self):
        return [
            {"ts": r["ts"], "level": "ok" if r["fail_count"] == 0 else "fail",
             "source": r["filename"], "msg": f"PASS {r['pass_count']} / FAIL {r['fail_count']} / WARN {r['warn_count']}"}
            for r in db.audit_history(40)
        ]

    # ---------------- live engine tasks (async via engine thread) ----------------

    def _normalize(self, form):
        form = dict(form or {})
        try:
            form["vlan_id"] = int(form.get("vlan_id"))
        except (TypeError, ValueError):
            pass
        return form

    def provision(self, form):
        form = self._normalize(form)
        errs = self.validate(form)
        if errs:
            return {"ok": False, "queued": False, "errors": errs}
        try:
            ok, detail = self.engine.provision_sync(form, dry_run=False)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "queued": False, "detail": str(e)[:240]}
        return {"ok": bool(ok), "queued": True, "action": form["action"],
                "site_name": form.get("site_name"), "vlan_id": form.get("vlan_id"),
                "pc_ip": form.get("pc_ip"), "detail": detail}

    def deleteSub(self, form):
        form = self._normalize(form)
        ok, detail = self.engine.delete_branch_sync(form)
        return {"ok": ok, "queued": False, "detail": detail,
                "site": form.get("site_name"), "vlan_id": form.get("vlan_id")}

    def ping(self, host):
        try:
            dev = device_mode.active_device() or db.get_device_plain()
            from src.restconf_client import get, RestconfError
            params = {"host": dev["host"], "username": dev["username"],
                      "password": dev["password"], "https": True,
                      "verify_ssl": False, "port": 443}
            data = get(params, "Cisco-IOS-XE-native:native/hostname", timeout=12)
            return {"ok": True, "host": data.get("Cisco-IOS-XE-native:hostname", "")}
        except (RestconfError, KeyError, Exception):  # noqa: BLE001
            return {"ok": False}

    def snapshot(self):
        self.engine.snapshot()
        return {"ok": True, "queued": True}

    def drift(self):
        """Blocking drift check against the stored baseline — returns the real
        result (status / item count / diff preview) for the UI to render."""
        try:
            return self.engine.drift_sync()
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:240]}

    def setBaseline(self):
        """Capture the device's current running-config as the new baseline."""
        try:
            return self.engine.set_baseline_sync()
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:240]}

    def compliance(self):
        """Last saved audit report (scan runs in background via scanCompliance)."""
        try:
            audits = db.audit_history(1)
            if not audits:
                return {"ok": True, "score": 0, "ts": None,
                        "counts": {"pass": 0, "fail": 0, "warn": 0}, "checks": []}
            a = audits[0]
            results = []
            try:
                results = json.loads(a.get("results") or "[]")
            except (ValueError, TypeError):
                results = []
            total = a["pass_count"] + a["fail_count"] + a["warn_count"]
            return {
                "ok": True,
                "score": round(100 * a["pass_count"] / total) if total else 100,
                "ts": a["ts"],
                "counts": {"pass": a["pass_count"], "fail": a["fail_count"],
                           "warn": a["warn_count"]},
                "checks": [
                    {
                        "name": (r.get("check") if isinstance(r, dict) else "") or "check",
                        "status": str(r.get("status", "")).upper(),
                        "pass": str(r.get("status", "")).upper() == "PASS",
                        "detail": r.get("detail", "") if isinstance(r, dict) else "",
                    }
                    for r in results
                ],
            }
        except Exception:  # noqa: BLE001
            return {"ok": False, "score": 0, "ts": None,
                    "counts": {"pass": 0, "fail": 0, "warn": 0}, "checks": []}

    def scanCompliance(self, collect=True):
        """Queue a compliance scan; collect=True pulls a fresh live
        running-config first so the result reflects the device today."""
        self.engine.scan(collect_first=bool(collect))
        return {"ok": True, "queued": True, "collect": bool(collect)}

    # ---------------- netconf model explorer ----------------

    def netconfModules(self):
        """YANG module list advertised by the NETCONF :830 server (cached 60s).
        Failures are NOT cached — the UI RUN button retries reachability."""
        if (self._nc_mods is not None
                and time.time() - self._nc_mods_ts < 60):
            return self._nc_mods
        try:
            from src import netconf_explorer as ncx
            res = ncx.list_modules()
            if res.get("ok"):
                self._nc_mods = res
                self._nc_mods_ts = time.time()
            return res
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:240], "count": 0, "modules": []}

    def scanVlans(self, fresh=False):
        """VLAN occupancy scan for the provision studio (cached 60s on success).

        Live source: Cisco-IOS-XE-vlan-oper:vlans/vlan over RESTCONF.
        Fallback: subinterface tags from the cached interfaces telemetry, so the
        studio still knows what is taken when the device is briefly unreachable.
        Always returns a `suggestion` — lowest free ID >= 100.
        Pass fresh=True after a deploy/teardown to bypass the cache."""
        if fresh:
            self._vlan_scan = None
        if (self._vlan_scan is not None
                and time.time() - self._vlan_scan_ts < 60):
            return self._vlan_scan
        used, names = {}, {}
        via = "restconf-vlan-oper"
        try:
            from src import restconf_client
            _, params = restconf_client.get_restconf_device()
            data = restconf_client.get(
                params, "Cisco-IOS-XE-vlan-oper:vlans/vlan", timeout=15)
            for v in (data.get("Cisco-IOS-XE-vlan-oper:vlan") or []):
                if not isinstance(v, dict):
                    continue
                try:
                    vid = int(v.get("id"))
                except (TypeError, ValueError):
                    continue
                if 2 <= vid <= 4094:
                    used[vid] = str(v.get("name") or "")
        except Exception:  # noqa: BLE001 — device unreachable -> cached fallback
            via = "db-cached"
            rows = db.telemetry_history("interfaces", limit=1)
            if rows:
                try:
                    data = json.loads(rows[0]["payload"])
                    root = data.get("Cisco-IOS-XE-interfaces-oper:interfaces", {})
                    for e in (root.get("interface") or []):
                        name = str((e.get("name") or "").strip())
                        if "." not in name:
                            continue
                        tag = name.rsplit(".", 1)[1]
                        if tag.isdigit() and 2 <= int(tag) <= 4094:
                            used[int(tag)] = used.get(int(tag), "")
                except (ValueError, KeyError, AttributeError):
                    pass
        suggestion = next((i for i in range(100, 4095) if i not in used), 2)
        res = {
            "ok": True, "via": via, "count": len(used),
            "used": sorted(used), "names": {str(k): v for k, v in used.items()},
            "used_names": [{"name": n, "vlan": int(v)}
                           for v, n in sorted(used.items()) if n],
            "suggestion": suggestion,
        }
        self._vlan_scan = res
        self._vlan_scan_ts = time.time()
        return res

    def provisionPlan(self, fresh=False):
        """Fabric IP-plan facts for the provision studio (read-only, cached 60s).

        Uses the cached interfaces snapshot (same source as topology()):
          branches   -> [{vlan, site, subnet, gateway}]
          wan_ip     -> the physical L3 uplink IP (router_wan_ip prefill)
          ifaces     -> interface names (port suggestion hints)
        No live call is made — this endpoint must never block the studio.
        Pass fresh=True after a deploy/teardown to bypass the cache."""
        if fresh:
            self._plan = None
            self._plan_ts = 0
        if (getattr(self, "_plan", None) is not None
                and time.time() - getattr(self, "_plan_ts", 0) < 60):
            return self._plan
        branches, ifaces, wan_ip = [], [], ""
        rows = db.telemetry_history("interfaces", limit=1)
        if rows:
            try:
                data = json.loads(rows[0]["payload"])
                root = data.get("Cisco-IOS-XE-interfaces-oper:interfaces", {})
                for e in (root.get("interface") or []):
                    if not isinstance(e, dict):
                        continue
                    name = str((e.get("name") or "").strip())
                    ifaces.append(name)
                    ip, mask = e.get("ipv4") or "", e.get("ipv4-subnet-mask") or ""
                    if not ip or ip == "0.0.0.0":
                        continue
                    prefix = ""
                    subnet = ""
                    try:
                        net = ipaddress.ip_network(f"{ip}/{mask}", strict=False)
                        prefix = f"{ip}/{net.prefixlen}"
                        subnet = str(net)
                    except (ValueError, TypeError):
                        prefix = ip
                    if "." in name:
                        tag = name.rsplit(".", 1)[1]
                        if tag.isdigit() and 2 <= int(tag) <= 4094:
                            branches.append({
                                "vlan": int(tag),
                                "site": (str(e.get("description") or "").split(" ")[0]
                                         or f"VLAN {tag}"),
                                "subnet": subnet, "gateway": ip,
                            })
                    elif not wan_ip:
                        wan_ip = prefix
            except (ValueError, KeyError, AttributeError):
                pass
        res = {
            "ok": True, "via": "db-cached", "branches": branches,
            "wan_ip": wan_ip, "ifaces": sorted(set(ifaces)),
        }
        self._plan = res
        self._plan_ts = time.time()
        return res

    def netconfSchema(self, module):
        """Fetch one module's YANG source text via <get-schema> (read-only)."""
        try:
            from src import netconf_explorer as ncx
            return ncx.schema_of(str(module or "").strip())
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:240]}

    def netconfGet(self, filterXml):
        """Run a subtree <get> with the supplied XML filter (read-only)."""
        try:
            from src import netconf_explorer as ncx
            return ncx.subtree_get(str(filterXml or "").strip())
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:240]}

    def netconfNamespace(self, module):
        """Namespace declared by a module (helps build subtree filters)."""
        try:
            from src import netconf_explorer as ncx
            return ncx.module_namespace(str(module or "").strip())
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:240]}

    # ---------------- cli show runner (netmiko ssh) ----------------

    def cliRun(self, command):
        """Run one read-only show command over SSH :22 (netmiko cisco_xe)."""
        try:
            from src import cli_runner
            res = cli_runner.run_show(str(command or "").strip())
            db.log_action("CLI", "OK", f"show {str(command or '')[:80]}",
                          payload=json.dumps({"command": str(command or "")[:120]}),
                          device=_device_name())
            return res
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:240]}

    def cliArchiveDiff(self):
        """show archive config diff — last committed change vs running."""
        try:
            from src import cli_runner
            res = cli_runner.run_show("show archive config diff", timeout=90)
            db.log_action("CLI", "OK", "show archive config diff",
                          device=_device_name())
            return res
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:240]}

    # ---------------- config timeline / diff ----------------

    def configHistory(self):
        """Saved running-config snapshots (logs/*_running_config_*.txt),
        newest first — the timeline for config change archaeology."""
        log_dir = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "logs")
        items = []
        try:
            for f in sorted(os.listdir(log_dir)):
                if "_running_config_" in f and f.endswith(".txt"):
                    p = os.path.join(log_dir, f)
                    items.append({
                        "file": f,
                        "ts": f.rsplit("_", 1)[-1][:-4] or "?",
                        "size": os.path.getsize(p),
                    })
        except OSError as e:
            return {"ok": False, "error": str(e)[:200], "items": []}
        items.sort(key=lambda x: x["file"], reverse=True)
        return {"ok": True, "count": len(items), "items": items,
                "baseline": os.path.exists(BASELINE_PATH)}

    def configDiff(self, fileA="", fileB=""):
        """Unified diff between two saved config snapshots (default: latest
        vs baseline). Read-only, bounded to the newest 60k diff lines."""
        log_dir = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "logs")

        def read(f):
            if f and f != "baseline":
                p = os.path.join(log_dir, f)
                if not os.path.exists(p):
                    raise ValueError(f"snapshot not found: {f}")
            else:
                p = BASELINE_PATH
            with open(p, encoding="utf-8", errors="replace") as fh:
                return fh.read().splitlines()

        latest = None
        try:
            files = sorted(f for f in os.listdir(log_dir)
                           if "_running_config_" in f and f.endswith(".txt"))
        except OSError as e:
            return {"ok": False, "error": str(e)[:200]}
        if files:
            latest = files[-1]

        if not latest and not fileA:
            return {"ok": True, "diff": "", "a": "none", "b": "none",
                    "note": "no snapshots collected yet — press COLLECT NOW"}
        a_file = fileA or latest
        b_file = fileB or "baseline"
        if b_file == "baseline" and not os.path.exists(BASELINE_PATH):
            return {"ok": True, "diff": "",
                    "note": "no baseline yet — run BASELINE first",
                    "a": a_file, "b": "baseline"}
        a = read(a_file if a_file != "baseline" else "baseline")
        b = read(b_file if b_file != "baseline" else "baseline")
        import difflib
        diff = list(difflib.unified_diff(a, b, fromfile=a_file,
                                         tofile=b_file, lineterm=""))
        diff = diff[:60000]
        return {"ok": True, "diff": "\n".join(diff), "a": a_file,
                "b": b_file, "lines": len(diff),
                "note": "" if diff else "snapshots are identical"}

    # ---------------- watchdog (port flap / error burst) ----------------

    def watchdog(self):
        """Compare interface counters across the last snapshots and raise
        alerts for flaps, error bursts and up->down transitions.

        Pattern-detection only (client-side, mirrors the PortFlap/Spark EEM
        samples): the device itself has no guestshell to run EEM on the
        Catalyst 8000 sandbox, so detection happens here on collected data."""
        rows = db.iface_history(limit=2000)
        by_snap = {}
        for r in rows:
            by_snap.setdefault(r["snapshot_id"], []).append(r)
        snaps = sorted(by_snap, reverse=True)
        if len(snaps) < 2:
            return {"ok": True, "alerts": [], "summary": {"critical": 0,
                    "warn": 0, "info": 0},
                    "note": "need at least two snapshots — run COLLECT NOW twice",
                    "window": [str(r["ts"]) for r in rows[:1]]}
        prev_sid, cur_sid = snaps[1], snaps[0]
        prev = {r["if_name"]: r for r in by_snap[prev_sid]}
        cur = by_snap[cur_sid]
        alerts = []
        for r in cur:
            name = r["if_name"]
            p = prev.get(name)
            ts = str(r["ts"])
            if p is None:
                continue
            fl = (r["flaps"] or 0) - (p["flaps"] or 0)
            if fl > 0:
                alerts.append({"severity": "warn" if fl > 1 else "info",
                               "iface": name, "kind": "port-flap",
                               "detail": f"{fl} flap(s) since last snapshot",
                               "ts": ts})
            err = ((r["in_errors"] or 0) - (p["in_errors"] or 0)
                   + (r["out_errors"] or 0) - (p["out_errors"] or 0))
            crc = (r["crc_errors"] or 0) - (p["crc_errors"] or 0)
            if err > 100:
                alerts.append({"severity": "warn", "iface": name,
                               "kind": "error-burst",
                               "detail": f"+{err} input/output errors since last snapshot",
                               "ts": ts})
            if crc > 10:
                alerts.append({"severity": "warn", "iface": name,
                               "kind": "crc-burst",
                               "detail": f"+{crc} CRC errors since last snapshot",
                               "ts": ts})
            if (str(p.get("oper") or "").lower() in ("up", "ready")
                    and str(r.get("oper") or "").lower() not in ("up", "ready")):
                alerts.append({"severity": "critical", "iface": name,
                               "kind": "link-down",
                               "detail": "link dropped between snapshots",
                               "ts": ts})
        summary = {"critical": sum(1 for a in alerts if a["severity"] == "critical"),
                   "warn": sum(1 for a in alerts if a["severity"] == "warn"),
                   "info": sum(1 for a in alerts if a["severity"] == "info")}
        alerts.sort(key=lambda a: ({"critical": 0, "warn": 1, "info": 2}[a["severity"]],
                                   a["iface"]))
        window = sorted({str(r["ts"]) for r in by_snap[snaps[0]]})[:2]
        return {"ok": True, "alerts": alerts[:60], "summary": summary,
                "note": "compared last two snapshots", "window": window}

    # ---------------- extra restconf verbs (dns post / ip delete) ----------------

    def dnsAdd(self, domain):
        """POST a domain name into native/ip/domain.

        IOS XE 17.x models the domain list as a single-instance
        name-container/name-no-vrf, so a fresh instance is created with
        POST (older list-form) and an existing one replaced via PATCH."""
        try:
            from src.restconf_client import post, patch, get_restconf_device
            domain = str(domain or "").strip()
            if not domain:
                return {"ok": False, "error": "domain required"}
            _, rc = get_restconf_device(None)
            verb = "PATCH"
            try:
                post(rc, "Cisco-IOS-XE-native:native/ip/domain/name-container",
                     {"name-no-vrf": domain})
                verb = "POST"
            except Exception:
                try:
                    post(rc, "Cisco-IOS-XE-native:native/ip/domain",
                         {"name": domain})
                    verb = "POST"
                except Exception:
                    patch(rc,
                          "Cisco-IOS-XE-native:native/ip/domain/"
                          "name-container",
                          {"Cisco-IOS-XE-native:name-container":
                           {"name-no-vrf": domain}})
            db.log_action("DNS", "OK",
                          f"domain {domain} applied via {verb} "
                          f"(name-container/name-no-vrf)",
                          device=_device_name())
            db.log_ledger("WRITE", db.get_setting("session", ""), "dns-add",
                          payload={"domain": domain, "verb": verb})
            return {"ok": True, "domain": domain, "verb": verb}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:240]}

    def ifaceIpDelete(self, iface):
        """DELETE the primary IPv4 from an interface (list-instance delete)."""
        try:
            from src.restconf_client import delete, get_restconf_device
            iface = str(iface or "").strip()
            if not iface:
                return {"ok": False, "error": "interface required"}
            name = iface.replace("/", "%2F")
            if not name.lower().startswith("gigabitethernet"):
                name = "GigabitEthernet=" + name
            _, rc = get_restconf_device(None)
            delete(rc, "Cisco-IOS-XE-native:native/interface/"
                       f"{name}/ip/address/primary")
            db.log_action("IFACE", "OK",
                          f"primary IPv4 removed from {iface} (DELETE)",
                          device=_device_name())
            db.log_ledger("WRITE", db.get_setting("session", ""), "iface-ip-delete",
                          payload={"iface": iface})
            return {"ok": True, "iface": iface}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)[:240]}

    # ---------------- security console (audit page) ----------------

    def security(self):
        """Rich audit-page payload: last scan checks + ledger + integrity."""
        try:
            audits = db.audit_history(1)
            last = audits[0] if audits else None
            results = []
            if last:
                try:
                    results = json.loads(last.get("results") or "[]")
                except (ValueError, TypeError):
                    results = []
            total = (last["pass_count"] + last["fail_count"] + last["warn_count"]
                     if last else 0)
            return {
                "ok": True,
                "scan": {"ts": last["ts"], "filename": last["filename"]}
                if last else None,
                "score": round(100 * last["pass_count"] / total) if total else 0,
                "counts": {"pass": last["pass_count"] if last else 0,
                           "fail": last["fail_count"] if last else 0,
                           "warn": last["warn_count"] if last else 0},
                "checks": [
                    {
                        "id": str(r.get("id", "")),
                        "check": str(r.get("check", "")),
                        "category": str(r.get("category", "OTHER")),
                        "severity": str(r.get("severity", "medium")),
                        "status": str(r.get("status", "WARN")).upper(),
                        "evidence": str(r.get("evidence", "")),
                        "remediation_id": r.get("remediation_id") or None,
                    }
                    for r in results if isinstance(r, dict)
                ],
                "ledger": db.ledger_chain(30),
                "verify": db.verify_ledger(),
            }
        except Exception:  # noqa: BLE001
            return {"ok": False, "scan": None, "score": 0,
                    "counts": {"pass": 0, "fail": 0, "warn": 0},
                    "checks": [], "ledger": [], "verify": {"ok": True,
                    "total": 0, "broken_at": None, "last_hash": ""}}

    def securityPosture(self, force=False):
        """Live read-only posture survey (cached 60s). force=1 re-pulls."""
        if (not force and self._posture is not None
                and time.time() - self._posture_ts < 60):
            return self._posture
        self._posture = self.engine.posture_sync()
        self._posture_ts = time.time()
        return self._posture

    def verifyAudit(self):
        return db.verify_ledger()

    def remediate(self, checkId, ack=False, value=""):
        """Live remediation write. `ack` is the explicit UI confirmation —
        without it nothing is ever pushed to the device (only a ledger note)."""
        if not ack:
            if checkId:
                db.log_ledger("REMEDIATION", db.get_setting("session", ""),
                              f"cancelled:{str(checkId)}", payload={})
            return {"ok": False, "reason": "confirmation required"}
        return self.engine.remediate(str(checkId or "").strip(), str(value or ""))

    def remediateAll(self, ack=False):
        """Batch remediate every fixable failing check (value-less specs plus
        the banner default). Value-required checks are skipped in the batch.
        Same acknowledgement gate as `remediate`."""
        if not ack:
            db.log_ledger("REMEDIATION", db.get_setting("session", ""),
                          "cancelled:fix-all", payload={})
            return {"ok": False, "reason": "confirmation required"}
        return self.engine.remediate_all()

    def revert(self, checkId, ack=False):
        """Undo a remediation (e.g. restore the default banner). Same gate."""
        if not ack:
            if checkId:
                db.log_ledger("REMEDIATION", db.get_setting("session", ""),
                              f"revert-cancelled:{str(checkId)}", payload={})
            return {"ok": False, "reason": "confirmation required"}
        return self.engine.revert(str(checkId or "").strip())

    def factory(self, checkId, ack=False):
        """Restore the factory default (e.g. DELETE the MOTD banner entirely,
        back to 'no banner motd'). Same gate."""
        if not ack:
            if checkId:
                db.log_ledger("REMEDIATION", db.get_setting("session", ""),
                              f"factory-cancelled:{str(checkId)}", payload={})
            return {"ok": False, "reason": "confirmation required"}
        return self.engine.factory(str(checkId or "").strip())

    # ---------------- ops tools (Cisco-approved RESTCONF operations) ----------------

    def inventory(self):
        """Queue hardware inventory pull -> onResult({id:'INVENTORY', data:[…]})"""
        self.engine.inventory()
        return {"ok": True, "queued": True}

    def getHostname(self):
        self.engine.get_hostname()
        return {"ok": True, "queued": True}

    def setHostname(self, name):
        name = str(name or "").strip()
        if not name or len(name) > 63:
            return {"ok": False, "queued": False, "error": "hostname 1-63 chars"}
        self.engine.set_hostname(name)
        return {"ok": True, "queued": True}

    def setIfaceIp(self, iface, address, mask):
        iface = str(iface or "").strip()
        if not re.match(r"^\d+(/\d+){1,2}$", iface):
            return {"ok": False, "queued": False, "error": "bad interface (e.g. 0/0/0)"}
        if not (_valid_ip(address) and _valid_ip(mask)):
            return {"ok": False, "queued": False, "error": "bad IPv4 address/mask"}
        self.engine.set_interface_ip(iface, address, mask)
        return {"ok": True, "queued": True}

    def setIfaceState(self, iface, up=True):
        iface = str(iface or "").strip()
        if not iface:
            return {"ok": False, "queued": False, "error": "interface name required"}
        self.engine.set_interface_state(iface, bool(up))
        return {"ok": True, "queued": True}

    def ifaceConfig(self):
        self.engine.get_interface_config()
        return {"ok": True, "queued": True}


# ---------------- static file server (same-origin for the UI) ----------------

class _Handler(SimpleHTTPRequestHandler):
    CUST_ICONS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_DIR, **kwargs)

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/cust-icons/"):
            name = os.path.basename(self.path.split("?")[0])
            if name.endswith(".svg") and re.match(r"^[\w-]+\.svg$", name):
                src = os.path.join(self.CUST_ICONS, name)
                if os.path.isfile(src):
                    try:
                        with open(src, "rb") as fh:
                            self.send_response(200)
                            self.send_header("Content-Type", "image/svg+xml")
                            self.send_header("Cache-Control", "no-store")
                            self.send_header("Content-Length", str(os.path.getsize(src)))
                            self.end_headers()
                            self.wfile.write(fh.read())
                        return
                    except OSError:
                        pass
            self.send_error(404)
            return
        super().do_GET()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *a):
        pass


def _serve():
    ThreadingHTTPServer.allow_reuse_address = True
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), _Handler)
    httpd.serve_forever()


def main():
    import webview

    if "--no-window" in sys.argv:
        _smoke()
        return

    if "--serve-only" in sys.argv:
        threading.Thread(target=_serve, daemon=True).start()
        print(f"serving http://127.0.0.1:{PORT}/index.html  (ctrl-c to stop)")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
        return

    threading.Thread(target=_serve, daemon=True).start()

    api = Api()
    window = webview.create_window(
        "CAT8k-SYNC // CONTROL CLOUD",
        url=f"http://127.0.0.1:{PORT}/index.html",
        js_api=api,
        width=1480, height=940,
        min_size=(1180, 720),
        background_color="#0a0f1a",
    )
    api.set_window(window)
    webview.start(gui="edgechromium")


def _smoke():
    """Headless check that the bridge layer can be constructed and queried."""
    api = Api()
    print("state:", json.dumps(api.state(), default=str))
    print("series:", {k: len(v["vals"]) for k, v in api.series().items()})
    print("stats:", json.dumps(api.stats(), default=str))
    print("validate(empty):", json.dumps(api.validate({})))
    print("validate(add_branch):", json.dumps(api.validate({
        "action": "add_branch", "site_name": "BR-X", "department_vlan": "100",
        "vlan_name": "finance", "department_subnet": "10.1.100.0/24",
        "gateway": "10.1.100.1", "router_wan_ip": "172.16.2.1",
    })))
    print("telemetry:", json.dumps(api.telemetry("interfaces"), default=str)[:400])
    print("logs:", len(api.logs()))
    print("SMOKE OK")


if __name__ == "__main__":
    main()

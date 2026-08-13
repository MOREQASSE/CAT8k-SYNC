"""Threaded bridge between the GUI and the automation engine (src/*).

Every task runs off the Tk main thread, captures the engine's stdout into a
string buffer, and reports back through `on_done(label, log_text, result)`.
"""
import contextlib
import io
import json
import os
import re
import sys
import threading
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import yaml

from src.connector import load_devices
from src.deployer import build_operations, deploy_restconf, get_physical_parent_interface
from src.parser import collect_config_restconf, scan_compliance
from src.automation import (
    delete_subinterface,
    device_snapshot,
    drift_check,
    dump_json,
    render_snapshot,
    set_baseline as set_baseline_fn,
)
from src import db
from src.restconf_client import (
    RestconfError,
    connect_test_restconf,
    delete,
    get,
    get_restconf_device,
    patch,
    put,
)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE_PATH = os.path.join(BASE, "logs", "baseline_running_config.txt")


def _telemetry_kind(path):
    """Derive a short kind tag from a YANG path."""
    if "interface" in path:
        return "interfaces"
    if "arp" in path:
        return "arp"
    if "ospf" in path:
        return "ospf"
    if "bgp" in path:
        return "bgp"
    if "controller" in path:
        return "pkt-dist"
    return "raw"


def _dev_name():
    try:
        return load_devices()[0]["name"]
    except (IndexError, OSError):
        return "?"


def _json_dump(obj):
    try:
        return json.dumps(obj, default=str)
    except (TypeError, ValueError):
        return ""


def _actor():
    """Session actor for ledger provenance (empty = system)."""
    try:
        return db.get_setting("session", "")
    except Exception:  # noqa: BLE001
        return ""


# YANG write snippets + CLI equivalents for each remediable check id.
# `body` may be a callable(value) for checks needing operator input.
BANNER_DEFAULT = "Authorized access only. All activity is monitored."
REMEDIATIONS = {
    "ssh-version": {
        "cli": ["ip ssh version 2"],
        "path": "Cisco-IOS-XE-native:native/ip",
        "body": {"Cisco-IOS-XE-native:ip": {"ssh": {"version": 2}}},
        "alt_body": {"Cisco-IOS-XE-native:ip": {"ssh": {"version": "2"}}},
        "summary": "Force SSH v2 (blocks SSHv1)",
    },
    "vty-transport": {
        "cli": ["line vty 0 4", " transport input ssh"],
        "path": "Cisco-IOS-XE-native:native/line/vty=0",
        "body": {"Cisco-IOS-XE-native:vty": [
            {"first": 0, "transport": {"input": {"input": ["ssh"]}}}]},
        "summary": "Restrict vty 0-4 to SSH input",
    },
    "exec-timeout": {
        "cli": ["line vty 0 4", " exec-timeout 10 0"],
        "path": "Cisco-IOS-XE-native:native/line/vty=0",
        "body": {"Cisco-IOS-XE-native:vty": [
            {"first": 0, "exec-timeout": {"minutes": 10}}]},
        "alt_body": {"Cisco-IOS-XE-native:vty": [
            {"first": 0, "exec-timeout": [{"time": 10, "minute": 0}]}]},
        "summary": "Set 10m idle session timeout on vty 0-4",
    },
    "password-encryption": {
        "cli": ["service password-encryption"],
        "path": "Cisco-IOS-XE-native:native/service",
        "body": {"Cisco-IOS-XE-native:service": {"password-encryption": [None]}},
        "summary": "Enable type-7 password encryption",
    },
    "enable-secret": {
        "cli": ["enable secret 9 <NEW-SECRET>"],
        "path": "Cisco-IOS-XE-native:native/enable",
        "body": lambda v: {"Cisco-IOS-XE-native:enable": {
            "secret": {"type": 9, "secret": str(v)}}},
        "needs_value": "New enable secret",
        "summary": "Install enable secret with type-9 hash",
    },
    "http-plane": {
        "cli": ["ip http secure-server"],
        "path": "Cisco-IOS-XE-native:native/ip/Cisco-IOS-XE-http:http",
        "body": {"http": {"secure-server": True}},
        "summary": "Enable HTTPS-only management HTTP",
    },
    "domain-lookup": {
        "cli": ["no ip domain lookup"],
        "path": "Cisco-IOS-XE-native:native/ip/domain",
        "body": {"Cisco-IOS-XE-native:domain": {"lookup": False}},
        "summary": "Disable IP domain lookup (anti-DNS poisoning)",
    },
    "syslog": {
        "cli": ["logging host <SYSLOG-SERVER-IP>"],
        "path": "Cisco-IOS-XE-native:native/logging",
        "body": lambda v: {"Cisco-IOS-XE-native:logging": {
            "host": [{"ip": str(v)}]}},
        "needs_value": "Syslog server IP",
        "summary": "Point syslog at a collector",
    },
    "ntp": {
        "cli": ["ntp server <NTP-SERVER-IP>"],
        "path": "Cisco-IOS-XE-native:native/ntp",
        "body": lambda v: {"Cisco-IOS-XE-native:ntp": {
            "server": [{"ip": str(v)}]}},
        "needs_value": "NTP server IP",
        "summary": "Synchronize clock (log integrity)",
    },
    "banner": {
        "cli": ["banner motd ^C <your phrase> ^C"],
        "path": "Cisco-IOS-XE-native:native/banner",
        "body": lambda v: {"Cisco-IOS-XE-native:banner": {"motd": {
            "banner": str(v).strip() or BANNER_DEFAULT}}},
        "needs_value": "Banner phrase",
        "default": BANNER_DEFAULT,
        "summary": "Set legal MOTD banner",
        "revert": {
            "path": "Cisco-IOS-XE-native:native/banner",
            "body": {"Cisco-IOS-XE-native:banner": {"motd": {
                "banner": BANNER_DEFAULT}}},
            "summary": "restored the default banner phrase",
        },
        "factory": {
            "path": "Cisco-IOS-XE-native:native/banner/motd",
            "summary": "removed the MOTD banner (Catalyst factory default: none)",
        },
    },
}

POSTURE_PATHS = (
    ("nacm", "ietf-netconf-acm:nacm"),
    ("aaa", "Cisco-IOS-XE-native:native/aaa"),
    ("ssh", "Cisco-IOS-XE-native:native/ip/ssh"),
    ("http", "Cisco-IOS-XE-native:native/ip/Cisco-IOS-XE-http:http"),
)


def _posture_summary(items):
    """Derive boolean posture flags from the read-only GET responses."""
    by = {i["kind"]: i for i in items}
    summary = {}
    nacm = by.get("nacm", {}).get("data", {})
    summary["nacm"] = bool(
        (nacm.get("ietf-netconf-acm:nacm") or {}).get("enable-nacm"))
    aaa = json.dumps(by.get("aaa", {}).get("data", {}))
    summary["aaa_new_model"] = "new-model" in aaa
    ssh = by.get("ssh", {}).get("data", {})
    ssh_core = ssh.get("Cisco-IOS-XE-native:ssh") or ssh
    summary["ssh_v2"] = str(ssh_core.get("version") or "") == "2.0" or \
        str(ssh_core.get("version") or "") == "2"
    http = by.get("http", {}).get("data", {})
    http_core = http.get("http") or http
    summary["http_secure"] = bool(http_core.get("secure-server"))
    summary["http_plain"] = bool(http_core.get("server"))
    return summary


class Engine:
    def __init__(self, on_done, on_start=None):
        self.on_done = on_done
        self.on_start = on_start
        db.init()

    def device_names(self):
        return [d["name"] for d in load_devices()]

    def device_host(self):
        devs = load_devices()
        return devs[0]["host"] if devs else "?"

    def _run(self, label, fn, *args, **kwargs):
        if self.on_start:
            self.on_start(label)

        def target():
            buf = io.StringIO()
            result = None
            try:
                with contextlib.redirect_stdout(buf):
                    result = fn(*args, **kwargs)
            except Exception as e:  # noqa: BLE001 - surface everything to the GUI
                buf.write(f"\n[FATAL] {e}\n")
                result = None
            self.on_done(label, buf.getvalue(), result)

        threading.Thread(target=target, daemon=True).start()

    # ---------------- tasks ----------------

    def connect(self):
        def fn():
            ok = connect_test_restconf()
            db.log_event("INFO", "CONNECT",
                         "connection test " + ("PASSED" if ok else "FAILED"))
            return ok

        self._run("CONNECT", fn)

    def ping_backend(self):
        """Quiet reachability probe: returns device hostname or None."""

        def fn():
            _, rc = get_restconf_device(None)
            try:
                data = get(rc, "Cisco-IOS-XE-native:native/hostname", timeout=12)
                return data.get("Cisco-IOS-XE-native:hostname") or ""
            except RestconfError:
                return None

        self._run("PING", fn)

    def test_connection(self, host, username, password, https=True,
                        verify_ssl=False, port=443):
        """Synchronous RESTCONF probe with explicit credentials (profile page)."""
        params = {"host": host, "username": username, "password": password,
                  "https": https, "verify_ssl": verify_ssl, "port": port}
        try:
            data = get(params, "Cisco-IOS-XE-native:native/hostname", timeout=15)
            return data.get("Cisco-IOS-XE-native:hostname") or ""
        except RestconfError:
            return None

    def reload_devices(self):
        """Re-read the device vault after a profile save (fresh each call anyway)."""
        db.log_event("INFO", "PROFILE", "device vault reloaded")
        return load_devices()

    def provision(self, action_data, dry_run):
        def fn():
            dev = action_data.get("device") or _dev_name()
            try:
                ok = deploy_restconf(action_data, device_name=action_data.get("device"),
                                     dry_run=dry_run)
                db.log_action("PROVISION", "OK" if ok else "FAIL",
                              "dry-run" if dry_run else ("deployed" if ok else "one or more operations failed"),
                              payload=_json_dump(action_data), device=dev)
                db.log_ledger("WRITE", _actor(), "provision",
                              payload={**action_data, "dry_run": bool(dry_run),
                                       "result": "ok" if ok else "failed"})
            except Exception as e:
                db.log_action("PROVISION", "FAIL", str(e)[:200],
                              payload=_json_dump(action_data), device=dev)
                db.log_ledger("WRITE", _actor(), "provision:failed",
                              payload={"error": str(e)[:300]})
                raise

        self._run("PROVISION", fn)

    def collect(self):
        def fn():
            _, rc = get_restconf_device(None)
            collect_config_restconf(rc)
            db.log_action("COLLECT", "OK", "running config collected",
                          device=_dev_name())

        self._run("COLLECT", fn)

    def telemetry_interfaces(self):
        _, rc = get_restconf_device(None)

        def fn():
            return json.dumps(get(rc, "Cisco-IOS-XE-interfaces-oper:interfaces"),
                              indent=2)

        self._run("TELEMETRY", fn)

    def telemetry_ospf(self):
        _, rc = get_restconf_device(None)

        def fn():
            return json.dumps(get(rc, "Cisco-IOS-XE-ospf-oper:ospf-oper-data"),
                              indent=2)

        self._run("TELEMETRY", fn)

    def telemetry_raw(self, path):
        def fn():
            _, rc = get_restconf_device(None)
            try:
                text = dump_json(rc, path)
            except RestconfError:
                if _telemetry_kind(path) != "pkt-dist":
                    raise
                # controllers-oper not served (Cat8kv always-on returns 404):
                # store a marker and refresh interfaces-oper so the
                # packet-mix fallback renders from fresh counters.
                text = json.dumps({"restconf-error":
                                   "controllers-oper not served by this device"})
                try:
                    iface_text = dump_json(rc, "Cisco-IOS-XE-interfaces-oper:interfaces")
                    db.save_telemetry("interfaces", "Cisco-IOS-XE-interfaces-oper:interfaces",
                                      iface_text)
                except RestconfError:
                    pass
            db.save_telemetry(_telemetry_kind(path), path, text)
            return text

        self._run("TELEMETRY", fn)

    def snapshot(self):
        def fn():
            _, rc = get_restconf_device(None)
            snap = device_snapshot(rc)
            db.save_snapshot(snap)
            db.log_ledger("STATE", _actor(), "snapshot",
                          payload={"hostname": snap.get("hostname", "")})
            return render_snapshot(snap)

        self._run("SNAPSHOT", fn)

    def drift(self):
        def fn():
            _, rc = get_restconf_device(None)
            diff = drift_check(rc, BASELINE_PATH)
            status = "CLEAN" if not diff else "DRIFT"
            db.save_drift(status, str(diff or ""))
            db.log_ledger("STATE", _actor(), "drift-check",
                          payload={"status": status})
            return diff

        self._run("DRIFT", fn)

    def drift_sync(self):
        """Blocking drift check: collect the live config, diff it against the
        stored baseline, persist and return a real result dict for the UI."""
        _, rc = get_restconf_device(None)
        diff = drift_check(rc, BASELINE_PATH)
        status = "CLEAN" if not diff else "DRIFT"
        db.save_drift(status, str(diff or ""))
        db.log_ledger("STATE", _actor(), "drift-check",
                      payload={"status": status})
        return {
            "ok": True,
            "status": status,
            "count": len(diff) if diff else 0,
            "diff": str(diff or "")[:4000],
            "baseline_exists": os.path.exists(BASELINE_PATH),
            "ts": db.now(),
        }

    def set_baseline(self):
        def fn():
            _, rc = get_restconf_device(None)
            set_baseline_fn(rc, BASELINE_PATH)
            db.log_action("BASELINE", "OK", "baseline captured",
                          device=_dev_name())
            return True

        self._run("BASELINE", fn)

    def set_baseline_sync(self):
        """Blocking baseline capture: overwrite the baseline file with the
        device's current running-config."""
        _, rc = get_restconf_device(None)
        set_baseline_fn(rc, BASELINE_PATH)
        db.log_action("BASELINE", "OK", "baseline captured",
                      device=_dev_name())
        return {"ok": True, "ts": db.now()}

    def delete_branch(self, action_data):
        def fn():
            _, rc = get_restconf_device(action_data.get("device"))
            name = delete_subinterface(rc, action_data["vlan_id"])
            print(f"[RESTCONF] DELETED subinterface {name}")
            db.log_action("DELETE", "OK", f"deleted {name}",
                          payload=_json_dump(action_data),
                          device=action_data.get("device") or _dev_name())
            db.log_ledger("WRITE", _actor(), "delete-branch",
                          payload={"vlan_id": action_data["vlan_id"]})
            return True

        self._run("DELETE", fn)

    def delete_branch_sync(self, action_data):
        """Blocking teardown for the web bridge — returns (ok, detail).

        The web UI needs a truthful answer (the async `_run` path swallows
        RESTCONF errors and would toast "applied" on a failed DELETE).
        """
        try:
            _, rc = get_restconf_device(action_data.get("device"))
            name = delete_subinterface(rc, action_data["vlan_id"])
            print(f"[RESTCONF] DELETED subinterface {name}")
            db.log_action("DELETE", "OK", f"deleted {name}",
                          payload=_json_dump(action_data),
                          device=action_data.get("device") or _dev_name())
            db.log_ledger("WRITE", _actor(), "delete-branch",
                          payload={"vlan_id": action_data["vlan_id"]})
            return True, f"deleted {name}"
        except Exception as e:  # noqa: BLE001 — surface the real error to the UI
            print(f"[RESTCONF] DELETE failed: {e}")
            db.log_action("DELETE", "FAIL", str(e)[:300],
                          payload=_json_dump(action_data),
                          device=action_data.get("device") or _dev_name())
            return False, str(e)

    def preview(self, action_data):
        """Render the exact RESTCONF calls for the current form (no push)."""

        def fn():
            _, rc = get_restconf_device(action_data.get("device"))
            if action_data["action"] == "delete_branch":
                parent = get_physical_parent_interface(rc)
                name = f"GigabitEthernet{parent}.{action_data['vlan_id']}"
                return (f"--- delete subinterface ---\n"
                        f"DELETE /restconf/data/Cisco-IOS-XE-native:native/\n"
                        f"       interface/GigabitEthernet={name}\n\n"
                        f"Removes the VLAN {action_data['vlan_id']} branch gateway "
                        f"in one call. No payload needed.")
            ops = build_operations(action_data, rc)
            parts = []
            for method, label, path, payload in ops:
                parts.append(f"--- {label} -> /restconf/data/{path} ({method}) ---\n"
                             f"{json.dumps(payload, indent=2)}")
            return "\n\n".join(parts)

        self._run("PREVIEW", fn)

    def scan(self, collect_first):
        def fn():
            if collect_first:
                _, rc = get_restconf_device(None)
                collect_config_restconf(rc)
            log_dir = os.path.join(BASE, "logs")
            files = sorted(
                f for f in os.listdir(log_dir)
                if "_running_config_" in f and f.endswith(".txt")
            )
            if not files:
                print("No collected running-config found. Run COLLECT first.")
                return {"filename": None, "results": []}
            filename = files[-1]
            with open(os.path.join(log_dir, filename)) as fh:
                config_text = fh.read()
            results = scan_compliance(config_text)
            db.save_audit(filename, results)
            db.log_ledger("SCAN", _actor(), "compliance-scan",
                          payload={"filename": filename,
                                   "checks": len(results)})
            print(f"Audited {filename}")
            return {"filename": filename, "results": results}

        self._run("AUDIT", fn)

    # ---------------- security: posture (read-only) + remediation (write) ----

    def posture_sync(self):
        """Read-only NACM/AAA/SSH/HTTP-plane survey. Blocking — call from a
        bridge thread, not the UI thread. Never mutates the device."""
        out = {"ok": False, "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
               "error": "", "items": [], "summary": {}}
        try:
            _, rc = get_restconf_device(None)
        except Exception as e:  # noqa: BLE001
            out["error"] = f"device lookup failed: {e}"
            return out
        for kind, path in POSTURE_PATHS:
            entry = {"kind": kind, "path": path, "data": {}, "error": ""}
            try:
                entry["data"] = get(rc, path, timeout=15)
            except RestconfError as e:
                entry["error"] = str(e)
            out["items"].append(entry)
        out["ok"] = True
        out["summary"] = _posture_summary(out["items"])
        return out

    def test_credentials(self, host, username, password):
        """Probe a RESTCONF device with ad-hoc credentials (nothing saved):
        a single lightweight GET of the hostname leaf, classified errors."""
        params = {
            "host": str(host or "").strip(),
            "username": str(username or "").strip(),
            "password": str(password or ""),
            "https": True, "verify_ssl": False, "port": 443,
        }
        try:
            data = get(params, "Cisco-IOS-XE-native:native/hostname", timeout=25)
            hostname = (data.get("Cisco-IOS-XE-native:hostname") or "").strip()
            return {"ok": True, "hostname": hostname or "?", "user": params["username"]}
        except RestconfError as e:
            msg = str(e)
            if "401" in msg or "403" in msg:
                err = ("authentication failed (401) — wrong credentials, "
                       "or the DevNet reservation expired (rotates every 3 days)")
            elif "502" in msg or "backend cycling" in msg:
                err = "sandbox backend cycling (HTTP 502) — retry in a minute"
            elif "timed out" in msg.lower() or "connect" in msg.lower() \
                    or "name resolution" in msg.lower():
                err = "host unreachable — is the reservation still live?"
            else:
                err = msg[:240]
            return {"ok": False, "error": err}

    def remediate_all(self):
        """Batch remediate every check that can be applied without operator
        input (value-less specs, plus the banner default). Checks that need a
        typed value (enable-secret, syslog, ntp) are reported as skipped.

        One write per check (no per-write rescan), then a single final
        collect + rescan so the audit reflects the whole batch."""
        _, rc = get_restconf_device(None)
        results = []
        for check_id, spec in REMEDIATIONS.items():
            # skip checks whose body needs operator input with no usable default
            if spec.get("needs_value") and not spec.get("default"):
                results.append({"id": check_id, "ok": None,
                                "reason": "needs-operator-value"})
                continue
            value = spec.get("default", "") if spec.get("needs_value") else ""
            body = spec["body"](value) if callable(spec["body"]) else spec["body"]
            res = self._commit(rc, check_id, spec["path"], body,
                               kind="remediate", summary=spec.get("summary", ""),
                               rescan=False)
            if not res.get("ok") and spec.get("alt_body") is not None:
                res = self._commit(rc, check_id, spec["path"], spec["alt_body"],
                                   kind="remediate",
                                   summary=spec.get("summary", "") + " (legacy model)",
                                   rescan=False)
            results.append({"id": check_id, "ok": res.get("ok", False),
                            "reason": res.get("reason")})
        scan = None
        try:
            scan = self._rescan_locked(rc, "fix-all")
        except Exception:  # noqa: BLE001
            scan = None
        return {"ok": True, "results": results, "scan": scan}

    def remediate(self, check_id, value=""):
        """Live RESTCONF write for one remediation spec (blocking).

        The UI gate (shared-sandbox warning + explicit confirm) happens before
        this is called; here we only execute and log. Returns the write outcome
        with a redacted diff for the ledger."""
        spec = REMEDIATIONS.get(check_id)
        if not spec:
            return {"ok": False, "reason": f"no remediation defined for {check_id}"}
        try:
            _, rc = get_restconf_device(None)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "reason": f"device lookup failed: {e}"}
        body = spec["body"](value) if callable(spec["body"]) else spec["body"]
        res = self._commit(rc, check_id, spec["path"], body,
                           kind="remediate", summary=spec.get("summary", ""))
        if not res.get("ok") and spec.get("alt_body") is not None:
            res = self._commit(rc, check_id, spec["path"], spec["alt_body"],
                               kind="remediate",
                               summary=spec.get("summary", "") + " (legacy model)")
        return res

    def revert(self, check_id):
        """Undo a remediation: write the revert body for the check (e.g. the
        default banner) then re-collect + rescan so the audit reflects it."""
        spec = REMEDIATIONS.get(check_id)
        rev = spec and spec.get("revert")
        if not rev:
            return {"ok": False, "reason": f"no revert defined for {check_id}"}
        try:
            _, rc = get_restconf_device(None)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "reason": f"device lookup failed: {e}"}
        body = rev["body"](spec) if callable(rev["body"]) else rev["body"]
        return self._commit(rc, check_id, rev["path"], body,
                            kind="revert", summary=rev.get("summary",
                                                           "reverted to default"))

    def factory(self, check_id):
        """Restore the factory default for a check: DELETE the YANG node (e.g.
        the whole MOTD banner -> 'no banner motd'), then re-collect + rescan."""
        spec = REMEDIATIONS.get(check_id)
        fac = spec and spec.get("factory")
        if not fac:
            return {"ok": False, "reason": f"no factory spec for {check_id}"}
        try:
            _, rc = get_restconf_device(None)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "reason": f"device lookup failed: {e}"}
        return self._commit(rc, check_id, fac["path"], None,
                            kind="factory", summary=fac.get("summary",
                                                            "factory default"))

    def _commit(self, rc, check_id, path, body, kind, summary, rescan=True):
        """Shared write-and-verify used by remediate()/revert()/factory():
        PATCH (or DELETE for factory) the live device, record it in the audit
        ledger, then re-collect + rescan the running-config so audits reflect
        the actual device state."""
        op = "delete" if kind == "factory" else "patch"
        diff = {"path": path, "delete": True} if op == "delete" \
            else {"path": path, "body": body}
        label = {"remediate": "REMEDIATE", "revert": "REVERT",
                 "factory": "FACTORY"}.get(kind, "WRITE")
        try:
            if op == "delete":
                delete(rc, path)
            else:
                patch(rc, path, body)
        except RestconfError as e:
            tag = f"failed:{check_id}" if kind == "remediate" \
                else f"{kind}-failed:{check_id}"
            db.log_ledger("REMEDIATION", _actor(), tag,
                          payload={"diff": diff, "error": str(e)})
            db.log_action(label, "FAIL", f"{check_id}: {e}"[:200],
                          payload=_json_dump(diff), device=_dev_name())
            return {"ok": False, "reason": str(e), "diff": diff}
        tag = check_id if kind == "remediate" else f"{kind}:{check_id}"
        db.log_ledger("REMEDIATION", _actor(), tag, payload=diff)
        msg = (f"{check_id} applied ({summary})" if label == "REMEDIATE"
               else f"{check_id} {label.lower()} ({summary})")
        db.log_action(label, "OK", msg[:200],
                      payload=_json_dump(diff), device=_dev_name())
        db.log_event("OK", label, f"{check_id} -> {summary}")
        # re-collect + rescan so the next audit reflects the write
        scan = self._rescan_locked(rc, check_id) if rescan else None
        return {"ok": True, "check_id": check_id, "summary": summary,
                "diff": diff, "scan": scan, "action": kind}

    def _rescan_locked(self, rc, check_id):
        """Collect the live running-config, rescan and store — best effort."""
        try:
            collect_config_restconf(rc)
            log_dir = os.path.join(BASE, "logs")
            files = sorted(
                f for f in os.listdir(log_dir)
                if "_running_config_" in f and f.endswith(".txt"))
            if not files:
                return None
            filename = files[-1]
            with open(os.path.join(log_dir, filename)) as fh:
                results = scan_compliance(fh.read())
            db.save_audit(filename, results)
            db.log_ledger("SCAN", _actor(), "compliance-scan:post-remediation",
                          payload={"filename": filename,
                                   "checks": len(results)})
            counts = {"PASS": 0, "FAIL": 0, "WARN": 0}
            for r in results:
                counts[str(r.get("status", "")).upper()] += 1
            total = sum(counts.values())
            return {
                "score": round(100 * counts["PASS"] / total) if total else 100,
                "ts": db.now(),
                "counts": {"pass": counts["PASS"], "fail": counts["FAIL"],
                           "warn": counts["WARN"]},
                "checks": [{"id": r.get("id", ""), "status": r.get("status", "")}
                           for r in results],
            }
        except Exception as e:  # noqa: BLE001 - rescan is best-effort
            print(f"[remediate] post-write rescan failed: {e}")
            return None

    # ---------------- data access ----------------

    def load_provisioning_yaml(self, index=0):
        path = os.path.join(BASE, "config", "branches.yaml")
        try:
            with open(path) as fh:
                data = yaml.safe_load(fh) or {}
        except OSError:
            return {}
        items = data.get("provisioning") or []
        return items[index] if index < len(items) else {}

    # ---------------- ops tools (Cisco-approved RESTCONF ops) ----------------

    def _iface_path(self, iface):
        """'0/0/0' -> GigabitEthernet=0%2F0%2F0 (RESTCONF URL-safe name)."""
        return f"GigabitEthernet={iface.strip().replace('/', '%2F')}"

    def inventory(self):
        """Hardware inventory: part number + serial per field-replaceable unit."""

        def fn():
            _, rc = get_restconf_device(None)
            data = get(
                rc,
                "Cisco-IOS-XE-device-hardware-oper:device-hardware-data/device-hardware",
            )
            root = data.get(
                "Cisco-IOS-XE-device-hardware-oper:device-hardware", {})
            items = []
            for a in root.get("device-inventory") or []:
                if a.get("serial-number"):
                    items.append({
                        "pn": a.get("part-number", ""),
                        "sn": a["serial-number"],
                        "desc": a.get("description", ""),
                    })
            print(f"[RESTCONF] inventory -> {len(items)} field-replaceable units")
            return items

        self._run("INVENTORY", fn)

    def get_hostname(self):
        def fn():
            _, rc = get_restconf_device(None)
            data = get(rc, "Cisco-IOS-XE-native:native/hostname")
            return data.get("Cisco-IOS-XE-native:hostname", "")

        self._run("HOSTNAME", fn)

    def set_hostname(self, name):
        def fn():
            _, rc = get_restconf_device(None)
            put(rc, "Cisco-IOS-XE-native:native/hostname",
                {"Cisco-IOS-XE-native:hostname": name})
            print(f"[RESTCONF] hostname -> {name}")
            db.log_action("HOSTNAME", "OK", f"hostname set to {name}",
                          device=_dev_name())
            return name

        self._run("SET_HOSTNAME", fn)

    def set_interface_ip(self, iface, address, mask):
        def fn():
            _, rc = get_restconf_device(None)
            path = (f"Cisco-IOS-XE-native:native/interface/"
                    f"{self._iface_path(iface)}/ip/address/primary")
            patch(rc, path, {"primary": {"address": address, "mask": mask}})
            print(f"[RESTCONF] {iface} IPv4 -> {address}/{mask}")
            db.log_action("SET_IP", "OK",
                          f"{iface} primary IPv4 {address} {mask}",
                          device=_dev_name())
            return {"iface": iface, "address": address, "mask": mask}

        self._run("SET_IP", fn)

    def set_interface_state(self, iface, up=True):
        """One-click port bring-up / shut-down.

        Bring-up DELETEs the native 'shutdown' presence leaf — the DevNet
        c8k sandbox rejects PATCH-create of the leaf (HTTP 400 '0: Internal
        error'), but DELETE is accepted. A 404 on the DELETE simply means
        the leaf is already gone (interface already up)."""

        def fn():
            m = re.match(r"^([A-Za-z]+)(.+)$", str(iface or ""))
            if not m:
                raise RuntimeError(f"cannot parse interface name: {iface!r}")
            itype, iname = m.group(1), m.group(2).replace("/", "%2F")
            path = (f"Cisco-IOS-XE-native:native/interface/"
                    f"{itype}={iname}/shutdown")
            _, rc = get_restconf_device(None)
            if up:
                try:
                    delete(rc, path)
                except RestconfError as e:
                    if "404" not in str(e):
                        raise
                print(f"[RESTCONF] {iface} -> up (shutdown leaf removed)")
            else:
                patch(rc, path, {"shutdown": [None, True]})
                print(f"[RESTCONF] {iface} -> down (shutdown leaf set)")
            db.log_action("IFACE_STATE", "OK",
                          f"{iface} {'up' if up else 'down'}",
                          device=_dev_name())
            return {"iface": iface, "up": bool(up)}

        self._run("IFACE_STATE", fn)

    def get_interface_config(self):
        """Full interface configuration model (ietf-interfaces)."""

        def fn():
            _, rc = get_restconf_device(None)
            data = get(rc, "ietf-interfaces:interfaces")
            items = []
            for e in (data.get("ietf-interfaces:interfaces", {}).get("interface")
                      or []):
                ip = ""
                addrs = (((e.get("ipv4") or {}).get("address")) or [])
                if addrs:
                    ip = f"{addrs[0].get('address', '')}/{addrs[0].get('netmask', '')}"
                items.append({
                    "name": e.get("name", "?"),
                    "type": ((e.get("type") or "").split("/")[-1]) or "?",
                    "enabled": "up" if e.get("enabled") else "down",
                    "description": e.get("description", ""),
                    "ip": ip,
                })
            print(f"[RESTCONF] interface config -> {len(items)} interfaces")
            return items

        self._run("IFACE_CONFIG", fn)

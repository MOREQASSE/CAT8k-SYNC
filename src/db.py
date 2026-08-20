"""SQLite memory layer: the project's long-term brain.

Everything the engine ever learns is persisted here — snapshots,
per-interface health, raw telemetry pulls, audits, drifts, actions and
events — so the dashboard can show trends without a live RESTCONF pull.

Thread safety: engine tasks run in daemon threads, so every call opens
its own short-lived connection (SQLite is fine with that; no shared
state). Writes are small and infrequent.
"""
import hashlib
import json
import os
import sqlite3
import time

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(BASE, "data", "CAT8k-SYNC.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT DEFAULT '',
    password_hash TEXT DEFAULT '',
    password_salt TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    host TEXT NOT NULL,
    username TEXT NOT NULL,
    password_enc TEXT DEFAULT '',
    secret_enc TEXT DEFAULT '',
    port INTEGER DEFAULT 22,
    https INTEGER DEFAULT 1,
    verify_ssl INTEGER DEFAULT 0,
    restconf_port INTEGER DEFAULT 443,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS snapshot_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    hostname TEXT NOT NULL,
    cpu TEXT DEFAULT '?',
    mem_used INTEGER,
    mem_free INTEGER,
    iface_up INTEGER DEFAULT 0,
    iface_down INTEGER DEFAULT 0,
    arp_count INTEGER DEFAULT 0,
    bgp TEXT DEFAULT '',
    payload TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS iface_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER,
    ts TEXT NOT NULL,
    if_name TEXT NOT NULL,
    admin TEXT DEFAULT '',
    oper TEXT DEFAULT '',
    state TEXT DEFAULT '',
    speed INTEGER DEFAULT 0,
    rx_kbps INTEGER DEFAULT 0,
    tx_kbps INTEGER DEFAULT 0,
    in_octets INTEGER DEFAULT 0,
    out_octets INTEGER DEFAULT 0,
    in_errors INTEGER DEFAULT 0,
    out_errors INTEGER DEFAULT 0,
    crc_errors INTEGER DEFAULT 0,
    flaps INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS telemetry_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    path TEXT DEFAULT '',
    payload TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS audit_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    filename TEXT DEFAULT '',
    pass_count INTEGER DEFAULT 0,
    fail_count INTEGER DEFAULT 0,
    warn_count INTEGER DEFAULT 0,
    results TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS drift_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    status TEXT DEFAULT '',
    diff TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS actions_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    action TEXT NOT NULL,
    device TEXT DEFAULT '',
    status TEXT DEFAULT '',
    message TEXT DEFAULT '',
    payload TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS events_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    level TEXT DEFAULT 'INFO',
    source TEXT DEFAULT '',
    message TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS audit_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    event_type TEXT NOT NULL,
    actor TEXT DEFAULT '',
    action TEXT DEFAULT '',
    payload TEXT DEFAULT '',
    prev_hash TEXT NOT NULL,
    checksum TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS host_registry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL,
    node_type TEXT NOT NULL DEFAULT 'pc',
    vlan_id INTEGER DEFAULT 0,
    ip TEXT NOT NULL,
    mask TEXT DEFAULT '',
    port TEXT DEFAULT '',
    gateway TEXT DEFAULT '',
    subnet TEXT DEFAULT '',
    device TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
"""


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = connect()
    try:
        conn.executescript(_SCHEMA)
        # migrate existing databases created before the node_type column
        cols = [r[1] for r in conn.execute("PRAGMA table_info(host_registry)")]
        if "node_type" not in cols:
            conn.execute(
                "ALTER TABLE host_registry "
                "ADD COLUMN node_type TEXT NOT NULL DEFAULT 'pc'")
        conn.commit()
    finally:
        conn.close()


def now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def wipe_all():
    """Danger: clear every table (keeps schema + settings)."""
    conn = connect()
    try:
        for t in ("users", "devices", "snapshot_history", "iface_history",
                  "telemetry_history", "audit_history", "drift_history",
                  "actions_log", "events_log", "audit_ledger", "host_registry"):
            conn.execute(f"DELETE FROM {t}")
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------- users

def save_user(username, display_name="", password_hash="", password_salt=""):
    conn = connect()
    try:
        ts = now()
        conn.execute(
            """INSERT INTO users (username, display_name, password_hash,
                                  password_salt, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(username) DO UPDATE SET
                   display_name=excluded.display_name,
                   password_hash=excluded.password_hash,
                   password_salt=excluded.password_salt,
                   updated_at=excluded.updated_at""",
            (username, display_name, password_hash, password_salt, ts, ts))
        conn.commit()
    finally:
        conn.close()


def get_user():
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM users ORDER BY id LIMIT 1").fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def has_user():
    return get_user() is not None


def hash_password(password, salt=None):
    """PBKDF2-HMAC-SHA256 (stdlib only). Returns (hash_hex, salt_hex)."""
    salt = salt or os.urandom(16).hex()
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"),
        bytes.fromhex(salt), 200_000).hex()
    return digest, salt


def verify_password(user, password):
    if not user or not user.get("password_hash"):
        return True  # no frontend password set -> free login
    if not password:
        return False
    digest, _ = hash_password(password, user.get("password_salt"))
    return digest == user.get("password_hash")


# ---------------------------------------------------------------- devices

def save_device(rec):
    """rec: dict with plaintext username/password/secret (encrypted here).

    Single-device vault: updates the existing row in place, otherwise inserts.
    """
    from src import vault
    conn = connect()
    try:
        ts = now()
        row = conn.execute(
            "SELECT id FROM devices ORDER BY id LIMIT 1").fetchone()
        values = (
            rec.get("name", "Cat8000"), rec.get("host", ""),
            rec.get("username", ""),
            vault.encrypt(rec.get("password", "")),
            vault.encrypt(rec.get("secret", rec.get("password", ""))),
            int(rec.get("port", 22) or 22),
            1 if rec.get("https", True) else 0,
            1 if rec.get("verify_ssl", False) else 0,
            int(rec.get("restconf_port", 443) or 443),
            ts)
        if row:
            conn.execute(
                """UPDATE devices SET name=?, host=?, username=?,
                   password_enc=?, secret_enc=?, port=?, https=?,
                   verify_ssl=?, restconf_port=?, updated_at=?
                   WHERE id=?""",
                values + (row["id"],))
        else:
            conn.execute(
                """INSERT INTO devices (name, host, username, password_enc,
                    secret_enc, port, https, verify_ssl, restconf_port,
                    updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                values)
        conn.commit()
    finally:
        conn.close()


def get_device():
    """Encrypted row as dict (password_enc/secret_enc), or None."""
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM devices ORDER BY id LIMIT 1").fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_device_plain():
    """Full plaintext device dict for netmiko/restconf (password decrypted)."""
    from src import vault
    row = get_device()
    if not row:
        return None
    row = dict(row)
    row["password"] = vault.decrypt(row.pop("password_enc", ""))
    row["secret"] = vault.decrypt(row.pop("secret_enc", "")) or row["password"]
    return row


# ---------------------------------------------------------------- vpn access

def save_vpn(rec):
    """Sanbox VPN access record (Quick Access links: vpn_address, vpn_username,
    vpn_password, and vpn_device_host = the reservation device's mgmt IP /
    hostname reachable only inside the tunnel; vpn_device_username and
    vpn_device_password = the SSH/RESTCONF/NETCONF login of that device, which
    on DevNet reservations differs from the Quick Access login). Passwords are
    Fernet-encrypted; an empty password keeps the previously sealed value."""
    from src import vault
    password = rec.get("password", "")
    if password:
        password = vault.encrypt(password)
    else:
        password = get_setting("vpn.password", "")
    device_password = rec.get("device_password", "")
    if device_password:
        device_password = vault.encrypt(device_password)
    else:
        device_password = get_setting("vpn.device_password", "")
    set_setting("vpn.address", rec.get("address", ""))
    set_setting("vpn.username", rec.get("username", ""))
    set_setting("vpn.password", password)
    set_setting("vpn.device_host", rec.get("device_host", ""))
    set_setting("vpn.device_username", rec.get("device_username", ""))
    set_setting("vpn.device_password", device_password)
    set_setting("vpn.updated", now())
    return True


def get_vpn_plain():
    """Plaintext VPN access dict, or None when never configured."""
    from src import vault
    address = get_setting("vpn.address", "")
    username = get_setting("vpn.username", "")
    if not address and not username:
        return None
    return {
        "address": address,
        "username": username,
        "password": vault.decrypt(get_setting("vpn.password", "")),
        "device_host": get_setting("vpn.device_host", ""),
        "device_username": get_setting("vpn.device_username", ""),
        "device_password": vault.decrypt(get_setting("vpn.device_password", "")),
        "updated": get_setting("vpn.updated", ""),
    }


# ---------------------------------------------------------------- reservation companions

# Credential sets for the other devices of the Cat8kv reservation (reachable
# only inside the tunnel). Every field is editable in the profile page and
# stored Fernet-sealed; the documented sandbox defaults apply until changed.
RES_COMPANIONS = {
    "devbox": {
        "label": "Developer Box", "desc": "Linux environment",
        "default_host": "10.10.20.50", "default_port": 22,
        "default_username": "developer", "default_password": "C1sco12345",
    },
    "xrv": {
        "label": "IOS XRv 9K", "desc": "XR router",
        "default_host": "10.10.20.35", "default_port": 22,
        "default_username": "developer", "default_password": "C1sco12345",
    },
    "nexus": {
        "label": "Nexus 9K", "desc": "NX-OS switch",
        "default_host": "10.10.20.40", "default_port": 22,
        "default_username": "admin", "default_password": "RG!_Yw200",
    },
}

RES_SLUGS = tuple(RES_COMPANIONS)


def save_res_cred(slug, rec):
    """Editable reservation companion credential set (devbox/xrv/nexus).
    Passwords are Fernet-encrypted; an empty password keeps the sealed one."""
    if slug not in RES_COMPANIONS:
        raise ValueError(f"unknown reservation companion '{slug}'")
    from src import vault
    password = rec.get("password", "")
    if password:
        password = vault.encrypt(password)
    else:
        password = get_setting(f"res.{slug}.password", "")
    set_setting(f"res.{slug}.host", str(rec.get("host") or "").strip())
    set_setting(f"res.{slug}.port", str(int(rec.get("port") or 22)))
    set_setting(f"res.{slug}.username", str(rec.get("username") or "").strip())
    set_setting(f"res.{slug}.password", password)
    set_setting(f"res.{slug}.updated", now())
    return True


def get_res_creds():
    """All reservation companion sets with defaults applied, plaintext
    passwords (the caller masks before exposing to the UI)."""
    from src import vault
    out = {}
    for slug, meta in RES_COMPANIONS.items():
        out[slug] = {
            "slug": slug,
            "label": meta["label"],
            "desc": meta["desc"],
            "host": get_setting(f"res.{slug}.host", "") or meta["default_host"],
            "port": int(get_setting(f"res.{slug}.port", "") or meta["default_port"]),
            "username": get_setting(f"res.{slug}.username", "") or meta["default_username"],
            "password": vault.decrypt(get_setting(f"res.{slug}.password", ""))
                        or meta["default_password"],
            "updated": get_setting(f"res.{slug}.updated", ""),
        }
    return out


# ---------------------------------------------------------------- snapshots

def save_snapshot(snap):
    """snap: dict from automation.device_snapshot(). Returns snapshot id."""
    conn = connect()
    try:
        ts = now()
        mem = snap.get("memory") or (None, None)
        cur = conn.execute(
            """INSERT INTO snapshot_history (ts, hostname, cpu, mem_used,
                mem_free, iface_up, iface_down, arp_count, bgp, payload)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (ts, str(snap.get("hostname", "?")), str(snap.get("cpu", "?")),
             _num(mem[0]) if isinstance(mem, (tuple, list)) else None,
             _num(mem[1]) if isinstance(mem, (tuple, list)) else None,
             int(snap.get("iface_up", 0) or 0),
             int(snap.get("iface_down", 0) or 0),
             len(snap.get("arp_rows") or []),
             ",".join(snap.get("bgp_fams") or []),
             json.dumps(snap, default=str)))
        snap_id = cur.lastrowid
        for i in snap.get("ifaces") or []:
            stats = i.get("statistics") or {}
            conn.execute(
                """INSERT INTO iface_history (snapshot_id, ts, if_name,
                    admin, oper, state, speed, rx_kbps, tx_kbps, in_octets,
                    out_octets, in_errors, out_errors, crc_errors, flaps)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (snap_id, ts, str(i.get("name", "?")),
                 str(i.get("admin-status", "")), str(i.get("oper-status", "")),
                 _state(i), _num(i.get("speed")),
                 _num(stats.get("rx-kbps")), _num(stats.get("tx-kbps")),
                 _num(stats.get("in-octets")), _num(stats.get("out-octets")),
                 _num(stats.get("in-errors")), _num(stats.get("out-errors")),
                 _num(stats.get("in-crc-errors")), _num(stats.get("num-flaps"))))
        conn.commit()
        return snap_id
    finally:
        conn.close()


def _num(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def _state(i):
    oper = str(i.get("oper-status", ""))
    admin = str(i.get("admin-status", ""))
    if "ready" in oper or "up" in oper:
        return "UP"
    if "down" in oper and "up" in admin:
        return "DOWN"
    return "DEGRADED"


def snapshot_timeline(limit=40):
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM snapshot_history ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()]
    finally:
        conn.close()


def iface_history(limit=60, if_name=None):
    conn = connect()
    try:
        if if_name:
            rows = conn.execute(
                "SELECT * FROM iface_history WHERE if_name=? "
                "ORDER BY id DESC LIMIT ?", (if_name, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM iface_history ORDER BY id DESC LIMIT ?",
                (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def iface_names():
    conn = connect()
    try:
        return [r["if_name"] for r in conn.execute(
            "SELECT DISTINCT if_name FROM iface_history ORDER BY if_name")]
    finally:
        conn.close()


# ---------------------------------------------------------------- telemetry

def save_telemetry(kind, path, payload_text):
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO telemetry_history (ts, kind, path, payload) "
            "VALUES (?, ?, ?, ?)",
            (now(), kind, path, payload_text))
        conn.commit()
    finally:
        conn.close()


def telemetry_history(kind=None, limit=50):
    conn = connect()
    try:
        if kind:
            rows = conn.execute(
                "SELECT * FROM telemetry_history WHERE kind=? "
                "ORDER BY id DESC LIMIT ?", (kind, limit)).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM telemetry_history ORDER BY id DESC LIMIT ?",
                (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------- audits / drift

def save_audit(filename, results):
    conn = connect()
    try:
        counts = {"PASS": 0, "FAIL": 0, "WARN": 0}
        for r in results or []:
            counts[str(r.get("status", "")).upper()] = \
                counts.get(str(r.get("status", "")).upper(), 0) + 1
        conn.execute(
            "INSERT INTO audit_history (ts, filename, pass_count, fail_count, "
            "warn_count, results) VALUES (?, ?, ?, ?, ?, ?)",
            (now(), filename or "", counts["PASS"], counts["FAIL"],
             counts["WARN"], json.dumps(results, default=str)))
        conn.commit()
    finally:
        conn.close()


def audit_history(limit=40):
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM audit_history ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()]
    finally:
        conn.close()


def save_drift(status, diff_text):
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO drift_history (ts, status, diff) VALUES (?, ?, ?)",
            (now(), status or "", diff_text or ""))
        conn.commit()
    finally:
        conn.close()


def drift_history(limit=40):
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM drift_history ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()]
    finally:
        conn.close()


# ---------------------------------------------------------------- actions / events

def log_action(action, status, message="", payload="", device=""):
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO actions_log (ts, action, device, status, message, "
            "payload) VALUES (?, ?, ?, ?, ?, ?)",
            (now(), action, device, status, message, payload))
        conn.commit()
    finally:
        conn.close()


def recent_actions(limit=40):
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM actions_log ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()]
    finally:
        conn.close()


def log_event(level, source, message):
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO events_log (ts, level, source, message) "
            "VALUES (?, ?, ?, ?)",
            (now(), level, source, message))
        conn.commit()
    finally:
        conn.close()


def recent_events(limit=40):
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM events_log ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()]
    finally:
        conn.close()


# ---------------------------------------------------------------- audit ledger

def _ledger_genesis():
    """Hash anchor for the chain's first entry (immutable constant)."""
    return hashlib.sha256(b"Company-audit-ledger-v1").hexdigest()


def log_ledger(event_type, actor="", action="", payload=""):
    """Append an immutable ledger entry.

    Chain rule: checksum = sha256(prev_hash + event_type + actor + action
    + payload + ts). Reading rows and recomputing detects any tampering.
    Returns the stored checksum (or None on error)."""
    conn = connect()
    try:
        last = conn.execute(
            "SELECT checksum FROM audit_ledger ORDER BY id DESC LIMIT 1"
        ).fetchone()
        prev_hash = last["checksum"] if last else _ledger_genesis()
        ts = now()
        if not isinstance(payload, str):
            payload = json.dumps(payload, default=str)
        checksum = hashlib.sha256(
            f"{prev_hash}|{event_type}|{actor}|{action}|{payload}|{ts}"
            .encode("utf-8")).hexdigest()
        conn.execute(
            "INSERT INTO audit_ledger (ts, event_type, actor, action, "
            "payload, prev_hash, checksum) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (ts, event_type, actor or "", action or "", payload or "",
             prev_hash, checksum))
        conn.commit()
        return checksum
    finally:
        conn.close()


def ledger_chain(limit=100):
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM audit_ledger ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()]
    finally:
        conn.close()


def verify_ledger():
    """Recompute the whole chain; report first broken link.

    The anchor is the first entry's prev_hash when present (the genesis
    constant may legitimately change between re-seeds); otherwise the
    constant. Returns {ok, total, broken_at, last_hash}."""
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT * FROM audit_ledger ORDER BY id ASC").fetchall()
        prev_hash = (rows[0]["prev_hash"] if rows else _ledger_genesis())
        for i, r in enumerate(rows):
            recomputed = hashlib.sha256(
                f"{prev_hash}|{r['event_type']}|{r['actor']}|{r['action']}"
                f"|{r['payload']}|{r['ts']}".encode("utf-8")).hexdigest()
            if recomputed != r["checksum"] or r["prev_hash"] != prev_hash:
                return {"ok": False, "total": len(rows),
                        "broken_at": i + 1, "last_hash": prev_hash}
            prev_hash = r["checksum"]
        return {"ok": True, "total": len(rows),
                "broken_at": None, "last_hash": prev_hash}
    finally:
        conn.close()


# ---------------------------------------------------------------- settings

def get_setting(key, default=""):
    conn = connect()
    try:
        row = conn.execute("SELECT value FROM settings WHERE key=?",
                           (key,)).fetchone()
        return row["value"] if row else default
    finally:
        conn.close()


def set_setting(key, value):
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)))
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------- host registry

def save_host(rec):
    """Register a host node (add_pc action). Returns the new row id."""
    conn = connect()
    try:
        ts = now()
        cur = conn.execute(
            """INSERT INTO host_registry
               (label, node_type, vlan_id, ip, mask, port, gateway, subnet, device, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (str(rec.get("label") or ""),
             str(rec.get("node_type") or "pc").strip().lower()[:16],
             int(rec.get("vlan_id") or 0),
             str(rec.get("ip") or ""), str(rec.get("mask") or ""),
             str(rec.get("port") or ""), str(rec.get("gateway") or ""),
             str(rec.get("subnet") or ""), str(rec.get("device") or ""), ts))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def list_hosts(limit=100):
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT * FROM host_registry ORDER BY id DESC LIMIT ?",
            (limit,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def host_ip_taken(ip):
    conn = connect()
    try:
        row = conn.execute("SELECT id FROM host_registry WHERE ip=?",
                           (str(ip),)).fetchone()
        return row is not None
    finally:
        conn.close()


# ---------------------------------------------------------------- dashboard series

def series(kind, limit=40):
    """[(ts, value)] trend series for the hub charts."""
    conn = connect()
    try:
        if kind == "cpu":
            rows = conn.execute(
                "SELECT ts, cpu FROM snapshot_history ORDER BY id DESC LIMIT ?",
                (limit,)).fetchall()
            out = [(r["ts"][11:16], r["cpu"]) for r in rows]
        elif kind == "mem":
            rows = conn.execute(
                "SELECT ts, mem_used, mem_free FROM snapshot_history "
                "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            out = [(r["ts"][11:16], _mem_pct(r["mem_used"], r["mem_free"]))
                   for r in rows]
        elif kind == "up":
            rows = conn.execute(
                "SELECT ts, iface_up, iface_down FROM snapshot_history "
                "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
            out = [(r["ts"][11:16], r["iface_up"]) for r in rows]
        elif kind == "errors":
            rows = conn.execute(
                "SELECT MAX(id) AS id, MAX(ts) AS ts, "
                "SUM(in_errors+out_errors+crc_errors+flaps) AS e "
                "FROM iface_history GROUP BY snapshot_id "
                "ORDER BY MAX(id) DESC LIMIT ?", (limit,)).fetchall()
            out = [(r["ts"][11:16], r["e"] or 0) for r in rows]
        else:
            out = []
        return list(reversed(out))
    finally:
        conn.close()


def _mem_pct(used, free):
    try:
        used, free = int(used or 0), int(free or 0)
        total = used + free
        return round(used * 100 / total) if total else 0
    except (TypeError, ValueError):
        return 0


def stats_overview():
    conn = connect()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS snaps, SUM(iface_up) AS ups, "
            "SUM(iface_down) AS downs, MIN(ts) AS first_ts, "
            "MAX(ts) AS last_ts FROM snapshot_history").fetchone()
        audits = conn.execute(
            "SELECT COUNT(*) AS n, SUM(fail_count) AS fails "
            "FROM audit_history").fetchone()
        actions = conn.execute(
            "SELECT COUNT(*) AS n FROM actions_log").fetchone()
        drifts = conn.execute(
            "SELECT COUNT(*) AS n, MAX(ts) AS last FROM drift_history").fetchone()
        baseline = conn.execute(
            "SELECT MAX(ts) AS ts FROM actions_log "
            "WHERE action='BASELINE' AND status='OK'").fetchone()
        login = conn.execute(
            "SELECT MAX(ts) AS ts FROM events_log "
            "WHERE message LIKE '%unlocked%'").fetchone()
        return {
            "snapshots": row["snaps"] or 0,
            "iface_ups": row["ups"] or 0,
            "iface_downs": row["downs"] or 0,
            "first_snapshot": row["first_ts"] or "",
            "last_snapshot": row["last_ts"] or "",
            "audits": audits["n"] or 0,
            "audit_fails": audits["fails"] or 0,
            "actions": actions["n"] or 0,
            "drifts": drifts["n"] or 0,
            "baseline_ts": baseline["ts"] or "",
            "last_login": login["ts"] or "",
        }
    finally:
        conn.close()

"""High-level automations over the verified Catalyst 8000 YANG datastores.

Every function here was validated against the DevNet sandbox:
  interfaces-oper, process-cpu-oper, memory-oper, arp-oper,
  bgp-state-data, native/version, native/interface, native/ip.
Parsing is defensive: the IOS XE 17.x structures shift between releases,
so we walk trees and pick leaves by name instead of hard-coding paths.
"""
import difflib
import json
import os
from datetime import datetime

from src.restconf_client import RestconfError, delete, get, get_restconf_device

SNAPSHOT_ENDPOINTS = {
    "hostname": "Cisco-IOS-XE-native:native/hostname",
    "version": "Cisco-IOS-XE-native:native/version",
    "interfaces": "Cisco-IOS-XE-interfaces-oper:interfaces",
    "cpu": "Cisco-IOS-XE-process-cpu-oper:cpu-usage",
    "memory": "Cisco-IOS-XE-memory-oper:memory-statistics",
    "arp": "Cisco-IOS-XE-arp-oper:arp-data",
    "bgp": "Cisco-IOS-XE-bgp-oper:bgp-state-data",
}


def _find_leaves(obj, names, out):
    """Recursively collect every leaf whose key is in `names`."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            base = k.split(":")[-1]
            if base in names:
                out.append(v)
            _find_leaves(v, names, out)
    elif isinstance(obj, list):
        for item in obj:
            _find_leaves(item, names, out)


def _find_entries(obj, keys):
    """Collect dicts that contain ALL of `keys` (e.g. neighbour rows)."""
    out = []
    if isinstance(obj, dict):
        if all(k in obj for k in keys):
            out.append(obj)
        for v in obj.values():
            out.extend(_find_entries(v, keys))
    elif isinstance(obj, list):
        for item in obj:
            out.extend(_find_entries(item, keys))
    return out


def fetch(rc, path, timeout=25):
    return get(rc, path, timeout=timeout)


def _grab(data):
    return data[list(data.keys())[0]] if isinstance(data, dict) and data else {}


def _first_str(data, key):
    """Leaf may be a plain string ('NONA-LAB') or a wrapper dict."""
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        return data.get(key) or (list(data.values())[0] if data else None)
    return data


# ---------------------------------------------------------------- snapshot

def device_snapshot(rc):
    """One call: hostname, version, cpu%, memory%, interface/arp/bgp counts."""
    hostname = None
    try:
        hostname = _first_str(fetch(rc, SNAPSHOT_ENDPOINTS["hostname"]), "hostname")
    except RestconfError:
        hostname = None

    version = None
    try:
        version = _first_str(fetch(rc, SNAPSHOT_ENDPOINTS["version"]), "version")
    except RestconfError:
        version = None

    cpu = None
    try:
        data = fetch(rc, SNAPSHOT_ENDPOINTS["cpu"])
        vals = []
        _find_leaves(data, {"cpu-utilization"}, vals)
        if vals:
            v = vals[-1]
            cpu = v.get("one-minute") if isinstance(v, dict) else v
    except RestconfError:
        cpu = None

    mem = None
    try:
        data = fetch(rc, SNAPSHOT_ENDPOINTS["memory"])
        rows = _find_entries(data, {"name", "used-memory", "free-memory"})
        for r in rows:
            if str(r.get("name", "")).lower() in ("processor", "physical"):
                used = int(r.get("used-memory", 0))
                free = int(r.get("free-memory", 0))
                mem = (used, free)
                break
        if mem is None and rows:
            used = int(rows[0].get("used-memory", 0))
            free = int(rows[0].get("free-memory", 0))
            mem = (used, free)
    except RestconfError:
        mem = None

    ifaces = []
    try:
        data = fetch(rc, SNAPSHOT_ENDPOINTS["interfaces"])
        ifaces = _find_entries(data, {"name", "admin-status", "oper-status"})
    except RestconfError:
        ifaces = []

    arp_rows = []
    try:
        data = fetch(rc, SNAPSHOT_ENDPOINTS["arp"])
        rows = _find_entries(data, {"address", "hardware", "interface"})
        seen = set()
        for r in rows:
            key = (r.get("address"), r.get("hardware"), r.get("interface"))
            if key not in seen:
                seen.add(key)
                arp_rows.append(r)
    except RestconfError:
        arp_rows = []

    bgp_fams = []
    try:
        data = fetch(rc, SNAPSHOT_ENDPOINTS["bgp"])
        vals = []
        _find_leaves(data, {"afi-safi"}, vals)
        bgp_fams = sorted(set(str(v) for v in vals))
    except RestconfError:
        bgp_fams = []

    def _up(v):
        return "up" in str(v).lower()

    def _ready(v):
        return "ready" in str(v).lower() or "up" in str(v).lower()

    up = sum(1 for i in ifaces if _ready(i.get("oper-status")))
    down = sum(1 for i in ifaces if not _ready(i.get("oper-status")))
    return {
        "hostname": hostname or "?",
        "version": version or "?",
        "cpu": str(cpu) if cpu is not None else "?",
        "memory": mem,
        "ifaces": ifaces,
        "iface_up": up,
        "iface_down": down,
        "arp_rows": arp_rows,
        "bgp_fams": bgp_fams,
    }


def _if_state(i):
    admin = str(i.get("admin-status", "?"))
    oper = str(i.get("oper-status", "?"))
    admin = "up" if "up" in admin else "down"
    oper = "up" if ("ready" in oper or "up" in oper) else "down"
    return admin, oper


def interface_lines(ifaces, limit=14):
    """Compact 'name  state  in-err  out-err  ip' lines for terminal display."""
    lines = []
    for i in ifaces[:limit]:
        name = i.get("name", "?")
        admin, oper = _if_state(i)
        stats = i.get("statistics") or {}
        in_err = stats.get("in-errors") or stats.get("input-errors") or 0
        out_err = stats.get("out-errors") or stats.get("output-errors") or 0
        addr = ""
        try:
            prim = i["ipv4"]["address"][0]["address"]["primary"]["address"]
            addr = prim
        except (KeyError, TypeError, IndexError):
            addr = ""
        state = f"{admin}/{oper}"
        lines.append(f"{name:<22} {state:<9} in-err {str(in_err):>8} "
                     f"out-err {str(out_err):>8}  {addr}")
    if len(ifaces) > limit:
        lines.append(f"... +{len(ifaces) - limit} more interfaces")
    return lines


def render_snapshot(snap):
    host = snap["hostname"]
    ver = snap["version"]
    cpu = snap["cpu"]
    mem = snap["memory"]
    mem_txt = "?"
    if mem:
        used, free = mem
        mem_txt = f"{used + free:>9} bytes (used {used})" if False else \
            f"{100 * used // (used + free)}% (used {used} of {used + free})"
    ifaces = snap["ifaces"]
    arp = snap["arp_rows"]
    bgp = snap["bgp_fams"]

    lines = [
        "=" * 92,
        "  DEVICE SNAPSHOT // CATALYST 8000 CLOUD NODE",
        "=" * 92,
        f"  HOSTNAME   {host:<20} IOS-XE {ver}",
        f"  CPU        {cpu:<8}%            MEMORY {mem_txt}",
        f"  INTERFACES {len(ifaces)} total  (up={snap['iface_up']} down={snap['iface_down']})",
        f"  ARP        {len(arp)} neighbours",
        f"  BGP        {len(bgp)} address families configured",
        "-" * 92,
    ]
    lines += interface_lines(ifaces)
    lines.append("-" * 92)
    for r in arp[:8]:
        lines.append(f"  ARP  {r.get('address','?'):<16} {r.get('hardware','?'):<18} "
                     f"{r.get('interface','?'):<16} {str(r.get('mode','?')).replace('ios-arp-mode-','')}")
    if len(arp) > 8:
        lines.append(f"  ... +{len(arp) - 8} more ARP entries")
    lines.append("-" * 92)
    for fam in bgp:
        lines.append(f"  BGP  afi-safi {fam}")
    if not bgp:
        lines.append("  BGP  no route families")
    lines.append("=" * 92)
    return "\n".join(lines)


# ---------------------------------------------------------------- drift

def fetch_config_text(rc):
    """Flattened running config text (the audit's source format)."""
    data = fetch(rc, "Cisco-IOS-XE-native:native")
    from src.parser import flatten_json
    return "\n".join(flatten_json(data))


def drift_check(rc, baseline_path):
    """Compare live config to baseline. Creates baseline on first run."""
    fresh = fetch_config_text(rc)
    os.makedirs(os.path.dirname(baseline_path), exist_ok=True)
    if not os.path.exists(baseline_path):
        with open(baseline_path, "w") as f:
            f.write(fresh)
        return {"baseline": True, "diff": [], "added": 0, "removed": 0}

    with open(baseline_path) as f:
        old = f.read()
    if old == fresh:
        return {"baseline": False, "diff": [], "added": 0, "removed": 0}

    lines = list(difflib.unified_diff(
        old.splitlines(), fresh.splitlines(),
        fromfile="BASELINE", tofile="LIVE", lineterm=""))
    added = sum(1 for l in lines if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in lines if l.startswith("-") and not l.startswith("---"))
    return {"baseline": False, "diff": lines, "added": added, "removed": removed}


def set_baseline(rc, baseline_path):
    fresh = fetch_config_text(rc)
    os.makedirs(os.path.dirname(baseline_path), exist_ok=True)
    with open(baseline_path, "w") as f:
        f.write(fresh)
    return True


# ---------------------------------------------------------------- cleanup

def delete_subinterface(rc, vlan_id):
    """DELETE GigabitEthernet<phys>.<vlan> (rolls back a deployed branch).

    The RESTCONF list key is the bare name the subinterface was created
    with (e.g. ``1.101`` for ``GigabitEthernet1.101``) — the "GigabitEthernet"
    prefix must NOT be repeated in the key or the device answers 404.
    """
    from src.deployer import get_physical_parent_interface
    parent = get_physical_parent_interface(rc)
    name = f"{parent}.{vlan_id}"
    key = f"Cisco-IOS-XE-native:native/interface/GigabitEthernet={name}"
    delete(rc, key)
    try:
        get(rc, key)
    except RestconfError:
        return name
    raise RestconfError(f"subinterface {name} still present after DELETE — teardown failed")


# ---------------------------------------------------------------- raw dump

def dump_json(rc, path):
    data = fetch(rc, path)
    return json.dumps(data, indent=2)


if __name__ == "__main__":
    _, rc = get_restconf_device(None)
    snap = device_snapshot(rc)
    print(render_snapshot(snap))
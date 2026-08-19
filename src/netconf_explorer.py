"""NETCONF model explorer — YANG module browser over the NETCONF :830 session.

Read-only: module list from the hello capabilities, per-module YANG schema
text, and subtree <get> on any datastore filter. Never writes config.

Transparent RESTCONF fallback: when the NETCONF :830 socket is unreachable
(the common case from restricted networks where only 443 is open) the module
list, namespace lookup and subtree GETs are served from the RESTCONF
yang-library / datastore instead — same creds vault, still read-only.
YANG source text (<get-schema>) is NETCONF-only by transport.

Served by the web Api behind the same creds vault as RESTCONF.
"""

import json
import re
import socket
import xml.etree.ElementTree as ET

from src import db
from ncclient import manager

MODULE_RE = re.compile(r"\?module=([^&]+)&revision=([0-9\-]+)")
SCHEMA_MAX = 200_000  # cap a fetched schema at ~200 KB for the web preview
GET_TIMEOUT = 40
PREFLIGHT_TIMEOUT = 4  # fast socket probe on :830 before trying NETCONF


def _connect():
    from src import device_mode
    dev = device_mode.active_device() or db.get_device_plain()
    if not dev:
        raise ConnectionError("no device in vault — run setup first")
    return manager.connect(
        host=dev["host"], port=830, username=dev["username"],
        password=dev["password"], device_params={"name": "iosxe"},
        allow_agent=False, look_for_keys=False, hostkey_verify=False,
        timeout=25,
    )


def _netconf_reachable():
    """Fast preflight: is :830 actually open before we attempt ncclient (25s)?"""
    from src import device_mode
    dev = device_mode.active_device() or db.get_device_plain()
    if not dev:
        return False
    try:
        with socket.create_connection((dev["host"], 830), timeout=PREFLIGHT_TIMEOUT):
            return True
    except OSError:
        return False


def _restconf_device():
    from src import connector
    from src import restconf_client  # noqa: F401  (import check; unused on purpose)
    dev = connector.load_devices()[0]
    return {
        "host": dev["host"],
        "port": int(dev.get("restconf_port") or 443),
        "username": dev["username"],
        "password": dev["password"],
        "https": bool(dev.get("restconf_https", True)),
        "verify_ssl": bool(dev.get("restconf_verify_ssl", False)),
    }


def _yang_library_modules():
    """[{name, revision, namespace, schema}] from RESTCONF yang-library."""
    from src import restconf_client
    params = _restconf_device()
    data = restconf_client.get(
        params, "ietf-yang-library:modules-state/module", timeout=20)
    entries = data.get("ietf-yang-library:module", []) if isinstance(data, dict) else []
    out = []
    for e in entries:
        if not e or not e.get("name"):
            continue
        out.append({
            "name": e["name"],
            "revision": e.get("revision") or "",
            "namespace": e.get("namespace") or "",
            "schema_url": e.get("schema") or "",
        })
    out.sort(key=lambda m: m["name"].lower())
    return out


def list_modules():
    """{ok, count, modules:[{name, revision}]} — NETCONF hello caps, else RESTCONF."""
    if _netconf_reachable():
        try:
            with _connect() as m:
                caps = list(m.server_capabilities)
            seen = {}
            for c in caps:
                mm = MODULE_RE.search(c)
                if mm:
                    seen.setdefault(mm.group(1), mm.group(2))
            mods = [{"name": n, "revision": r} for n, r in sorted(seen.items())]
            return {"ok": True, "count": len(mods), "modules": mods,
                    "via": "netconf-830"}
        except Exception:  # noqa: BLE001  — socket open but session failed, fall through
            pass
    try:
        lib = _yang_library_modules()
    except Exception as e:  # noqa: BLE001
        raise ConnectionError(
            "NETCONF :830 unreachable and RESTCONF yang-library failed — " +
            str(e)[:160])
    mods = [{"name": m["name"], "revision": m["revision"]} for m in lib]
    return {"ok": True, "count": len(mods), "modules": mods,
            "via": "restconf-yang-library", "note": "via RESTCONF (NETCONF :830 closed)"}


def _schema_via_restconf(module):
    """Fetch YANG source through the yang-library schema URL.

    IOS-XE advertises per-module schema URLs like
    https://10.10.20.148:443/restconf/tailf/modules/<module>/<rev>
    pointing at an internal mgmt IP; rewriting host/port to the reachable
    RESTCONF endpoint returns the real YANG text (content-type application/yang)."""
    from src import restconf_client
    from urllib.parse import urlparse
    lib = _yang_library_modules()
    hit = next((m for m in lib if m["name"] == module), None)
    url = (hit or {}).get("schema_url") or ""
    if not url:
        raise ConnectionError(f"no schema URL in yang-library for {module}")
    parsed = urlparse(url)
    replacement = f"https://{_restconf_device()['host']}:{_restconf_device()['port']}"
    if parsed.query:
        public = f"{replacement}{parsed.path}?{parsed.query}"
    else:
        public = f"{replacement}{parsed.path}"

    import requests
    import urllib3
    urllib3.disable_warnings()
    params = _restconf_device()
    resp = requests.get(public, auth=(params["username"], params["password"]),
                        verify=False, timeout=25)
    if resp.status_code != 200 or not resp.content:
        raise ConnectionError(f"schema URL {public} -> HTTP {resp.status_code}")
    text = resp.text
    truncated = len(text) > SCHEMA_MAX
    return {
        "ok": True,
        "module": module,
        "len": len(text),
        "truncated": truncated,
        "text": text[:SCHEMA_MAX],
        "via": "restconf-yang-library",
        "note": "via RESTCONF yang-library (NETCONF :830 closed)",
    }


def schema_of(module):
    """Fetch a module's YANG text via <get-schema> (read-only).

    NETCONF :830 first; when unreachable, falls back to the yang-library
    schema URL served over RESTCONF (same text, public host rewrite)."""
    if _netconf_reachable():
        try:
            with _connect() as m:
                reply = m.get_schema(module)
                if not reply.ok:
                    raise ConnectionError(reply.error or "schema request failed")
                text = reply.data or ""
            truncated = len(text) > SCHEMA_MAX
            return {
                "ok": True,
                "module": module,
                "len": len(text),
                "truncated": truncated,
                "text": text[:SCHEMA_MAX],
                "via": "netconf-830",
            }
        except Exception:  # noqa: BLE001 — session failure, fall through
            pass
    return _schema_via_restconf(module)


# ---------------- RESTCONF subtree-get translation ----------------

def _filter_to_path(filter_xml, lib):
    """Translate a NETCONF subtree filter XML into a RESTCONF data path.

    <interfaces xmlns='urn:ietf:params:xml:ns:yang:ietf-interfaces'/>
      -> ietf-interfaces:interfaces
    Leaf children with values append as key=value segments (list keys).
    """
    try:
        root = ET.fromstring(filter_xml)
    except ET.ParseError as e:
        raise ValueError("filter is not valid XML — " + str(e)[:120])
    parts = []
    cur = root
    while True:
        tag = cur.tag.split("}")[-1]
        if cur.tag.startswith("{") and "}" in cur.tag:
            ns = cur.tag[1:cur.tag.index("}")]
            mod = next((m["name"] for m in lib if m.get("namespace") == ns), "")
            if mod and not parts:
                parts.append(f"{mod}:{tag}")
            else:
                parts.append(tag)
        else:
            parts.append(tag)
        leaves = [(c.tag.split("}")[-1], (c.text or "").strip())
                  for c in list(cur) if not list(c)]
        if leaves:
            for k, v in leaves:
                if v:
                    parts.append(f"{k}={v}")
        kids = [c for c in list(cur) if list(c)]
        if not kids:
            break
        cur = kids[0]
    return "/".join(parts)


def _json_to_xml(data, name):
    """JSON payload from RESTCONF -> pretty XML string (namespace prefixes stripped)."""
    lines = []
    indent = 0

    def emit(d, n):
        nonlocal indent
        pad = "  " * indent
        if isinstance(d, dict):
            for k, v in d.items():
                tag = k.split("}")[-1]
                if ":" in tag and not tag.startswith("{"):
                    tag = tag.split(":", 1)[-1]
                if isinstance(v, dict):
                    lines.append(f"{pad}<{tag}>")
                    indent += 1
                    emit(v, tag)
                    indent -= 1
                    lines.append(f"{pad}</{tag}>")
                elif isinstance(v, list):
                    for item in v:
                        lines.append(f"{pad}<{tag}>")
                        indent += 1
                        emit(item, tag)
                        indent -= 1
                        lines.append(f"{pad}</{tag}>")
                else:
                    lines.append(f"{pad}<{tag}>{'' if v is None else str(v)}</{tag}>")
        else:
            lines.append(f"{pad}<{n}>{'' if d is None else str(d)}</{n}>")

    emit(data, name)
    return "\n".join(lines)


def subtree_get(filter_xml):
    """<get> with a subtree filter — NETCONF first, RESTCONF datastore fallback."""
    if not filter_xml or not filter_xml.strip():
        raise ValueError("empty filter — supply a subtree element like "
                         "<interfaces xmlns='urn:ietf:params:xml:ns:yang:ietf-interfaces'/>")
    if _netconf_reachable():
        try:
            with _connect() as m:
                reply = m.get(filter=("subtree", filter_xml))
                data = reply.data_xml if reply.ok else (reply.error or "")
            if not reply.ok:
                raise ConnectionError(data or "get failed")
            return {"ok": True, "len": len(data), "xml": data, "via": "netconf-830"}
        except Exception:  # noqa: BLE001 — fall through to RESTCONF
            pass

    from src import restconf_client
    lib = _yang_library_modules()
    path = _filter_to_path(filter_xml, lib)
    params = _restconf_device()
    data = restconf_client.get(params, path, timeout=20)
    xml = _json_to_xml(data, "data")
    return {"ok": True, "len": len(xml), "xml": xml,
            "via": "restconf", "path": path,
            "note": "via RESTCONF (NETCONF :830 closed)"}


def module_namespace(module):
    """Namespace of a module — schema header (NETCONF) or yang-library (RESTCONF)."""
    if _netconf_reachable():
        try:
            text = schema_of(module)
            if text.get("ok"):
                mm = re.search(r'namespace\s+"([^"]+)"', text["text"])
                if mm:
                    return {"ok": True, "module": module,
                            "namespace": mm.group(1), "via": "netconf-830"}
        except Exception:  # noqa: BLE001
            pass
    try:
        lib = _yang_library_modules()
    except Exception as e:  # noqa: BLE001
        raise ConnectionError(str(e)[:200])
    hit = next((m for m in lib if m["name"] == module), None)
    if hit and hit["namespace"]:
        return {"ok": True, "module": module, "namespace": hit["namespace"],
                "via": "restconf-yang-library"}
    return {"ok": False, "module": module, "namespace": "",
            "error": "module not found in yang-library"}
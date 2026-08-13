"""Probe the Catalyst 8000 sandbox: which YANG datastores actually respond."""
import json
import sys

sys.path.insert(0, ".")
from src.restconf_client import get, post, get_restconf_device, RestconfError

PROBES_GET = [
    "Cisco-IOS-XE-native:native/hostname",
    "Cisco-IOS-XE-native:native/version",
    "Cisco-IOS-XE-native:native/interface",
    "Cisco-IOS-XE-interfaces-oper:interfaces",
    "Cisco-IOS-XE-ospf-oper:ospf-oper-data",
    "Cisco-IOS-XE-process-cpu-oper:cpu-usage",
    "Cisco-IOS-XE-memory-oper:memory-statistics",
    "Cisco-IOS-XE-device-hardware-oper:device-hardware",
    "Cisco-IOS-XE-arp-oper:arp-data",
    "Cisco-IOS-XE-routing-oper:routing",
    "Cisco-IOS-XE-cef-oper:cef",
    "ietf-interfaces:interfaces-state",
    "Cisco-IOS-XE-bgp-oper:bgp-state-data",
    "Cisco-IOS-XE-interface-common-oper:globals",
    "Cisco-IOS-XE-isis-oper:isis",
    "Cisco-IOS-XE-ipv6-oper:ipv6",
    "Cisco-IOS-XE-vlan-oper:vlan-states",
    "Cisco-IOS-XE-environment-oper:environment-sensors",
    "Cisco-IOS-XE-native:native/ip",
]

_, rc = get_restconf_device(None)
print(f"== probe {rc['host']} ==\n")
for path in PROBES_GET:
    try:
        data = get(rc, path, timeout=25)
        size = len(json.dumps(data))
        first_key = list(data.keys())[0] if isinstance(data, dict) and data else "?"
        print(f"[OK ] {path}  ({size} bytes, key={first_key})")
    except RestconfError as e:
        code = str(e).split("->")[1].split(":")[0].strip() if "->" in str(e) else "ERR"
        print(f"[{'FAIL' if code != 'HTTP 404' else '404 '}] {path}  {code}")

print("\n== ping RPC probe ==")
try:
    r = post(rc, "Cisco-IOS-XE-ping:ping",
             {"input": {"destination": "192.168.30.1", "repeat-count": 1}},
             timeout=40)
    out = r.get("Cisco-IOS-XE-ping:output", {}) if isinstance(r, dict) else r
    ok = "!" in str(out.get("packet", "")) if isinstance(out, dict) else "?" in str(out)
    print(f"[OK ] ping RPC responded: success-rate={out.get('success-rate') if isinstance(out, dict) else '?'}")
except RestconfError as e:
    print(f"[FAIL] ping RPC: {e}")

print("\n== runtime info ==")
try:
    data = get(rc, "Cisco-IOS-XE-native:native/version", timeout=25)
    print("[OK ] native/version:", json.dumps(data)[:300])
except RestconfError as e:
    print("[FAIL] native/version:", str(e)[:120])
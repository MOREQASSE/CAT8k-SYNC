"""live_test.py — guarded live-fabric check through the webapp Api bridge.
Read-only: snapshot / drift / scan + RESTCONF preview render. NO writes.

Run:  python gui/web/tools/live_test.py
"""
import json
import sys
import threading
from pathlib import Path

BASE = str(Path(__file__).resolve().parents[3])
sys.path.insert(0, BASE)

from src import db                                       # noqa: E402
from gui.webapp import Api                               # noqa: E402

DONE = threading.Event()
RESULTS = {}


def main():
    api = Api()

    def collect(label, text, result):
        RESULTS[label] = {"text": text[:500], "result": result}
        DONE.set()

    api.engine.on_done = collect  # capture instead of pushing to a window
    api.engine.on_start = lambda _l: None

    # 1) RESTCONF preview — renders exact calls, never pushes
    form = {
        "action": "add_branch", "site_name": "QA-PREVIEW", "department_vlan": 155,
        "vlan_name": "qa", "department_subnet": "10.1.155.0/24",
        "gateway": "10.1.155.1", "router_wan_ip": "172.16.2.1",
        "router_trunk_port": "Gi0/0/0",
    }
    print("[1] preview(add_branch) ->", end=" ")
    api.engine.preview(form)
    if not DONE.wait(60):
        print("TIMEOUT"); sys.exit(1)
    ok = "RESTCONF" in RESULTS.get("PREVIEW", {}).get("text", "")
    print("OK" if ok else "FAIL")
    if not ok:
        print(RESULTS.get("PREVIEW"))
        sys.exit(1)
    DONE.clear()

    # 2) snapshot — reads live device state, stores history row
    print("[2] snapshot() ->", end=" ")
    api.engine.snapshot()
    if not DONE.wait(90):
        print("TIMEOUT"); sys.exit(1)
    snaps = db.snapshot_timeline(3)
    print(f"OK rows={len(snaps)} last={snaps[0]['ts'] if snaps else 'none'}")
    DONE.clear()

    # 3) drift check vs baseline
    print("[3] drift() ->", end=" ")
    api.engine.drift()
    if not DONE.wait(90):
        print("TIMEOUT"); sys.exit(1)
    drifts = db.drift_history(3)
    print(f"OK rows={len(drifts)} last_status={drifts[0]['status'] if drifts else 'none'}")
    DONE.clear()

    # 4) compliance scan on latest collected config (no re-collect)
    print("[4] scan(latest) ->", end=" ")
    api.engine.scan(collect_first=False)
    if not DONE.wait(90):
        print("TIMEOUT"); sys.exit(1)
    audits = db.audit_history(3)
    print(f"OK rows={len(audits)} last={audits[0]['filename'] if audits else 'none'}")
    DONE.clear()

    # 5) telemetry refresh (interfaces payload persisted)
    print("[5] telemetry_raw(interfaces) ->", end=" ")
    api.engine.telemetry_raw("Cisco-IOS-XE-interfaces-oper:interfaces")
    if not DONE.wait(90):
        print("TIMEOUT"); sys.exit(1)
    tel = db.telemetry_history("interfaces", limit=1)
    print(f"OK payload={len(tel[0]['payload']) if tel else 0} bytes")

    print("\nLIVE FABRIC TEST: ALL PASS")


if __name__ == "__main__":
    main()

"""LIVE auto-collector test (backend): the webapp's background snapshot
collector must append a real device snapshot every ~30s so the ANALYTICS
window advances over time.

Tests the live endpoints exactly as the browser ticker calls them
(analyticsDeep / stats) — the collector starts on first live API call.

Run:  python gui/web/tools/analytics_live_device_probe.py  (~02:00, needs device)
"""
import sys, time
from pathlib import Path

BASE = str(Path(__file__).resolve().parents[3])
sys.path.insert(0, BASE)

from gui.webapp import Api  # noqa: E402

fails = []
def chk(name, cond, extra=""):
    print(("ok  " if cond else "FAIL") + f"  {name}  {extra}")
    if not cond: fails.append(name)

api = Api()
t0 = time.time()

a0 = api.stats()
n0 = a0["snapshots"]
chk("target", n0 >= 2, f"snapshots={n0} (baseline)")

d0 = api.analyticsDeep(72)
cpu0 = d0["cpu"]["vals"] or []

def grow_ok(d):
    for k in ("cpu", "mem", "up", "errors", "avail", "arp"):
        v = d.get(k) or {}
        if not (isinstance(v.get("vals"), list) and v["vals"]):
            return False, k
    if not (isinstance(d.get("audit", {}).get("score"), list) and d["audit"]["score"]):
        return False, "audit.score"
    if not (isinstance(d.get("thr", {}).get("rx"), list) and d["thr"]["rx"]):
        return False, "thr.rx"
    if not (isinstance(d.get("errs", {}).get("in_errors"), list)):
        return False, "errs.in_errors"
    if len(d.get("hourly") or []) != 24:
        return False, "hourly"
    if not isinstance(d.get("pkt", {}).get("labels"), list):
        return False, "pkt.labels"
    return True, None

ok, why = grow_ok(d0)
chk("contract", ok, why or f"cpu={cpu0}")

deadline = time.time() + 100
n1 = n0
while time.time() < deadline and n1 < n0 + 2:
    time.sleep(10)
    n1 = api.stats()["snapshots"]
chk("collector-grew2", n1 >= n0 + 2, f"{n0} -> {n1} ({time.time()-t0:.0f}s)")

for _ in range(3):
    time.sleep(2)
    d1 = api.analyticsDeep(240)
    cpu1 = d1["cpu"]["vals"] or []
    if len(cpu1) >= len(cpu0) + 1:
        break
chk("window-advances", len(cpu1) > len(cpu0), f"cpu {len(cpu0)} -> {len(cpu1)}  mem={len(d1['mem']['vals'])}  avail={len(d1['avail']['vals'])}  arp={len(d1['arp']['vals'])}")
chk("collector-stats", (api._collect_ok > 0 and api._collect_fail == 0),
    f"ok={api._collect_ok} fail={api._collect_fail}")

a1 = api.stats()
chk("kpi-snaps-basis", a1["snapshots"] >= n0 + 2, f"SNAPSHOTS kpi would read {a1['snapshots']}")
print(f"\nELAPSED {time.time()-t0:.0f}s  last snapshot={a1['last_snapshot']}  cpu={cpu1}")
print("FAILS:", fails if fails else "none")
sys.exit(1 if fails else 0)
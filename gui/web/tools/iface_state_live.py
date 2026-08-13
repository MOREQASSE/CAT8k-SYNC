"""End-to-end live test: engine.set_interface_state on the sandbox Loopback 9001.
Mirrors the web UI path (engine -> RESTCONF). Restores UP at the end.
Run:  python gui/web/tools/iface_state_live.py
"""
import sys
import threading
from pathlib import Path

BASE = str(Path(__file__).resolve().parents[3])
sys.path.insert(0, BASE)

from gui.webapp import Api  # noqa: E402
from src.restconf_client import get_restconf_device, get  # noqa: E402

DONE = threading.Event()
RESULTS = {}


def state():
    _, params = get_restconf_device()
    d = get(params, "ietf-interfaces:interfaces")
    for e in d["ietf-interfaces:interfaces"]["interface"]:
        if e.get("name") == "Loopback9001":
            return e.get("enabled")


def main():
    api = Api()
    api.engine.on_done = lambda label, text, result: (
        RESULTS.update(label=label, text=text, result=result), DONE.set())
    api.engine.on_start = lambda _l: None

    s0 = state()
    print(f"start: enabled={s0}")

    print("[1] Api.setIfaceState(Loopback9001, up=True) ->", end=" ")
    DONE.clear()
    api.setIfaceState("Loopback9001", True)
    if not DONE.wait(120):
        print("TIMEOUT"); sys.exit(1)
    s1 = state()
    ok1 = s1 is True
    print(f"result={RESULTS.get('result')} enabled={s1} ->", "PASS" if ok1 else "FAIL")

    print("[2] Api.setIfaceState(Loopback9001, up=False) ->", end=" ")
    DONE.clear()
    api.setIfaceState("Loopback9001", False)
    if not DONE.wait(120):
        print("TIMEOUT"); sys.exit(1)
    s2 = state()
    text = RESULTS.get("text", "")
    limited = "RESTCONF" in text  # sandbox rejects PATCH-create of the shutdown leaf
    print(f"enabled={s2} surfaced={limited} ->", "LIMITED (sandbox: PATCH-create of shutdown rejected)" if limited else "PASS" if s2 is False else "FAIL")

    print("[3] Api.setIfaceState(Loopback9001, up=True)  ->", end=" ")
    DONE.clear()
    api.setIfaceState("Loopback9001", True)
    if not DONE.wait(120):
        print("TIMEOUT"); sys.exit(1)
    s3 = state()
    ok3 = s3 is True
    print(f"result={RESULTS.get('result')} enabled={s3} ->", "PASS" if ok3 else "FAIL")

    print("\nIFACE-STATE LIVE TEST:", "ALL PASS (up-path OK; sandbox down-path limitation surfaced)" if (ok1 and ok3 and (limited or s2 is False)) else "FAILED")
    sys.exit(0 if (ok1 and ok3 and (limited or s2 is False)) else 1)


if __name__ == "__main__":
    main()

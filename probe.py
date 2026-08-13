"""probe.py — does the pywebview JS<->Python bridge respond in a real window?

Loads gui/web/probe.html, then in on_loaded:
  1. evaluate_js roundtrip (JS <-> Python channel)
  2. pywebview.api.state() resolve test (JS -> Python api bridge)
Prints verdict. Exit: 0 = healthy, 1 = bridge wedged, 2 = timed out.
"""
import os
import sys
import threading
import time

BASE = os.path.dirname(os.path.abspath(__file__))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import webview  # noqa: E402

from gui.webapp import Api, _serve, PORT  # noqa: E402

RESULT = {}


def probe(window):
    time.sleep(1.0)
    try:
        window.evaluate_js("window.__p1 = 'P1';")
        time.sleep(0.3)
        v1 = window.evaluate_js("window.__p1")
        RESULT["evaluate_js"] = v1

        window.evaluate_js(
            "window.__p2 = null;"
            "pywebview.api.state().then(function(s){ window.__p2 = (s && s.version && s.version.build) || 'NO-API'; });"
            "'queued'"
        )
        time.sleep(2.5)
        v2 = window.evaluate_js("window.__p2")
        RESULT["api.state()"] = v2
    except Exception as e:  # noqa: BLE001
        RESULT["exc"] = f"{type(e).__name__}: {e}"

    p1 = RESULT.get("evaluate_js")
    p2 = RESULT.get("api.state()")
    exc = RESULT.get("exc", "")
    if exc:
        print(f"RESULT: WEDGED  ({exc})")
    elif p1 == "P1" and p2 == "0.4.0-web":
        print(f"RESULT: HEALTHY  evaluate_js={p1!r}  api.state()={p2!r}")
    else:
        print(f"RESULT: BROKEN  evaluate_js={p1!r}  api.state()={p2!r}")
    sys.stdout.flush()
    os._exit(0 if RESULT.get("api.state()") == "0.4.0-web" else 1)


def on_loaded(window):
    threading.Thread(target=probe, args=(window,), daemon=True).start()


def watchdog():
    time.sleep(40)
    print(f"RESULT: WEDGED  (watchdog timeout, state={RESULT})")
    sys.stdout.flush()
    os._exit(2)

def main():
    threading.Thread(target=watchdog, daemon=True).start()
    threading.Thread(target=_serve, daemon=True).start()
    api = Api()
    window = webview.create_window(
        "PROBE", f"http://127.0.0.1:{PORT}/probe.html",
        js_api=api, width=700, height=460,
        background_color="#0a0f1a",
    )
    api.set_window(window)
    window.events.loaded += on_loaded
    webview.start(gui="edgechromium")

    p1 = RESULT.get("evaluate_js")
    p2 = RESULT.get("api.state()")
    exc = RESULT.get("exc", "")
    if exc:
        print(f"RESULT: WEDGED  ({exc})")
        os._exit(1)
    if p1 == "P1" and p2 == "0.4.0-web":
        print(f"RESULT: HEALTHY  evaluate_js={p1!r}  api.state()={p2!r}")
        os._exit(0)
    print(f"RESULT: BROKEN  evaluate_js={p1!r}  api.state()={p2!r}")
    os._exit(1)


if __name__ == "__main__":
    main()

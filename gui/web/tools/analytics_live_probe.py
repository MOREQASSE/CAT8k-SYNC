"""Full natural-timing test: do the analytics charts actually change with time?
Runs two full 30s auto-refresh cycles + a span-switch cycle, comparing DOM.
Run:  python gui/web/tools/analytics_live_probe.py  (takes ~02:00)
"""
import sys, threading, time, os
from playwright.sync_api import sync_playwright

ROOT = r"C:\Users\hp\Desktop\Sujets OCP PFA\PFA Reqasse\CAT8k-SYNC"
os.chdir(ROOT)
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "gui")); sys.path.insert(0, os.path.join(ROOT, "gui", "web"))
import webapp

threading.Thread(target=webapp._serve, daemon=True).start()
time.sleep(0.8)
BASE = f"http://127.0.0.1:{webapp.PORT}/index.html"

fails = []
def chk(name, cond, extra=""):
    print(("ok  " if cond else "FAIL") + f"  {name}  {extra}")
    if not cond: fails.append(name)

def snap(pg):
    """Capture everything that should move on a tick."""
    return pg.evaluate("""() => {
      const svg = document.querySelectorAll('.area-svg');
      const dsum = (s) => { let h = 0; for (const ch of s) h = (h * 31 + ch.codePointAt(0)) % 999983; return h; };
      const polys = [...document.querySelectorAll('.area-svg path')].map(p => dsum(p.getAttribute('d') || '') + ':' + p.getAttribute('d').length);
      const bars = [...document.querySelectorAll('.bars-svg rect')].length;
      const heat = [...document.querySelectorAll('.heat-cell')].map(c => c.getAttribute('fill') || '');
      return {
        lastX: (window.__cat8kDebug && window.__cat8kDebug.lastX()) || null,
        ticks: (window.__cat8kDebug && window.__cat8kDebug.ticks()) || 0,
        areas: svg.length,
        polyHash: polys.join('|') || 'none',
        bars, heat,
        kpi: [...document.querySelectorAll('.kpi .v')].map(v => v.textContent),
        note: (document.querySelector('.an-note') || {}).textContent || '',
      };
    }""")

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=r"C:\Users\hp\AppData\Local\ms-playwright\chromium-1217\chrome-win64\chrome.exe")
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    errs = []
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    pg.goto(f"{BASE}?demo=1#analytics", wait_until="networkidle")
    pg.wait_for_selector(".area-svg", timeout=8000)

    t0 = time.time()
    A = snap(pg)
    chk("render", A["areas"] >= 6 and A["polyHash"] != "none", f"areas={A['areas']} ticks={A['ticks']}")
    chk("kpi-7", len(A["kpi"]) == 7, str(A["kpi"]))

    chk("wait T+30 tick1", True)
    pg.wait_for_function("window.__cat8kDebug && window.__cat8kDebug.ticks() >= %d" % (A["ticks"] + 1), timeout=40000)
    B = snap(pg)
    chk("feed-advance", B["lastX"] and B["lastX"] != A["lastX"], f"{A['lastX']} -> {B['lastX']}")
    chk("graph-shape-changed", A["polyHash"] != B["polyHash"], f"poly-{len(A['polyHash'])} -> {len(B['polyHash'])}")
    chk("ticks-grew", B["ticks"] > A["ticks"], f"{A['ticks']} -> {B['ticks']}")
    chk("note-moved", B["note"] != A["note"], repr(A["note"][:60]) + " -> " + repr(B["note"][:60]))
    chk("kpi-snaps-grew", B["kpi"][5] != A["kpi"][5], f"{A['kpi'][5]} -> {B['kpi'][5]}")
    chk("charts-rebuilt", B["areas"] == A["areas"], f"stable {B['areas']}")

    pg.wait_for_function("window.__cat8kDebug && window.__cat8kDebug.ticks() >= %d" % (A["ticks"] + 2), timeout=40000)
    C = snap(pg)
    chk("tick2-advance", C["lastX"] != B["lastX"], f"{B['lastX']} -> {C['lastX']}")
    chk("tick2-stable-areas", C["areas"] == A["areas"], str(C["areas"]))
    chk("heat-24", len(C["heat"]) == 24, str(len(C["heat"])))

    pg.click(".seg-btn:has-text('1D')")
    pg.wait_for_timeout(1500)
    D = snap(pg)
    chk("span-1d-applied", "24 collections" in D["note"], repr(D["note"][:60]))
    pg.wait_for_function("window.__cat8kDebug && window.__cat8kDebug.ticks() >= %d" % (C["ticks"] + 1), timeout=40000)
    E = snap(pg)
    chk("span-1d-tick", D["lastX"] and E["lastX"] != D["lastX"], f"{D['lastX']} -> {E['lastX']}")

    pg.screenshot(path=os.path.join(ROOT, "screenshots", "analytics-live-t3.png"), full_page=True)
    chk("console-errors-0", len(errs) == 0, f"n={len(errs)}")
    print(f"\nELAPSED {time.time() - t0:.0f}s — natural ticks observed: {A['ticks']} -> {C['ticks']}")
    b.close()

print("FAILS:", fails if fails else "none")
sys.exit(1 if fails else 0)
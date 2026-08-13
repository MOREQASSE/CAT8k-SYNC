"""Tick-label overlap test for the analytics charts.

Loads each sample window (ALL/1W/1D), then measures every visible x-tick
label: pairwise overlap between ticks, half-clips at the plot edges, and
legend rows. Any overlap => FAIL.

Run:  python gui/web/tools/chart_labels_probe.py
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

def measure(pg):
    return pg.evaluate("""() => {
      const out = { rows: 0, ticks: 0, overlaps: 0, clipped: 0, hidden: 0, legends: 0, legendOverlap: 0 };
      document.querySelectorAll('.tx-xtick').forEach(row => {
        out.rows++;
        const spans = [...row.querySelectorAll('span')];
        const vis = spans.filter(s => s.style.visibility !== 'hidden');
        out.hidden += spans.length - vis.length;
        const plot = row.getBoundingClientRect();
        const rects = vis.map(s => s.getBoundingClientRect()).sort((a, b) => a.left - b.left);
        out.ticks += rects.length;
        for (let i = 1; i < rects.length; i++) if (rects[i].left < rects[i-1].right - 1) out.overlaps++;
        for (const r of rects) {
          if (r.left < plot.left - 1 || r.right > plot.right + 1) out.clipped++;
        }
      });
      document.querySelectorAll('.ch-legend').forEach(leg => {
        const keys = [...leg.querySelectorAll('.ch-key')].map(k => k.getBoundingClientRect());
        for (let i = 1; i < keys.length; i++) {
          const a = keys[i-1], b = keys[i];
          if (!(b.left >= a.right || a.left >= b.right || b.top >= a.bottom || a.top >= b.bottom)) {
            out.legendOverlap++;
          }
        }
        out.legends++;
      });
      return out;
    }""")

with sync_playwright() as p:
    b = p.chromium.launch(executable_path=r"C:\Users\hp\AppData\Local\ms-playwright\chromium-1217\chrome-win64\chrome.exe")
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    errs = []
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    pg.goto(f"{BASE}?demo=1#analytics", wait_until="networkidle")
    pg.wait_for_selector(".area-svg", timeout=8000)
    pg.wait_for_timeout(500)

    for span, n_expected in (("ALL", 400), ("1W", 72), ("1D", 24)):
        pg.click(f".seg-btn:has-text('{span}')")
        pg.wait_for_timeout(2600)
        m = measure(pg)
        chk(f"{span}-ticks", m["ticks"] >= 4, f"visible={m['ticks']} hidden={m['hidden']}")
        chk(f"{span}-no-overlap", m["overlaps"] == 0, f"overlaps={m['overlaps']}")
        chk(f"{span}-no-clip", m["clipped"] == 0, f"clipped={m['clipped']}")
        chk(f"{span}-legend", m["legendOverlap"] == 0, f"keys={m['legends']} overlap={m['legendOverlap']}")
        print(f"    rows={m['rows']} rows-with-ticks={m['ticks']} hidden={m['hidden']}")

    pg.screenshot(path=os.path.join(ROOT, "screenshots", "charts-labels-1D.png"), full_page=True)
    chk("console-errors-0", len(errs) == 0, f"n={len(errs)}")
    b.close()

print("FAILS:", fails if fails else "none")
sys.exit(1 if fails else 0)
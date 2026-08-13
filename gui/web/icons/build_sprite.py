"""One-time build: merge Lucide sprite + the project's custom network SVGs
into a single offline sprite used by the web UI.

Usage:  python gui/web/icons/build_sprite.py
Output: gui/web/icons/sprite.svg  (git-committed asset)
"""
import os
import re
import sys
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))
ICONS_DIR = os.path.join(BASE, "gui", "icons")
OUT = os.path.join(BASE, "gui", "web", "icons", "sprite.svg")
LUCIDE_URL = "https://cdn.jsdelivr.net/npm/lucide-static@latest/sprite.svg"

os.makedirs(os.path.dirname(OUT), exist_ok=True)

print("downloading lucide sprite ...")
try:
    with urllib.request.urlopen(LUCIDE_URL, timeout=60) as r:
        lucide = r.read().decode("utf-8")
    print(f"  lucide sprite: {len(lucide) // 1024} KB")
except Exception as e:  # noqa: BLE001 - network fallback
    print("  download failed:", e)
    sys.exit(1)

symbols = []
for m in re.finditer(
        r"<symbol\s+([^>]*)id=\"([^\"]+)\"(.*?)</symbol>", lucide, re.S):
    attrs, sym_id, inner = m.group(1), m.group(2), m.group(3)
    vb = re.search(r'viewBox="([^"]+)"', attrs) or re.search(
        r'viewBox="([^"]+)"', m.group(0))
    vb = vb.group(1) if vb else "0 0 24 24"
    symbols.append((sym_id, vb, inner))
print(f"  lucide symbols: {len(symbols)}")

for fname in sorted(os.listdir(ICONS_DIR)):
    if not fname.endswith(".svg"):
        continue
    with open(os.path.join(ICONS_DIR, fname), encoding="utf-8") as fh:
        svg = fh.read()
    m = re.search(r"<svg[^>]*>(.*)</svg>", svg, re.S)
    if not m:
        print("  SKIP (no svg body):", fname)
        continue
    sym_id = "Company-" + fname[:-4]
    symbols.append((sym_id, "0 0 24 24", m.group(1)))
print(f"  custom symbols merged: total {len(symbols)}")

def normalize(inner):
    inner = re.sub(r'<path([^>]*?)\bstroke="[^"]*"', r"<path\1", inner)
    inner = re.sub(r'<path([^>]*?)\bfill="[^"]*"', r"<path\1", inner)
    inner = re.sub(r"\s*/>", "/>", inner)
    return inner

parts = ['<svg xmlns="http://www.w3.org/2000/svg" style="display:none">']
for sym_id, vb, inner in symbols:
    parts.append(
        f'<symbol id="{sym_id}" viewBox="{vb}">'
        f'{normalize(inner)}'
        f"</symbol>")
parts.append("</svg>")

with open(OUT, "w", encoding="utf-8") as fh:
    fh.write("\n".join(parts))
print("wrote", OUT, f"({len(parts) // 1024} KB)")

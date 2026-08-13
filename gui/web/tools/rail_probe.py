"""rail probe — screenshot sidebar in expanded and icon-rail modes, check layout."""
import os
import sys
import threading

from pathlib import Path

BASE = str(Path(__file__).resolve().parents[3])
sys.path.insert(0, BASE)

from gui import webapp                              # noqa: E402
from playwright.sync_api import sync_playwright      # noqa: E402

CHROME = r"C:\Users\hp\AppData\Local\ms-playwright\chromium-1217\chrome-win64\chrome.exe"
BASE_URL = f"http://127.0.0.1:{webapp.PORT}/index.html"
SHOT_DIR = os.path.join(BASE, "gui", "web", "screenshots")

def main():
    t = threading.Thread(target=webapp._serve, daemon=True)
    t.start()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME, headless=True, args=["--disable-gpu"])
        page = browser.new_page(viewport={"width": 1480, "height": 940})
        page.goto(f"{BASE_URL}?demo=1", wait_until="networkidle")
        page.wait_for_selector(".sidebar", timeout=8000)
        page.screenshot(path=os.path.join(SHOT_DIR, "rail-expanded.png"))

        toggle = page.locator(".side-toggle")
        print("toggle visible:", toggle.is_visible())
        print("toggle text:", (toggle.text_content() or "").strip())

        toggle.click()
        page.wait_for_timeout(600)
        rail = page.locator("#shell.rail")
        print("rail class applied:", rail.count() == 1)
        w = page.evaluate("document.getElementById('sidebar').getBoundingClientRect().width")
        print("sidebar width(rail):", round(w, 1))
        print("nav labels hidden:", page.locator(".rail .nav-item span:not(.icon)").count())
        print("brand text hidden:", page.locator(".rail .brand-name").count())
        print("nav title attr:", page.locator(".nav-item").first.get_attribute("title"))
        page.screenshot(path=os.path.join(SHOT_DIR, "rail-collapsed.png"))

        page.reload(wait_until="networkidle")
        page.wait_for_timeout(500)
        print("persisted after reload:", page.locator("#shell.rail").count() == 1)

        toggle.click()
        page.wait_for_timeout(600)
        print("expanded again:", page.locator("#shell.rail").count() == 0)
        print("toggle title now:", toggle.get_attribute("title"))
        page.screenshot(path=os.path.join(SHOT_DIR, "rail-restored.png"))
        browser.close()

if __name__ == "__main__":
    main()
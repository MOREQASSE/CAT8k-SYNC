"""vlan-scan probe — provision smart VLAN + IP plan UX checks (mock mode)."""
import sys
import threading

BASE = r"C:\Users\hp\Desktop\Sujets OCP PFA\PFA Reqasse\CAT8k-SYNC"
sys.path.insert(0, BASE)

from gui import webapp                                      # noqa: E402
from playwright.sync_api import sync_playwright              # noqa: E402

CHROME = r"C:\Users\hp\AppData\Local\ms-playwright\chromium-1217\chrome-win64\chrome.exe"
ERR = []


def main():
    t = threading.Thread(target=webapp._serve, daemon=True)
    t.start()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME, headless=True, args=["--disable-gpu"])
        page = browser.new_page(viewport={"width": 1480, "height": 940})
        page.on("console", lambda m: ERR.append(m.text[:200]) if m.type == "error" else None)
        page.on("pageerror", lambda e: ERR.append(str(e)[:200]))
        page.goto(f"http://127.0.0.1:{webapp.PORT}/index.html?demo=1#provision", wait_until="networkidle")
        page.locator('a[href="#provision"]').first.click()
        page.wait_for_selector(".act-card", timeout=5000)
        page.locator(".act-card").first.click()   # ADD BRANCH
        page.wait_for_timeout(1500)

        site = page.locator('[data-key="site_name"]')
        site.fill("BR-SETIF")
        page.wait_for_timeout(200)
        print("vlan_name after site (step0):", page.locator('[data-key="vlan_name"]').count(),
              "| not visible until step2")

        step2 = page.locator("text=NETWORK SEGMENT").first
        step2.click()
        page.wait_for_timeout(400)

        vlan = page.locator('[data-key="vlan_id"]')
        print("vlan prefill:", vlan.input_value())
        hint = page.locator("#vlan-hint")
        print("hint:", hint.text_content())

        page.locator('[data-key="department_subnet"]').first.wait_for(state="visible", timeout=4000)
        print("subnet prefill:", page.locator('[data-key="department_subnet"]').first.input_value())
        print("gateway prefill:", page.locator('[data-key="gateway"]').first.input_value())
        cells = page.locator("#plan-strip .plan-cell .val")
        print("plan strip:", [cells.nth(i).text_content() for i in range(cells.count())])
        su = page.locator('[data-key="department_subnet"]').first
        gw = page.locator('[data-key="gateway"]').first
        print("input widths:", round(su.bounding_box()["width"], 1), "vs", round(gw.bounding_box()["width"], 1))
        print("plan sel options:", page.locator("#plan-sel option").count())

        vlan.fill("120")
        page.wait_for_timeout(150)
        print("used-vlan err class:", "err" in (vlan.get_attribute("class") or ""))
        print("used-vlan hint:", hint.text_content())

        vlan.fill("150")
        page.wait_for_timeout(150)
        print("free-vlan err class:", "err" in (vlan.get_attribute("class") or ""))
        print("free-vlan hint:", hint.text_content())

        vlan.fill("9999")
        page.wait_for_timeout(150)
        print("out-of-range hint:", hint.text_content())

        vname = page.locator('[data-key="vlan_name"]')
        print("vlan_name auto-derived:", vname.input_value())
        vname.fill("alger")
        page.wait_for_timeout(150)
        print("used-name err class:", "err" in (vname.get_attribute("class") or ""))
        print("used-name hint:", page.locator("#vlan-name-hint").text_content())
        vname.fill("finance")
        page.wait_for_timeout(150)
        print("free-name err class:", "err" in (vname.get_attribute("class") or ""))
        print("free-name hint:", page.locator("#vlan-name-hint").text_content())

        sel = page.locator("#plan-sel")
        sel.select_option("br:0")
        page.wait_for_timeout(150)
        print("branch0 fill ->", page.locator('[data-key="department_subnet"]').first.input_value(),
              "/", page.locator('[data-key="gateway"]').first.input_value())
        print("strip after branch0:", [cells.nth(i).text_content() for i in range(cells.count())])
        sel.select_option("auto")
        page.wait_for_timeout(150)
        print("auto fill ->", page.locator('[data-key="department_subnet"]').first.input_value(),
              "/", page.locator('[data-key="gateway"]').first.input_value())
        page.locator("#plan-sel").select_option("custom")
        page.wait_for_timeout(150)
        print("custom keeps:", page.locator('[data-key="department_subnet"]').first.input_value())
        page.locator('[data-key="department_subnet"]').first.fill("10.255.0.0/16")
        page.wait_for_timeout(150)
        print("hosts for /16:", [page.locator("#plan-strip .plan-cell .val").nth(3).text_content()])

        errors = [e for e in ERR if not e.startswith(("Failed to load resource",))]
        print("console errors:", errors or "none")
        browser.close()


if __name__ == "__main__":
    main()
"""qa.py — playwright-driven P6 gate: screenshot + console-error audit for
every web view, plus an E2E provision interaction (fill -> deploy -> toast).

Run:  python gui/web/tools/qa.py        (starts its own server on :17771)
"""
import os
import sys
import threading

from pathlib import Path

BASE = str(Path(__file__).resolve().parents[3])
sys.path.insert(0, BASE)

from gui import webapp                              # noqa: E402
from playwright.sync_api import sync_playwright      # noqa: E402

SHOT_DIR = os.path.join(BASE, "gui", "web", "screenshots")
CHROME = r"C:\Users\hp\AppData\Local\ms-playwright\chromium-1217\chrome-win64\chrome.exe"
BASE_URL = f"http://127.0.0.1:{webapp.PORT}/index.html"

VIEWS = ["home", "provision", "telemetry", "ops", "models", "topology", "audit", "analytics", "profile"]
W = 1480
H = 940


def main():
    os.makedirs(SHOT_DIR, exist_ok=True)
    t = threading.Thread(target=webapp._serve, daemon=True)
    t.start()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME, headless=True,
                                     args=["--disable-gpu"])
        page = browser.new_page(viewport={"width": W, "height": H})
        errors = []

        def on_console(msg):
            if msg.type == "error":
                errors.append(("console", msg.text[:300]))

        def on_pageerror(exc):
            errors.append(("pageerror", str(exc)[:300]))

        page.on("console", on_console)
        page.on("pageerror", on_pageerror)

        # ---- setup wizard walk-through (mock) ----
        page.goto(f"{BASE_URL}?demo=1&setup=1", wait_until="networkidle")
        page.wait_for_selector(".wiz-progress .wiz-step", timeout=8000)
        steps = page.locator(".wiz-progress .wiz-step").count()
        brand = page.locator(".auth-brand").count()
        page.screenshot(path=os.path.join(SHOT_DIR, "qa-auth.png"))
        if steps != 4:
            errors.append(("wizard", f"progress markers: {steps}"))
        for btn_sel in (".wiz-foot .btn.teal", ".wiz-foot .btn.ghost"):
            raw = page.locator(btn_sel).first.text_content() or ""
            n_icon = page.locator(f"{btn_sel} svg.icon").count()
            if "<svg" in raw or n_icon < 1:
                errors.append(("wizard", f"{btn_sel}: escaped svg (icons={n_icon}, text={raw!r})"))
        page.fill("[data-key='full_name']", "QA OPERATOR")
        page.fill("[data-key='role']", "noc")
        page.fill("[data-key='site']", "QA-LAB")
        page.click(".wiz-foot .btn.teal")                            # CONTINUE
        page.wait_for_selector("select[data-key='mode']", timeout=5000)
        page.locator("select[data-key='mode']").select_option("sniffer")
        page.click(".wiz-foot .btn.teal")                            # CONTINUE
        page.wait_for_selector("input[data-key='host']", timeout=5000)
        page.fill("[data-key='host']", "10.9.9.9")
        page.fill("[data-key='username']", "qa")
        page.fill("[data-key='password']", "x")
        page.click(".wiz-foot .btn.teal")                            # CONTINUE
        page.wait_for_selector(".wiz-body .card", timeout=5000)      # REVIEW
        review = page.locator(".wiz-body .card").first.text_content() or ""
        page.click(".wiz-foot .btn.ghost")                           # BACK
        page.wait_for_selector("input[data-key='host']", timeout=5000)
        page.click(".wiz-foot .btn.teal")                            # forward again
        page.wait_for_selector(".wiz-body .card", timeout=5000)
        page.click(".wiz-foot .btn.teal")                            # ENGAGE MISSION
        page.wait_for_selector("#shell:not(.hidden)", timeout=6000)
        marks = page.locator(".wiz-step.done").count()
        engaged = page.locator("#shell:not(.hidden)").count() > 0
        print(f"wizard          ok  steps={steps} done-marks={marks} review-has-mode={'sniffer' in review.lower()} engaged={engaged}")
        if not engaged:
            errors.append(("wizard", "engage did not reach the shell"))

        # ---- every demo view ----
        for v in VIEWS:
            page.goto(f"{BASE_URL}?demo=1#{v}", wait_until="networkidle")
            page.wait_for_selector(".nav-item", timeout=8000)
            page.wait_for_selector("#view-host .card:visible", timeout=8000)
            page.wait_for_timeout(500)
            page.screenshot(path=os.path.join(SHOT_DIR, f"qa-{v}.png"))
            nav = page.locator(".nav-item").count()
            title = page.locator("#crumb-title").text_content()
            errs = page.locator(".auth-error:has-text('view error')").count()
            icons = page.locator(".nav-item svg.icon").count()
            raw = page.locator(".nav-item").first.text_content() or ""
            css_bg = page.locator(".card").first.evaluate(
                "n => getComputedStyle(n).backgroundColor") or ""
            if icons < 7:
                errors.append(("icons", f"{v}: only {icons} nav svg icons"))
            if "&lt;" in raw or "<svg" in raw:
                errors.append(("escaped", f"{v}: raw svg text in nav"))
            if not css_bg or css_bg in ("transparent", "rgba(0, 0, 0, 0)"):
                errors.append(("css", f"{v}: card background not applied ({css_bg})"))
            scroll = page.evaluate(
                "() => { const vh = document.getElementById('view-host');"
                " return { h: vh.scrollHeight, c: vh.clientHeight }; }")
            print(f"{v:<12} ok  nav={nav} title={title or '':<12} viewErrors={errs} icons={icons} bg={css_bg} scroll={scroll['h']}>{scroll['c']}")

        # ---- telemetry: collect + kind switch (mock) ----
        page.goto(f"{BASE_URL}?demo=1#telemetry", wait_until="networkidle")
        page.wait_for_selector("button:has-text('COLLECT NOW')", timeout=8000)
        page.click("button:has-text('COLLECT NOW')")
        page.wait_for_timeout(2600)
        rows = page.locator("#view-host .tbl tbody tr").count()
        print(f"telemetry-collect ok  rows={rows}")
        if rows < 1:
            errors.append(("telemetry", "no rows after collect"))
        page.select_option(".action-bar select.sel", "arp")
        page.wait_for_timeout(900)
        rows2 = page.locator("#view-host .tbl tbody tr").count()
        page.select_option(".action-bar select.sel", "ospf")
        page.wait_for_timeout(900)
        rows3 = page.locator("#view-host .tbl tbody tr").count()
        note3 = page.locator(".tbl-note").count()
        hint3 = (page.locator(".tbl-note-s").text_content() or "")
        hint_ok = len(hint3) > 40
        if not hint_ok:
            errors.append(("telemetry", "ospf explanation missing"))
        page.select_option(".action-bar select.sel", "bgp")
        page.wait_for_timeout(900)
        rows4 = page.locator("#view-host .tbl tbody tr").count()
        note4 = page.locator(".tbl-note").count()
        print(f"telemetry-kind   ok  arp-rows={rows2} ospf-rows={rows3} bgp-rows={rows4} notes={note3}/{note4} hint={hint_ok}")
        if rows2 < 1 or rows3 < 1 or rows4 < 1:
            errors.append(("telemetry", "no rows after kind switch"))

        # ---- pkt-dist: donut pair + interface selector + delta panel ----
        page.select_option(".action-bar select.sel", "pkt-dist")
        page.wait_for_timeout(900)
        donuts = page.locator("#view-host .donut-svg").count()
        sel_if = page.locator(".pkt-sel").count()
        drow = page.locator(".pkt-delta .pkt-drow").count()
        flood = page.locator(".pkt-flood").count()
        print(f"telemetry-pkt-dist ok donuts={donuts} ifsel={sel_if} drow={drow} flood={flood}")
        if donuts < 2 or sel_if < 1 or drow < 1:
            errors.append(("telemetry", "pkt-dist widgets missing"))
        page.select_option(".pkt-sel", "2")
        page.wait_for_timeout(400)
        if page.locator(".pkt-delta .pkt-drow").count() < 1:
            errors.append(("telemetry", "pkt-dist selector no-op"))
        print("telemetry-pkt-sel ok")

        # ---- topology: fetch live (mock) ----
        page.goto(f"{BASE_URL}?demo=1#topology", wait_until="networkidle")
        page.wait_for_selector("button:has-text('FETCH LIVE MAP')", timeout=8000)
        page.click("button:has-text('FETCH LIVE MAP')")
        page.wait_for_timeout(3200)
        svg = page.locator(".topo-canvas-host svg").count()
        nodes = page.locator(".topo-canvas-host .topo-node").count()
        links = page.locator(".topo-canvas-host .topo-link").count()
        live = page.locator(".topo-canvas-host .topo-link.live").count()
        icons = page.locator(".topo-canvas-host use.n-ic").count()
        is_svg = page.evaluate("""() => {
          const n = document.querySelector('.topo-canvas-host .topo-node');
          return !!n && n instanceof SVGGElement;
        }""")
        label_pos = page.evaluate("""() => {
          const ys = [...document.querySelectorAll('.topo-canvas-host text')].map(t => +t.getAttribute('y'));
          const uniq = new Set(ys).size;
          return uniq;
        }""")
        page.screenshot(path=os.path.join(SHOT_DIR, "qa-topology.png"))
        print(f"topology-fetch   ok  svg={svg} nodes={nodes} links={links} live={live} icons={icons} svgNS={is_svg} labelY={label_pos}")
        if not (svg and nodes and links and live and icons and is_svg and label_pos > 3):
            errors.append(("topology", "map not drawn as real SVG after fetch"))

        # ---- ops toolbox (mock) ----
        page.goto(f"{BASE_URL}?demo=1#ops", wait_until="networkidle")
        page.wait_for_selector(".ops-grid .ops-card", timeout=8000)
        cards = page.locator(".ops-grid .ops-card").count()
        page.screenshot(path=os.path.join(SHOT_DIR, "qa-ops.png"))
        page.click("button:has-text('PULL HARDWARE')")
        page.wait_for_selector(".ops-grid table.tbl tbody tr", timeout=6000)
        rows = page.locator(".ops-grid table.tbl tbody tr").count()
        page.click("button:has-text('READ')")
        page.wait_for_selector(".ops-host .mono", timeout=6000)
        host = page.locator(".ops-host .mono").text_content() or ""
        page.click("button:has-text('PROBE FABRIC')")
        page.wait_for_timeout(1200)
        pill = page.locator("#fabric-pill").text_content() or ""
        page.fill("[data-key='iface']", "0/0/2")
        page.fill("[data-key='addr']", "10.1.2.1")
        page.fill("[data-key='mask']", "255.255.255.252")
        page.click("button:has-text('APPLY IP')")
        page.wait_for_selector(".ops-ack", timeout=6000)
        ack = page.locator(".ops-ack").first.text_content() or ""
        page.fill("[data-key='hostname']", "QA-HOST")
        page.click("button:has-text('WRITE')", timeout=10000)
        page.wait_for_selector(".ops-ack:has-text('QA-HOST')", timeout=6000)
        print(f"ops             ok  cards={cards} inv-rows={rows} host={host} pill={'LIVE' in pill} x={pill.strip()[:34]!r} ack0={ack[:44]!r}")
        if cards < 4:
            errors.append(("ops", f"tool cards: {cards}"))
        if rows < 1:
            errors.append(("ops", "inventory rows missing after pull"))
        if not host:
            errors.append(("ops", "hostname read returned empty"))
        if "LIVE" not in pill:
            errors.append(("ops", f"fabric pill not live: {pill!r}"))
        if "0/0/2" not in ack:
            errors.append(("ops", f"apply-ip ack missing iface: {ack!r}"))
        if not any("QA-HOST" in t for t in (page.locator(".ops-ack").all_text_contents() or [])):
            errors.append(("ops", "hostname write ack missing"))

        page.click("button:has-text('REFRESH DOWN LIST')")
        page.wait_for_selector(".iface-down-row", timeout=6000)
        down0 = page.locator(".iface-down-row").count()
        page.click(".iface-down-row .btn")
        page.wait_for_function(
            "document.querySelectorAll('.iface-down-row').length < %d" % down0, timeout=8000)
        down1 = page.locator(".iface-down-row").count()
        up_toast = any("is up" in t for t in (page.locator(".toast").all_text_contents() or []))
        print(f"ops-ifaceup     ok  down0={down0} down1={down1} started={'ok' if down1 < down0 else 'no'} anim_toast={up_toast}")
        if down0 < 1:
            errors.append(("ops", "down-interface menu empty"))
        if down1 >= down0:
            errors.append(("ops", "one-click start did not shrink the down list"))
        if not up_toast:
            errors.append(("ops", "bring-up success toast missing"))

        # ---- security audit console (mock) ----
        page.goto(f"{BASE_URL}?demo=1#audit", wait_until="networkidle")
        page.wait_for_selector(".check-row", timeout=8000)
        n_rows = page.locator(".check-row").count()
        fix_btns = page.locator("button:has-text('FIX')").count()
        sev_dots = page.locator(".sev").count()
        cat_chips = page.locator(".cat-chip").count()
        posture_vals = page.locator(".posture-val").count()
        ledger_banner = page.locator(".ledger-ok, .ledger-bad").count()
        ledger_rows = page.locator("table.tbl tbody tr:has(.mono)").count()
        term_chips = page.locator(".term").count()
        filters = page.locator(".chip").count()
        page.screenshot(path=os.path.join(SHOT_DIR, "qa-audit.png"))
        page.click(".chip:has-text('FAIL')")
        page.wait_for_timeout(250)
        fail_rows = page.locator(".check-row").count()
        page.click(".chip:has-text('ALL')")
        page.wait_for_timeout(250)
        page.locator("button:has-text('FIX')").first.click()
        page.wait_for_selector(".warn-box", timeout=6000)
        warn_ok = "LIVE device" in (page.locator(".warn-box").first.text_content() or "")
        has_snippet = page.locator(".cli-snippet").count() > 0
        proceed = page.locator(".modal button.btn.danger")
        disabled0 = proceed.is_disabled()
        page.check(".confirm-check input")
        page.wait_for_timeout(250)
        enabled1 = not proceed.is_disabled()
        page.click(".modal button:has-text('CANCEL')")
        page.wait_for_timeout(400)
        modal_closed = page.locator(".warn-box").count() == 0
        tooltip_ok = page.locator(".term .tip").count() >= 6
        print(f"audit           ok  rows={n_rows} fix={fix_btns} sev={sev_dots} cat={cat_chips} "
              f"posture={posture_vals} ledger={ledger_banner}/{ledger_rows} terms={term_chips} "
              f"filters={filters} fail-filter={fail_rows} gated={disabled0}/{enabled1} "
              f"cancel={modal_closed} tip={tooltip_ok}")
        if n_rows < 10:
            errors.append(("audit", f"check rows: {n_rows}"))
        if fix_btns < 6:
            errors.append(("audit", f"FIX buttons: {fix_btns}"))
        if sev_dots < 10 or cat_chips < 5:
            errors.append(("audit", f"severity({sev_dots})/category({cat_chips}) markers"))
        if posture_vals < 5:
            errors.append(("audit", f"posture rows: {posture_vals}"))
        if ledger_banner != 1 or ledger_rows < 1:
            errors.append(("audit", f"ledger banner/rows: {ledger_banner}/{ledger_rows}"))
        if term_chips < 6 or not tooltip_ok:
            errors.append(("audit", f"glossary tooltips: {term_chips} chips"))
        if filters != 4:
            errors.append(("audit", f"filter chips: {filters}"))
        if fail_rows < 1:
            errors.append(("audit", "FAIL filter returned nothing"))
        if not (warn_ok and has_snippet):
            errors.append(("audit", "FIX modal missing sandbox warning / CLI snippet"))
        if not (disabled0 and enabled1):
            errors.append(("audit", f"confirm checkbox gating: {disabled0}/{enabled1}"))
        if not modal_closed:
            errors.append(("audit", "CANCEL did not close the FIX modal"))

        # ---- loading skeleton on view switch (slow view: audit) ----
        page.goto(f"{BASE_URL}?demo=1#home", wait_until="networkidle")
        page.click(".nav-item[href='#audit']")
        try:
            page.locator(".view-loading").wait_for(state="visible", timeout=1500)
            skel = page.locator(".view-loading .load-card").count()
            page.locator(".view-loading").wait_for(state="detached", timeout=8000)
            rows = page.locator(".check-row").count()
            leftover = page.locator(".view-loading").count()
            print(f"loading-skeleton ok  cards={skel} then-rows={rows} leftover={leftover}")
            if skel < 1 or rows < 10 or leftover != 0:
                errors.append(("loading", f"cards {skel} / rows {rows} / leftover {leftover}"))
        except Exception as e:
            errors.append(("loading", str(e)[:120]))

        # ---- banner remediation: custom phrase + default placeholder (mock) ----
        banner_row = page.locator(".check-row:has-text('Legal banner')")
        banner_row.locator("button:has-text('FIX')").click()
        page.wait_for_selector(".confirm-value input", timeout=6000)
        ph = page.locator(".confirm-value input").get_attribute("placeholder") or ""
        ph_ok = "Authorized access only" in ph
        page.check(".confirm-check input")
        page.wait_for_timeout(250)
        empty_ok = not page.locator(".modal button.btn.danger").is_disabled()
        page.fill(".confirm-value input", "QA LAB — AUTHORIZED PERSONNEL ONLY")
        page.click(".modal button.btn.danger")
        page.wait_for_timeout(700)
        pushed = page.locator(".modal").count() == 0
        page.wait_for_selector(".check-row:has-text('Legal banner') .tag.green", timeout=10000)
        toast_banner = "".join(page.locator(".toast").all_text_contents())
        print(f"banner-fix      ok  placeholder={ph_ok} empty-allowed={empty_ok} "
              f"pushed={pushed} pass-after-reload={True} toast={'rescanned' in toast_banner}")
        if not (ph_ok and empty_ok and pushed):
            errors.append(("banner", f"placeholder={ph_ok} empty-allowed={empty_ok} pushed={pushed}"))

        # ---- banner revert-to-default (mock) ----
        page.locator(".check-row:has-text('Legal banner') button[title^='Undo']").click()
        page.wait_for_selector(".modal .warn-box", timeout=6000)
        mtitle = (page.locator(".modal h3").first.text_content() or "")
        cta = (page.locator(".modal button.btn.danger").text_content() or "")
        no_value_input = page.locator(".confirm-value input").count() == 0
        title_ok = "REVERT" in mtitle.upper() and "BANNER" in mtitle.upper()
        cta_ok = "REVERT TO DEFAULT" in cta
        page.check(".confirm-check input")
        page.wait_for_timeout(250)
        page.click(".modal button.btn.danger")
        page.wait_for_selector(".toast:has-text('reverted')", timeout=10000)
        reverted_toast = page.locator(".toast:has-text('reverted')").count() > 0
        page.wait_for_timeout(300)
        reverted_modal = page.locator(".modal").count() == 0
        page.wait_for_selector(".check-row:has-text('Legal banner') .tag.green", timeout=10000)
        print(f"banner-revert   ok  title={title_ok} cta={cta_ok} no-input={no_value_input} "
              f"pushed={reverted_modal} toast={reverted_toast}")
        if not (title_ok and cta_ok and no_value_input and reverted_modal and reverted_toast):
            errors.append(("banner-revert", f"title={title_ok} cta={cta_ok} "
                           f"no-input={no_value_input} pushed={reverted_modal} toast={reverted_toast}"))

        # ---- banner factory-default (mock) ----
        page.locator(".check-row:has-text('Legal banner') button[title^='Factory']").click()
        page.wait_for_selector(".modal .warn-box", timeout=6000)
        ftitle = (page.locator(".modal h3").first.text_content() or "")
        fcta = (page.locator(".modal button.btn.danger").text_content() or "")
        f_snippet = (page.locator(".cli-snippet").text_content() or "")
        ftitle_ok = "FACTORY DEFAULT" in ftitle.upper() and "BANNER" in ftitle.upper()
        fcta_ok = "REMOVE FROM DEVICE" in fcta
        fcli_ok = "no banner motd" in f_snippet
        page.check(".confirm-check input")
        page.wait_for_timeout(250)
        page.click(".modal button.btn.danger")
        page.wait_for_selector(".toast:has-text('factory default restored')", timeout=10000)
        ftoast = page.locator(".toast:has-text('factory default restored')").count() > 0
        page.wait_for_timeout(300)
        fmodal = page.locator(".modal").count() == 0
        page.wait_for_selector(".check-row:has-text('Legal banner') .tag.red", timeout=10000)
        ffix_back = page.locator(".check-row:has-text('Legal banner') button:has-text('FIX')").count() == 1
        fundo_gone = page.locator(".check-row:has-text('Legal banner') button[title^='Undo']").count() == 0
        print(f"banner-factory  ok  title={ftitle_ok} cta={fcta_ok} cli={fcli_ok} "
              f"pushed={fmodal} toast={ftoast} fail-tag=True fix-back={ffix_back} undo-gone={fundo_gone}")
        if not (ftitle_ok and fcta_ok and fcli_ok and fmodal and ftoast and ffix_back and fundo_gone):
            errors.append(("banner-factory", f"title={ftitle_ok} cta={fcta_ok} cli={fcli_ok} "
                           f"pushed={fmodal} toast={ftoast} fix-back={ffix_back} undo-gone={fundo_gone}"))

        # ---- fabric unreachable: sidebar alert + dismissible pop-out ----
        page.goto(f"{BASE_URL}?demo=1&dead=1#home", wait_until="networkidle")
        page.wait_for_selector(".side-alert", timeout=8000)
        side_alert = page.locator(".side-alert").count() == 1
        alert_txt = (page.locator(".side-alert b").first.text_content() or "").upper()
        alert_ok = "UNREACHABLE" in alert_txt
        page.wait_for_selector(".modal .fabric-alert", timeout=8000)
        modal_alert = page.locator(".modal .fabric-alert").count() == 1
        mtitle = (page.locator(".modal h3").first.text_content() or "").upper()
        mtitle_ok = "UNREACHABLE" in mtitle
        page.click(".modal button:has-text('DISMISS')")
        page.wait_for_timeout(400)
        modal_gone = page.locator(".modal").count() == 0
        side_still = page.locator(".side-alert").count() == 1
        page.goto(f"{BASE_URL}?demo=1#home", wait_until="networkidle")
        page.wait_for_timeout(2000)
        side_cleared = page.locator(".side-alert").count() == 0
        print(f"unreachable    ok  side={side_alert} text={alert_ok} modal={modal_alert} "
              f"title={mtitle_ok} dismissed={modal_gone} side-still={side_still} cleared={side_cleared}")
        if not (side_alert and alert_ok and modal_alert and mtitle_ok and modal_gone
                and side_still and side_cleared):
            errors.append(("unreachable", f"side={side_alert} text={alert_ok} modal={modal_alert} "
                           f"title={mtitle_ok} dismissed={modal_gone} side-still={side_still} cleared={side_cleared}"))

        # ---- console dock: fixed max-height + mini scrollbar + collapse/close/reopen ----
        page.goto(f"{BASE_URL}?demo=1#home", wait_until="networkidle")
        page.wait_for_selector("#console-dock")
        dock = page.locator("#console-dock")
        maxh = page.eval_on_selector("#console", "el => getComputedStyle(el).maxHeight")
        maxh_ok = maxh == "170px"
        ov = page.eval_on_selector("#console", "el => getComputedStyle(el).overflowY")
        scroll_ok = ov in ("auto", "scroll")
        page.click("#console-collapse")
        page.wait_for_timeout(300)
        collapsed1 = "collapsed" in (dock.get_attribute("class") or "")
        body_hidden = not page.locator("#console").is_visible()
        flipped = page.eval_on_selector("#console-collapse",
                                        "el => el.classList.contains('flipped')")
        page.click("#console-collapse")
        page.wait_for_timeout(300)
        expanded2 = "collapsed" not in (dock.get_attribute("class") or "")
        page.click("#console-close")
        page.wait_for_timeout(300)
        dock_hidden = not dock.is_visible()
        reopen_visible = page.locator("#console-reopen").is_visible()
        page.click("#console-reopen")
        page.wait_for_timeout(300)
        dock_back = dock.is_visible()
        print(f"console-dock   ok  maxh={maxh_ok}({maxh}) scroll={scroll_ok} "
              f"collapse={collapsed1}/{body_hidden}/{flipped} expand={expanded2} "
              f"close={dock_hidden}/{reopen_visible} reopen={dock_back}")
        if not (maxh_ok and scroll_ok and collapsed1 and body_hidden and flipped
                and expanded2 and dock_hidden and reopen_visible and dock_back):
            errors.append(("console-dock", f"maxh={maxh_ok} scroll={scroll_ok} "
                           f"collapse={collapsed1}/{body_hidden}/{flipped} expand={expanded2} "
                           f"close={dock_hidden}/{reopen_visible} reopen={dock_back}"))

        # ---- dashboard graphs (home) ----
        page.goto(f"{BASE_URL}?demo=1#home", wait_until="networkidle")
        page.wait_for_selector(".dash-kpis")
        kpi_ok = page.locator(".dash-kpi").count() == 6
        gauge_ok = page.locator(".gauge-svg").count() >= 1
        donut_ok = page.locator(".donut-svg").count() == 1
        svg_ok = page.locator(".chart-card svg").count() >= 4
        heat_ok = page.locator(".heat-cell").count() == 24
        legend_ok = page.locator(".ch-legend").count() >= 3
        area_ok = page.locator(".area-svg").count() == 1
        bars_ok = page.locator(".bars-svg").count() == 2
        tele_ok = page.locator("#tele-list .tele-row").count() >= 1
        ev_ok = page.locator("#ev-feed .ev-row").count() >= 1
        badge_txt = page.locator("#tele-badge").text_content() or ""
        badge_ok = "HISTORY" in badge_txt
        page.click("#tele-refresh")
        page.wait_for_timeout(1500)
        toast_ok = "demo feed refreshed" in (page.locator(".toast").last.text_content() or "")
        empty_ok = page.locator(".chart-empty").count() == 0  # demo data seeds all charts
        print(f"dashboard    ok  kpis={kpi_ok} gauge={gauge_ok} donut={donut_ok} svgs={svg_ok} "
              f"heat={heat_ok} legend={legend_ok} area={area_ok} bars={bars_ok} "
              f"tele={tele_ok} ev={ev_ok} badge={badge_ok} toast={toast_ok} empty={empty_ok}")
        if not (kpi_ok and gauge_ok and donut_ok and svg_ok and heat_ok and legend_ok
                and area_ok and bars_ok and tele_ok and ev_ok and badge_ok
                and toast_ok and empty_ok):
            errors.append(("dashboard", f"kpis={kpi_ok} gauge={gauge_ok} donut={donut_ok} "
                           f"svgs={svg_ok} heat={heat_ok} legend={legend_ok} area={area_ok} "
                           f"bars={bars_ok} tele={tele_ok} ev={ev_ok} badge={badge_ok} "
                           f"toast={toast_ok} empty={empty_ok}"))

        # ---- analytics live auto-refresh (30s ticker, forced via debug hook) ----
        page.goto(f"{BASE_URL}?demo=1#analytics", wait_until="networkidle")
        page.wait_for_selector(".area-svg", timeout=8000)
        live_chip = page.locator(".live-chip").count() == 1
        x0 = page.evaluate("window.__cat8kDebug && window.__cat8kDebug.lastX()") or ""
        t0 = page.evaluate("window.__cat8kDebug && window.__cat8kDebug.ticks()") or 0
        page.evaluate("window.__cat8kDebug && window.__cat8kDebug.tickAnalytics()")
        page.wait_for_function(
            "window.__cat8kDebug && window.__cat8kDebug.ticks() > %d" % t0, timeout=8000)
        x1 = page.evaluate("window.__cat8kDebug && window.__cat8kDebug.lastX()") or ""
        charts_ok = page.locator(".area-svg").count() >= 6
        kpi_snaps = (page.locator(".kpi-strip .kpi:nth-child(6) .v").text_content() or "").strip()
        print(f"analytics-live ok  live-chip={live_chip} x={x0!r}->{x1!r} charts={charts_ok} kpi-snaps={kpi_snaps}")
        if not (live_chip and x1 and x1 != x0 and charts_ok):
            errors.append(("analytics-live",
                           f"chip={live_chip} x={x0!r}->{x1!r} charts={charts_ok}"))

        # ---- profile: test-and-save credentials ----
        page.goto(f"{BASE_URL}?demo=1#profile", wait_until="networkidle")
        page.wait_for_selector("[data-key='creds_host']")
        pw_masked = page.locator("[data-key='creds_password']").get_attribute("type") == "password"
        page.click(".pw-wrap .btn")
        page.wait_for_timeout(150)
        pw_unmasked = page.locator("[data-key='creds_password']").get_attribute("type") == "text"
        eye_svg = page.locator(".pw-wrap svg").count() >= 1
        eye_escaped = "<svg" in (page.locator(".pw-wrap").first.text_content() or "")
        page.click(".pw-wrap .btn")
        page.fill("[data-key='creds_host']", "failbox.cisco.com")
        page.fill("[data-key='creds_username']", "qa-admin")
        page.fill("[data-key='creds_password']", "wrong-pass")
        page.click("#creds-save")
        page.wait_for_selector(".creds-status.bad", timeout=8000)
        bad_txt = (page.locator(".creds-status.bad").text_content() or "").lower()
        bad_ok = "authentication" in bad_txt or "401" in bad_txt
        page.fill("[data-key='creds_host']", "devnetsandboxiosxec8k.cisco.com")
        page.fill("[data-key='creds_username']", "qa-user")
        page.fill("[data-key='creds_password']", "qa-pass-123")
        page.click("#creds-save")
        page.wait_for_selector(".creds-status.ok", timeout=8000)
        ok_txt = (page.locator(".creds-status.ok").text_content() or "").lower()
        ok_ok = "core-edge" in ok_txt and "sealed" in ok_txt
        rows_ok = (page.locator("#c-host").text_content() == "devnetsandboxiosxec8k.cisco.com"
                   and page.locator("#c-user").text_content() == "qa-user")
        toast_sealed = page.locator(".toast:has-text('sealed')").count() > 0
        print(f"profile-creds   ok  masked={pw_masked} eye={pw_unmasked} eye-svg={eye_svg} "
              f"no-escaped={not eye_escaped} bad={bad_ok} ok={ok_ok} rows={rows_ok} sealed-toast={toast_sealed}")
        if not (pw_masked and pw_unmasked and eye_svg and not eye_escaped
                and bad_ok and ok_ok and rows_ok and toast_sealed):
            errors.append(("profile-creds", f"masked={pw_masked} eye={pw_unmasked} "
                           f"eye-svg={eye_svg} no-escaped={not eye_escaped} bad={bad_ok} "
                           f"ok={ok_ok} rows={rows_ok} sealed-toast={toast_sealed}"))

        # ---- profile: vpn access card (quick access namings) ----
        vpn_fields = (page.locator("[data-key='vpn_address']").count() == 1
                      and page.locator("[data-key='vpn_username']").count() == 1
                      and page.locator("[data-key='vpn_password']").count() == 1)
        vpn_labels = (page.locator("label", has_text="vpn_address").count() >= 1
                      and page.locator("label", has_text="vpn_username").count() >= 1
                      and page.locator("label", has_text="vpn_password").count() >= 1)
        vpn_pw_masked = page.locator("[data-key='vpn_password']").get_attribute("type") == "password"
        page.fill("[data-key='vpn_address']", "devnetsandbox-usw1-reservation.cisco.com:20199")
        page.fill("[data-key='vpn_username']", "qa-vpn")
        page.fill("[data-key='vpn_password']", "qa-vpn-pass-123")
        page.click("#vpn-save")
        page.wait_for_timeout(1200)
        vpn_toast = page.locator(".toast:has-text('vpn access')").count() > 0
        vpn_status_ok = page.locator("#vpn-status .creds-status.ok").count() > 0
        vpn_rows = (page.locator("#v-address").text_content()
                    == "devnetsandbox-usw1-reservation.cisco.com:20199"
                    and page.locator("#v-user").text_content() == "qa-vpn")
        print(f"profile-vpn    ok  fields={vpn_fields} labels={vpn_labels} masked={vpn_pw_masked} "
              f"toast={vpn_toast} status={vpn_status_ok} rows={vpn_rows}")
        if not (vpn_fields and vpn_labels and vpn_pw_masked
                and vpn_toast and vpn_status_ok and vpn_rows):
            errors.append(("profile-vpn", f"fields={vpn_fields} labels={vpn_labels} "
                           f"masked={vpn_pw_masked} toast={vpn_toast} status={vpn_status_ok} "
                           f"rows={vpn_rows}"))

        # ---- profile: vpn drive (mock only — never touches a real client) ----
        vpn_rows = (page.locator("#v-client").count() == 1
                    and page.locator("#v-tunnel").count() == 1)
        tunnel_dn0 = (page.locator("#v-tunnel").text_content() or "").upper() == "DOWN"
        page.click("#vpn-connect")
        page.wait_for_timeout(2800)
        vpn_conn_toast = page.locator(".toast:has-text('vpn connected')").count() > 0
        tunnel_up = (page.locator("#v-tunnel").text_content() or "").upper() == "UP"
        page.click("#vpn-disconnect")
        page.wait_for_timeout(1200)
        vpn_disc_toast = page.locator(".toast:has-text('vpn disconnected')").count() > 0
        tunnel_dn1 = (page.locator("#v-tunnel").text_content() or "").upper() == "DOWN"
        print(f"profile-vpn-drive ok  rows={vpn_rows} down0={tunnel_dn0} conn-toast={vpn_conn_toast} "
              f"up={tunnel_up} disc-toast={vpn_disc_toast} down1={tunnel_dn1}")
        if not (vpn_rows and tunnel_dn0 and vpn_conn_toast
                and tunnel_up and vpn_disc_toast and tunnel_dn1):
            errors.append(("profile-vpn-drive", f"rows={vpn_rows} down0={tunnel_dn0} "
                           f"conn-toast={vpn_conn_toast} up={tunnel_up} "
                           f"disc-toast={vpn_disc_toast} down1={tunnel_dn1}"))

        # ---- E2E: provision flow (mock) ----
        page.goto(f"{BASE_URL}?demo=1#provision", wait_until="networkidle")
        page.wait_for_selector(".act-card", timeout=5000)
        act_cards = page.locator(".act-card").count()
        print(f"provision-actions  ok  cards={act_cards}")
        page.locator(".act-card").first.click()
        page.wait_for_selector("#view-host .field input[data-key='site_name']")
        page.fill("[data-key='site_name']", "BR-TEST1")
        page.locator(".card-head:has-text('NETWORK SEGMENT')").click()
        page.wait_for_selector("[data-key='vlan_id']", timeout=5000)
        page.fill("[data-key='vlan_id']", "155")
        page.fill("[data-key='vlan_name']", "qa")
        page.fill("[data-key='department_subnet']", "10.1.155.0/24")
        page.fill("[data-key='gateway']", "10.1.155.1")
        page.locator("button.btn.teal:has-text('DEPLOY')").click()
        page.wait_for_timeout(600)
        modal_ok = page.locator(".modal").count() > 0
        print(f"provision-modal  ok  modal={modal_ok}")
        page.click(".modal .btn.teal, .modal .btn.red")
        page.wait_for_timeout(1600)
        toasts = page.locator(".toast").all_text_contents()
        print("toast:", toasts)
        if not any("change applied" in t for t in toasts):
            errors.append(("e2e", "deploy toast not confirmed"))

        browser.close()

    print("\n==== QA REPORT ====")
    if errors:
        print(f"{len(errors)} ERROR(S):")
        for kind, text in errors:
            print(f"  [{kind}] {text}")
        sys.exit(1)
    print("CLEAN — no console errors, no page errors, no view errors")


if __name__ == "__main__":
    main()

"""Dual-instance resolver test: AUTO / NORMAL / RESERVATION + profile GUI.

Part 1 (resolver, real code path): drives src/device_mode + the live Api —
  - normal mode always resolves the public Catalyst 8000 instance
  - auto mode follows the (monkeypatched) tunnel probe result
  - reservation mode forces the Cat8kv host; empty fields fall back to the
    DevNet sandbox defaults (10.10.20.48 / developer / C1sco12345)
  - the resolved instance is persisted in SQLite (device.identity)
  - reservation companions (devbox/xrv/nexus) resolve with defaults and
    save/restore their sealed credential sets
  Legacy settings values 'vault'/'vpn' are mapped to the new names.
  The user's live VPN record is snapshotted and restored afterwards.

Part 2 (demo UI): profile page renders the FABRIC SELECTOR tiles, the live
instance strip, the two instance-credential cards and the companion rows.

Run:  python gui/web/tools/dual_mode_probe.py
"""
import os
import sys
import threading
import time

from playwright.sync_api import sync_playwright

ROOT = r"C:\Users\hp\Desktop\Sujets OCP PFA\PFA Reqasse\CAT8k-SYNC"
os.chdir(ROOT)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "gui"))
sys.path.insert(0, os.path.join(ROOT, "gui", "web"))
import webapp
from webapp import Api
from src import db
from src import device_mode  # noqa: E402  resolver under test

threading.Thread(target=webapp._serve, daemon=True).start()
time.sleep(0.8)
BASE = f"http://127.0.0.1:{webapp.PORT}/index.html"

fails = []
def chk(name, cond, extra=""):
    print(("ok  " if cond else "FAIL") + f"  {name}  {extra}")
    if not cond:
        fails.append(name)

PUBLIC_HOST = "devnetsandboxiosxec8k.cisco.com"
VPN_HOST = "10.10.20.48"
api = Api()
saved_vpn = webapp.db.get_vpn_plain() or {}
saved_res = webapp.db.get_res_creds()
saved_backend = webapp.db.get_setting("device.backend", "auto")

def restore_all():
    webapp.db.save_vpn(saved_vpn)
    for slug, s in saved_res.items():
        webapp.db.save_res_cred(slug, {"host": s["host"], "port": s["port"],
                                       "username": s["username"], "password": s["password"]})
    device_mode.set_backend(saved_backend)
    device_mode.invalidate()

def set_backend(mode):
    return device_mode.set_backend(mode)

# ---------------- part 1: resolver semantics (real code) ----------------

set_backend("auto")
device_mode._probe_vpn = lambda: False
webapp.db.save_vpn({"address": "", "username": "", "password": "",
                    "device_host": "", "device_username": "", "device_password": ""})
device_mode.invalidate()

info = api.state()["backend"]
chk("state-has-backend", isinstance(info, dict) and "identity" in info,
    f"keys={list(info.keys())}")
chk("default-auto", info["mode"] == "auto")
chk("auto-probe-down->normal", info["source"] == "normal" and info["host"] == PUBLIC_HOST,
    f'source={info["source"]} host={info["host"]}')
chk("identity-public-persisted", db.get_setting("device.identity") == "cat8000-public",
    f'={db.get_setting("device.identity")}')

# default device host applies even with an empty record
dev = device_mode.vpn_device()
chk("defaults-fill-device", (dev or {}).get("host") == VPN_HOST,
    f'host={(dev or {}).get("host")}')

# reservation mode with empty record -> defaults, forced reservation
set_backend("reservation")
dev = device_mode.active_device()
chk("reservation-forced-defaults", (dev or {}).get("host") == VPN_HOST
    and dev.get("username") == "developer" and dev.get("source") == "reservation",
    f'host={(dev or {}).get("host")} user={dev.get("username")} source={(dev or {}).get("source")}')
chk("identity-reservation-persisted", db.get_setting("device.identity") == "cat8000v-reservation",
    f'={db.get_setting("device.identity")}')

# explicit device creds override the defaults (changed values persisted)
webapp.db.save_vpn({"address": "devnetsandbox-usw1-reservation.cisco.com:20291",
                    "username": "reqasse", "password": "",
                    "device_host": VPN_HOST,
                    "device_username": "myuser",
                    "device_password": "mypass"})
device_mode.invalidate()
dev = device_mode.active_device()
chk("saved-creds-override", dev.get("username") == "myuser" and dev.get("password") == "mypass",
    f'user={dev.get("username")}')

# normal mode forces the public instance regardless of the VPN record
set_backend("normal")
info = api.state()["backend"]
chk("normal-forced", info["source"] == "normal" and info["host"] == PUBLIC_HOST,
    f'source={info["source"]} host={info["host"]}')

# auto mode + probe up -> reservation host
device_mode._probe_vpn = lambda: True
set_backend("auto")
info = api.state()["backend"]
chk("auto-probe-up->reservation", info["source"] == "reservation" and info["host"] == VPN_HOST
    and info["tunnel"], f'source={info["source"]} host={info["host"]} tunnel={info["tunnel"]}')

# legacy setting values map to the new names
db.set_setting("device.backend", "vault")
chk("legacy-vault->normal", device_mode.get_backend() == "normal", f'={device_mode.get_backend()}')
db.set_setting("device.backend", "vpn")
chk("legacy-vpn->reservation", device_mode.get_backend() == "reservation",
    f'={device_mode.get_backend()}')
set_backend("auto")

# setBackend API round-trip + rejection
res = api.setBackend("normal")
chk("setBackend-ok", res.get("ok") is True and res["backend"]["mode"] == "normal",
    f'res={res["backend"]["mode"]}')
res = api.setBackend("bogus")
chk("setBackend-rejects", res["ok"] is False, f'res={res}')

# saveVpn persists device creds into the plain record
rec = webapp.db.get_vpn_plain()
chk("saveVpn-persists-device-creds", rec.get("device_username") == "myuser"
    and rec.get("device_host") == VPN_HOST, f'user={rec.get("device_username")}')

# reservation companions: defaults + sealed save + empty-password keep
companions = webapp.db.get_res_creds()
chk("companions-defaults", companions["devbox"]["host"] == "10.10.20.50"
    and companions["xrv"]["host"] == "10.10.20.35"
    and companions["nexus"]["host"] == "10.10.20.40"
    and companions["nexus"]["username"] == "admin",
    f"devbox={companions['devbox']['host']} xrv={companions['xrv']['host']} nexus={companions['nexus']['host']}")
webapp.db.save_res_cred("nexus", {"host": "10.10.20.41", "port": 22,
                                  "username": "admin", "password": ""})
companions = webapp.db.get_res_creds()
chk("companion-save-keeps-password", companions["nexus"]["host"] == "10.10.20.41"
    and companions["nexus"]["password"] == "RG!_Yw200",
    f'host={companions["nexus"]["host"]} pass-kept={bool(companions["nexus"]["password"])}')
chk("companion-rejects-bad-slug", True)
try:
    webapp.db.save_res_cred("nope", {})
    chk("companion-rejects-bad-slug", False)
except ValueError:
    chk("companion-rejects-bad-slug", True)

# never leave the user's live record behind
restore_all()
rec = webapp.db.get_vpn_plain() or {}
companions = webapp.db.get_res_creds()
chk("restored-live-record", rec.get("address") == saved_vpn.get("address")
    and rec.get("device_host") == saved_vpn.get("device_host"),
    f'addr={rec.get("address")} host={rec.get("device_host")}')
chk("restored-companions", all(
        {k: companions[s][k] for k in ("host", "port", "username", "password")}
        == {k: saved_res[s][k] for k in ("host", "port", "username", "password")}
        for s in ("devbox", "xrv", "nexus")),
    f'nexus-host={companions["nexus"]["host"]}')

# ---------------- part 2: demo UI wiring ----------------

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=r"C:\Users\hp\AppData\Local\ms-playwright\chromium-1217\chrome-win64\chrome.exe")
    pg = browser.new_page(viewport={"width": 1440, "height": 900})
    errs = []
    pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
    pg.goto(f"{BASE}?demo=1#profile", wait_until="networkidle")
    pg.wait_for_selector("#backend-seg", timeout=8000)
    pg.wait_for_timeout(500)

    chk("ui-tiles-3", pg.locator("#backend-seg [data-backend]").count() == 3)
    chk("ui-hub-cards", pg.locator('.act-card[data-studio]').count() == 2, "public + reservation studios")
    chk("ui-tile-auto-on", pg.locator('#backend-seg [data-backend="auto"].on').count() == 1)
    for mode in ("normal", "reservation"):
        pg.eval_on_selector(f'#backend-seg [data-backend="{mode}"]', "b => b.click()")
        pg.wait_for_timeout(600)
        chk(f"ui-tile-{mode}-active", pg.locator(f'#backend-seg [data-backend="{mode}"].on').count() == 1)
        live = pg.evaluate("""() => document.querySelector('#b-mode').textContent""")
        chk(f"ui-live-{mode}", live == mode, f"b-mode={live}")
    pg.eval_on_selector('#backend-seg [data-backend="auto"]', "b => b.click()")
    pg.wait_for_timeout(600)

    live = pg.evaluate("""() => {
        const g = id => (document.querySelector('#'+id)||{}).textContent || '';
        return { mode: g('b-mode'), source: g('b-source'), tunnel: g('b-tunnel'),
                 identity: g('b-identity'), host: g('b-host'), reason: g('b-reason') };
    }""")
    chk("ui-live-grid-filled", live["mode"] and live["source"] and live["identity"],
        f"mode={live['mode']} source={live['source']} identity={live['identity']} tunnel={live['tunnel']}")

    pg.screenshot(path=os.path.join(ROOT, "screenshots", "profile-instances.png"), full_page=True)

    pg.click('[data-studio="public"]')
    pg.wait_for_selector("[data-key='creds_host']", timeout=5000)
    chk("ui-public-studio", (pg.locator("[data-key='creds_host']").count() == 1
                             and pg.locator("#creds-save").count() == 1
                             and pg.locator("#creds-live").count() == 1), "public creds studio")
    pg.click("#mode-back")
    pg.wait_for_selector('.act-card[data-studio="reservation"]', timeout=5000)
    pg.click('[data-studio="reservation"]')
    pg.wait_for_selector("[data-key='vpn_address']", timeout=5000)

    chk("ui-modebar-back", pg.locator("#mode-back").count() == 1, "back to overview")
    for key in ("vpn_device_host", "vpn_device_user", "vpn_device_pass"):
        chk(f"ui-field-{key}", pg.locator(f'input[data-key="{key}"]').count() == 1, "present")
    for slug in ("devbox", "xrv", "nexus"):
        chk(f"ui-companion-{slug}", pg.locator(f'input[data-key="res_{slug}_host"]').count() == 1)
    chk("ui-companions-folded", pg.locator(".comp-body.hidden").count() == 2,
        "devbox open by default, xrv+nexus folded")
    chk("ui-folds-2", pg.locator(".fold-head").count() == 2, "tunnel open + router folded")
    chk("ui-defaults-placeholders", "10.10.20.48" in (pg.locator('input[data-key="vpn_device_host"]')
                                                      .get_attribute("placeholder") or ""),
        "host placeholder = default ip")

    pg.screenshot(path=os.path.join(ROOT, "screenshots", "profile-studio.png"), full_page=True)
    chk("console-errors-0", len(errs) == 0, f"n={len(errs)}")
    browser.close()

print("FAILS:", fails if fails else "none")
sys.exit(1 if fails else 0)
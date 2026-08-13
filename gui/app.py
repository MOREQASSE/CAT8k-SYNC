"""CAT8k-SYNC // MODERN CONTROL DASHBOARD

CustomTkinter GUI wrapping the RESTCONF automation engine.
Run (from anywhere):  python CAT8k-SYNC/gui/app.py

Views:
  HUB        quick-launch landing (low learning curve)
  PROVISION  declare / preview / push branch automations + cleanup
  TELEMETRY  live device state (snapshot, interfaces, ARP, BGP, OSPF)
  AUDIT      hardening scan + config drift diff

Shell: dark sidebar + light topbar/status + card-grid views (no canvas).
"""
import os
import re
import sys
import time
import tkinter as tk

import customtkinter as ctk

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE not in sys.path:
    sys.path.insert(0, BASE)

from gui import widgets as W  # noqa: E402
from gui import icons as IC  # noqa: E402
from gui.topo import TopologyPanel, parse_interfaces  # noqa: E402
from gui.engine import Engine, BASE as ENGINE_BASE  # noqa: E402
from gui.theme import C, F, NAV, R  # noqa: E402
from src import db, vault  # noqa: E402

BASE = ENGINE_BASE

VLAN_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
IPV4_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
SUBNET_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}/\d{1,2}$")
ANIM_MS = 14

HELP_TEXT = {
    "hub": (
        "HUB // WHAT DOES THIS TOOL DO?\n\n"
        "It automates a Cisco Catalyst 8000 (IOS XE 17.15) via RESTCONF over HTTPS.\n"
        "Pick a card to jump into a workflow. The device is checked every 20s.\n"
        "Keyboard: 1-4 switch views, F5 health check.\n"
        "Everything runs on THIS laptop \u2014 the box lives in the Cisco cloud sandbox."
    ),
    "provision": (
        "PROVISION // HOW IT WORKS\n\n"
        "1) Pick an action. DEPLOY BRANCH creates a VLAN subinterface +\n"
        "   gateway IP on the device. DELETE BRANCH removes one.\n"
        "2) Fill the form. Fields validate live (red = fix).\n"
        "3) PREVIEW PAYLOAD shows the exact YANG JSON + URL sent \u2014 zero guessing.\n"
        "4) DEPLOY sends it via RESTCONF PUT/DELETE. DRY-RUN prints only.\n"
        "Tip: the Catalyst 8000 has no VLAN database, so VLAN is labelled only."
    ),
    "telemetry": (
        "TELEMETRY // LIVE STATE\n\n"
        "SNAPSHOT = one call: hostname, IOS version, CPU, memory,\n"
        "           interfaces, ARP neighbours, BGP families.\n"
        "INTERFACES renders the raw YANG JSON as a LIVE TOPOLOGY:\n"
        "           port LED list + cloud/router/switch map + stats panel.\n"
        "Then drill down: raw operational trees for ARP/OSPF/BGP.\n"
        "FULL COLLECT saves the whole state to logs/ for the audit view."
    ),
    "audit": (
        "AUDIT // HARDENING + DRIFT\n\n"
        "COLLECT + SCAN pulls the config and checks 3 benchmark classes:\n"
        "  A transport (Telnet vs SSH)   B enable secret   C syslog.\n"
        "DRIFT CHECK diffs the live config against your saved baseline\n"
        "(logs/baseline_running_config.txt). First run creates the baseline.\n"
        "SET BASELINE re-captures it after a planned change."
    ),
}


class Console(ctk.CTkFrame):
    """Dark rounded terminal feed with severity color tags."""

    def __init__(self, master, height=5):
        super().__init__(master, fg_color=C["dark"], corner_radius=10)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        head = tk.Frame(self, bg=C["dark"])
        head.grid(row=0, column=0, sticky="ew", padx=12, pady=(8, 4))
        ctk.CTkLabel(head, text="TERMINAL FEED", font=F["small"],
                     text_color=C["teal_l"], anchor="w").pack(side="left")
        ctk.CTkLabel(head, text="live engine log", font=F["tiny"],
                     text_color=C["muted"], anchor="w").pack(side="left", padx=(8, 0))
        clear = ctk.CTkLabel(head, text="clear", font=F["small"],
                             text_color=C["muted"], cursor="hand2")
        clear.pack(side="right", padx=(0, 14))
        clear.bind("<Button-1>", lambda _e: self.clear())
        self._copy_lbl = ctk.CTkLabel(head, text="\u29c9 copy", font=F["small"],
                                      text_color=C["teal_l"], cursor="hand2")
        self._copy_lbl.pack(side="right")
        self._copy_lbl.bind("<Button-1>", lambda _e: self.copy_all())

        self.text = tk.Text(
            self, bg=C["dark"], fg=C["cream"], insertbackground=C["cream"],
            font=F["mono"], wrap="word", state="disabled",
            relief="flat", borderwidth=0, padx=12, pady=6,
            height=height, width=96,
        )
        self.text.grid(row=1, column=0, sticky="nsew")
        scroll = tk.Scrollbar(self, command=self.text.yview, bg=C["dark"],
                              troughcolor=C["dark"], bd=0,
                              highlightthickness=0, activebackground=C["dim"])
        scroll.grid(row=1, column=1, sticky="ns")
        self.text.configure(yscrollcommand=scroll.set)

        self.text.tag_config("ok", foreground=C["green"])
        self.text.tag_config("fail", foreground=C["red"])
        self.text.tag_config("warn", foreground=C["yellow"])
        self.text.tag_config("dim", foreground=C["muted"])
        self.text.tag_config("time", foreground=C["muted"])

    def _tag(self, line):
        if "[FAIL]" in line or "[FATAL]" in line:
            return "fail"
        if "[OK]" in line:
            return "ok"
        if any(k in line for k in ("[WARN]", "[RETRY]", "[HINT]", "INVALID")):
            return "warn"
        return None

    def write(self, msg):
        self.text.configure(state="normal")
        ts = time.strftime("%H:%M:%S")
        for raw in msg.splitlines():
            self.text.insert("end", f"[{ts}] ", ("time",))
            tag = self._tag(raw)
            self.text.insert("end", raw + "\n", (tag,) if tag else ())
        self.text.see("end")
        self.text.configure(state="disabled")

    def clear(self):
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")

    def copy_all(self):
        """Copy the whole terminal feed to the clipboard."""
        text = self.text.get("1.0", "end-1c").strip()
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self._copy_lbl.configure(text="\u2713 copied")
        self.after(1400, lambda: self._copy_lbl.configure(text="\u29c9 copy"))


class Toast(tk.Frame):
    """Transient pill banner that slides in from the top."""

    def __init__(self, master):
        super().__init__(master, bg=C["dark"])
        self.label = ctk.CTkLabel(self, text="", font=F["h1"], text_color=C["teal"])
        self.label.pack(padx=26, pady=9)
        self.after_id = None
        self._anim = None
        self.place_forget()

    def show(self, text, color=C["yellow"]):
        self.label.configure(text=text, text_color=color)
        if self.after_id:
            self.after_cancel(self.after_id)
        self.place(relx=0.5, y=-34, anchor="n")
        self.lift()

        def slide(y):
            if y >= 14:
                self.place(relx=0.5, y=14, anchor="n")
                return
            self.place(relx=0.5, y=y, anchor="n")
            self._anim = self.after(ANIM_MS, slide, y + 3)

        slide(-30)
        self.after_id = self.after(2800, self.hide)

    def hide(self):
        self.place_forget()


class App(ctk.CTk):
    def __init__(self, login=True):
        super().__init__()
        self.title("CAT8k-SYNC // CONTROL CLOUD")
        self.geometry("1280x720")
        self.minsize(1100, 620)
        self.resizable(True, True)
        self.configure(fg_color=C["bg"])

        self._login_mode = bool(login)
        self.engine = Engine(self._on_task_done, on_start=self._on_task_start)
        self.views = {}
        self.nav_buttons = {}
        self.action_buttons = []
        self.backend_dot = None
        self.backend_nav = None
        self.toast = None
        self.backend_up = None
        self.backend_hostname = None
        self._checking = False
        self._busy_depth = 0
        self._pulse_id = None
        self._blink_id = None
        self._progress_id = None
        self._dots_after = None
        self._last_label = None
        self._preview_write = None
        self.topo_panel = None
        self._topo_raw = None
        self._auto_console = False
        self.HEALTH_MS = 20000
        self._ticker_id = None
        self._auth_frame = None
        self._trends = {}

        db.init()
        self.user = db.get_user()
        if self._login_mode:
            self._build_auth()
        else:
            self._boot()
    def _boot(self):
        """Build the full shell once identity/device are resolved."""
        self.user = db.get_user()
        self._build_menubar()
        self._build_shell()
        self._build_nav()
        self._build_main()
        self._build_hub_view()
        self._build_provision_view()
        self._build_telemetry_view()
        self._build_audit_view()
        self._switch("hub")
        self._refresh_trends()

        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.bind("<F5>", lambda _e: self._manual_health())
        self.bind("<Control-Key-1>", lambda _e: self._switch("hub"))
        self.bind("<Control-Key-2>", lambda _e: self._switch("provision"))
        self.bind("<Control-Key-3>", lambda _e: self._switch("telemetry"))
        self.bind("<Control-Key-4>", lambda _e: self._switch("audit"))
        for k in "1234":
            self.bind(f"<Key-{k}>", lambda _e, kk=k: self._switch(
                {"1": "hub", "2": "provision", "3": "telemetry", "4": "audit"}[kk]))

        self.after(600, self._manual_health)
        self._schedule_health()
        self._schedule_ticker()

    # ================= auth (first-run setup / login) =================

    def _build_auth(self):
        """Full-screen identity + device vault gate before the shell."""
        frame = tk.Frame(self, bg=C["bg"])
        frame.place(relwidth=1, relheight=1, x=0, y=0)
        self._auth_frame = frame
        frame.grid_columnconfigure(0, weight=1)

        card = tk.Frame(frame, bg=C["dark"], highlightthickness=0)
        card.place(relx=0.5, rely=0.5, anchor="center")
        W.IconLabel(card, "cloud-server", 46, C["teal_l"]).pack(pady=(28, 10))
        ctk.CTkLabel(card, text="Company // CONTROL CLOUD", font=F["brand"],
                     text_color=C["cream"]).pack()
        ctk.CTkLabel(card, text="CISCO NETWORK AUTOMATION \u2014 SECURE VAULT",
                     font=F["tiny"], text_color=C["muted"]).pack(pady=(2, 18))

        first = not db.has_user()
        self._auth_mode = "setup" if first else "login"
        body = tk.Frame(card, bg=C["dark"])
        body.pack(fill="x", padx=36, pady=(0, 30))

        if first:
            ctk.CTkLabel(body, text="FIRST RUN // SETUP", font=F["h1"],
                         text_color=C["teal_l"], anchor="w").pack(
                anchor="w", pady=(0, 4))
            ctk.CTkLabel(body, text="Credentials are encrypted at rest in the "
                                    "SQLite vault \u2014 never in scripts.",
                         font=F["tiny"], text_color=C["muted"], anchor="w",
                         justify="left").pack(anchor="w", pady=(0, 14))

            self._auth_vars = {}
            pairs = [
                ("USERNAME (DASHBOARD)", "f_user", "your name", False),
                ("PASSPHRASE (OPTIONAL)", "f_pass", "leave blank for free entry", True),
                ("DEVICE NAME", "f_dev_name", "Cat8000-Sandbox", False),
                ("DEVICE HOST", "f_host", "devnetsandboxiosxec8k.cisco.com", False),
                ("DEVICE USERNAME", "f_dev_user", "device login", False),
                ("DEVICE PASSWORD", "f_dev_pass", "restconf secret", True),
                ("ENABLE SECRET", "f_secret", "privileged exec", True),
            ]
            for label, key, ph, secret in pairs:
                var = tk.StringVar()
                self._auth_vars[key] = var
                row = tk.Frame(body, bg=C["dark"])
                row.pack(fill="x", pady=3)
                ctk.CTkLabel(row, text=label, font=F["label"],
                             text_color=C["muted"], width=190, anchor="w").pack(
                    side="left")
                entry = ctk.CTkEntry(
                    row, textvariable=var, placeholder_text=ph, show="*" if secret else "",
                    width=300, height=38, corner_radius=8, border_width=1,
                    border_color=C["dark3"], fg_color=C["dark2"],
                    text_color=C["cream"], font=F["mono"])
                entry.pack(side="right")
            W.Btn(body, "SAVE & LAUNCH", cmd=self._auth_submit, color=C["teal"],
                  width=300, height=42, icon="server-sucess-tick").pack(
                pady=(18, 4))
            self._auth_error = ctk.CTkLabel(body, text="", font=F["tiny"],
                                            text_color=C["red"])
            self._auth_error.pack()
        else:
            user = db.get_user()
            ctk.CTkLabel(body, text=f"WELCOME BACK, {user['username'].upper()}",
                         font=F["h1"], text_color=C["teal_l"], anchor="w").pack(
                anchor="w", pady=(0, 4))
            need_pass = bool(user.get("password_hash"))
            if need_pass:
                ctk.CTkLabel(body, text="Enter your passphrase to unlock the "
                                        "dashboard.",
                             font=F["tiny"], text_color=C["muted"],
                             anchor="w").pack(anchor="w", pady=(0, 14))
                row = tk.Frame(body, bg=C["dark"])
                row.pack(fill="x", pady=3)
                ctk.CTkLabel(row, text="PASSPHRASE", font=F["label"],
                             text_color=C["muted"], width=190, anchor="w").pack(
                    side="left")
                self._auth_pass = tk.StringVar()
                ctk.CTkEntry(row, textvariable=self._auth_pass, show="*",
                             width=300, height=38, corner_radius=8,
                             border_width=1, border_color=C["dark3"],
                             fg_color=C["dark2"], text_color=C["cream"],
                             font=F["mono"]).pack(side="right")
            else:
                ctk.CTkLabel(body, text="No passphrase set \u2014 one click "
                                        "entry.",
                             font=F["tiny"], text_color=C["muted"],
                             anchor="w").pack(anchor="w", pady=(0, 14))
            W.Btn(body, "ENTER DASHBOARD", cmd=self._auth_submit, color=C["teal"],
                  width=300, height=42, icon="network-switch-closed").pack(
                pady=(18, 4))
            self._auth_error = ctk.CTkLabel(body, text="", font=F["tiny"],
                                            text_color=C["red"])
            self._auth_error.pack()
        self.bind("<Return>", lambda _e: self._auth_submit())

    def _auth_submit(self):
        if self._auth_frame is None:
            return
        if self._auth_mode == "setup":
            v = self._auth_vars
            missing = [k for k in ("f_user", "f_host", "f_dev_user", "f_dev_pass")
                       if not v[k].get().strip()]
            if missing:
                self._auth_error.configure(
                    text="! fill username, host and device credentials")
                return
            db.save_user(v["f_user"].get().strip(),
                         password_hash="", password_salt="")
            pw = v["f_pass"].get()
            if pw:
                digest, salt = db.hash_password(pw)
                db.save_user(v["f_user"].get().strip(), password_hash=digest,
                             password_salt=salt)
            dev = {
                "name": v["f_dev_name"].get().strip() or "Cat8000",
                "host": v["f_host"].get().strip(),
                "username": v["f_dev_user"].get().strip(),
                "password": v["f_dev_pass"].get(),
                "secret": v["f_secret"].get() or v["f_dev_pass"].get(),
                "https": True, "verify_ssl": False, "restconf_port": 443,
            }
            db.save_device(dev)
            db.log_event("INFO", "AUTH",
                         f"first-run setup completed for "
                         f"{v['f_user'].get().strip()}")
        else:
            if not db.verify_password(db.get_user(), self._auth_pass.get()
                                      if hasattr(self, "_auth_pass") else ""):
                self._auth_error.configure(text="! wrong passphrase")
                return
            db.log_event("INFO", "AUTH", "dashboard unlocked")
        if self._auth_frame is not None:
            self._auth_frame.destroy()
            self._auth_frame = None
        self._boot()

    # ================= trends / analytics =================

    def _refresh_trends(self):
        if not self._trends or not self._trends.get("charts"):
            return
        st = db.stats_overview()
        last = (st.get("last_snapshot") or "NEVER").split(" ")[0]
        self._trends["meta"].configure(
            text=f"{st['snapshots']} SNAPSHOTS // LAST {last}")
        for key, color in (("cpu", C["teal_l"]), ("mem", C["blue"]),
                           ("up", C["green"]), ("errors", C["red"])):
            series = db.series(key)[-14:]
            self._draw_bars(self._trends["charts"][key], series, color)
            latest = series[-1][1] if series else "?"
            self._trends["vals"][key].configure(text=str(latest))
        recent = db.recent_actions(6)
        if recent:
            lines = [f"{a['ts'].split(' ')[1][:5]}  {a['action'].upper():10s}"
                     f"  {a['message'][:44] or a['status']}" for a in recent]
            self._trends["actions"].configure(text="\n".join(lines))

    @staticmethod
    def _draw_bars(canvas, series, color):
        canvas.delete("all")
        if not series:
            return
        w = max(canvas.winfo_width(), 150)
        h = max(canvas.winfo_height(), 64)
        maxv = 1.0
        for _t, v in series:
            try:
                maxv = max(maxv, float(v))
            except (TypeError, ValueError):
                pass
        n = len(series)
        offset = max(0, 14 - n)
        slot = w / 14.0
        bw = max(2.0, slot - 4)
        for idx, (_t, v) in enumerate(series):
            try:
                val = float(v)
            except (TypeError, ValueError):
                val = 0.0
            bh = max(2, int((val / maxv) * (h - 4))) if maxv else 2
            x0 = (offset + idx) * slot + 2
            canvas.create_rectangle(x0, h - bh, x0 + bw, h - 2,
                                    fill=color, outline="")

    def _open_analytics(self):
        win = ctk.CTkToplevel(self)
        win.title("ANALYTICS // DATABASE MEMORY")
        win.geometry("1080x720+100+20")
        win.configure(fg_color=C["dark"])
        win.transient(self)
        win.grab_set()

        head = tk.Frame(win, bg=C["dark"])
        head.pack(fill="x", padx=26, pady=(20, 6))
        W.IconLabel(head, "server-sucess-tick", 34, C["teal_l"]).pack(side="left")
        ctk.CTkLabel(head, text="ANALYTICS // DATABASE MEMORY",
                     font=F["h1"], text_color=C["cream"],
                     anchor="w").pack(side="left", padx=(12, 0))
        ctk.CTkLabel(head, text=f"sqlite // {os.path.join(ENGINE_BASE, 'data', 'CAT8k-SYNC.db')}",
                     font=F["tiny"], text_color=C["muted"],
                     anchor="w").pack(side="left", padx=(14, 0))
        W.Btn(head, "CLOSE", cmd=win.destroy, color=C["red"], width=140,
              height=36, icon="close-cross").pack(side="right")

        st = db.stats_overview()
        chips = tk.Frame(win, bg=C["dark"])
        chips.pack(fill="x", padx=26, pady=(0, 10))
        for text in (
            f"{st['snapshots']} SNAPSHOTS",
            f"FIRST {st['first_snapshot'] or 'NEVER'}",
            f"LAST {st['last_snapshot'] or 'NEVER'}",
            f"{st['audits']} AUDITS",
            f"{st['drifts']} DRIFT CHECKS",
            f"BASELINE {st['baseline_ts'] or 'NONE'}",
            f"LOGIN {st['last_login'] or 'NEVER'}",
        ):
            W.Tag(chips, text, C["dark3"], text_color=C["teal_l"],
                  height=26).pack(side="left", padx=(0, 8))

        charts = tk.Frame(win, bg=C["dark"])
        charts.pack(fill="x", padx=26, pady=(0, 12))
        for i, (label, key, color) in enumerate((
                ("CPU LOAD %", "cpu", C["teal_l"]),
                ("MEMORY %", "mem", C["blue"]),
                ("IFACES UP", "up", C["green"]),
                ("ERROR COUNT", "errors", C["red"]))):
            cell = tk.Frame(charts, bg=C["dark2"], highlightthickness=1,
                            highlightbackground=C["dark3"])
            cell.grid(row=i // 2, column=i % 2, sticky="nsew",
                      padx=6, pady=6)
            ctk.CTkLabel(cell, text=label, font=F["label"],
                         text_color=C["muted"]).pack(padx=10, pady=(8, 2))
            cv = tk.Canvas(cell, width=470, height=96, bg=C["dark2"],
                           highlightthickness=0)
            cv.pack(padx=10, pady=(0, 10))
            self._draw_bars(cv, db.series(key)[-28:], color)

        bottom = tk.Frame(win, bg=C["dark"])
        bottom.pack(fill="both", expand=True, padx=26, pady=(0, 20))
        for col, title, rows in (
            (0, "RECENT ACTIONS // logs", db.recent_actions(20)),
            (1, "EVENT LOG // last 40", db.recent_events(40)),
        ):
            cell = tk.Frame(bottom, bg=C["dark2"], highlightthickness=1,
                            highlightbackground=C["dark3"])
            cell.grid(row=0, column=col, sticky="nsew", padx=6)
            ctk.CTkLabel(cell, text=title, font=F["label"],
                         text_color=C["teal_l"], anchor="w").pack(
                anchor="w", padx=12, pady=(8, 2))
            box = ctk.CTkTextbox(cell, fg_color=C["dark2"], font=F["mono"],
                                 text_color=C["dim"], wrap="none",
                                 height=200)
            box.pack(fill="both", expand=True, padx=12, pady=(2, 12))
            for r in rows:
                kind = r.get("action") or r.get("level") or "?"
                summary = r.get("message") or r.get("status") or ""
                box.insert("end", f"{r['ts']}  {str(kind).upper():8s}"
                                  f"  {str(summary)}\n")
        bottom.grid_columnconfigure(0, weight=1)
        bottom.grid_columnconfigure(1, weight=1)

    # ================= profile modal =================

    def _open_profile(self):
        user = db.get_user() or {}
        dev = db.get_device_plain() or {}
        interval = db.get_setting("auto_interval", "15")

        win = ctk.CTkToplevel(self)
        win.title("PROFILE // IDENTITY & VAULT")
        win.geometry("780x600+260+60")
        win.configure(fg_color=C["dark"])
        win.transient(self)
        win.grab_set()

        head = tk.Frame(win, bg=C["dark"])
        head.pack(fill="x", padx=26, pady=(20, 8))
        W.IconLabel(head, "cartoon-laptop-terminal", 30, C["teal_l"]).pack(side="left")
        ctk.CTkLabel(head, text="PROFILE // IDENTITY & VAULT",
                     font=F["h1"], text_color=C["cream"]).pack(
            side="left", padx=(12, 0))
        W.Btn(head, "CLOSE", cmd=win.destroy, color=C["red"], width=140,
              height=36, icon="close-cross").pack(side="right")

        ctk.CTkLabel(win, text="Changes here rewrite the encrypted SQLite vault "
                               "\u2014 nothing is stored in scripts.",
                     font=F["tiny"], text_color=C["muted"],
                     anchor="w").pack(anchor="w", padx=26, pady=(0, 12))

        body = tk.Frame(win, bg=C["dark"])
        body.pack(fill="x", padx=26)
        body.grid_columnconfigure(1, weight=1)

        self._prof_vars = {}
        fields = [
            ("USERNAME (DASHBOARD)", "user", user.get("username", ""), False),
            ("PASSPHRASE (OPTIONAL)", "pass", "", True),
            ("DEVICE HOST", "host", dev.get("host", ""), False),
            ("DEVICE USERNAME", "dev_user", dev.get("username", ""), False),
            ("DEVICE PASSWORD", "dev_pass", "", True),
            ("ENABLE SECRET", "secret", "", True),
        ]
        for row, (label, key, value, secret) in enumerate(fields):
            ctk.CTkLabel(body, text=label, font=F["label"],
                         text_color=C["muted"], anchor="w").grid(
                row=row, column=0, sticky="w", pady=3)
            var = tk.StringVar(value=value)
            self._prof_vars[key] = var
            entry = ctk.CTkEntry(body, textvariable=var,
                                 show="*" if secret else "",
                                 placeholder_text="leave blank to keep current"
                                 if secret else "",
                                 height=36, corner_radius=8, border_width=1,
                                 border_color=C["dark3"], fg_color=C["dark2"],
                                 text_color=C["cream"], font=F["mono"])
            entry.grid(row=row, column=1, sticky="ew", pady=3)

        row = len(fields)
        ctk.CTkLabel(body, text="AUTO-COLLECT (MIN)", font=F["label"],
                     text_color=C["muted"], anchor="w").grid(
            row=row, column=0, sticky="w", pady=3)
        self._prof_interval = tk.StringVar(value=str(interval))
        spin = tk.Spinbox(body, from_=1, to=120, textvariable=self._prof_interval,
                          width=12, font=F["mono"], bg=C["dark2"],
                          fg=C["cream"], buttonbackground=C["dark3"],
                          relief="flat", highlightthickness=0)
        spin.grid(row=row, column=1, sticky="w", pady=3)
        ctk.CTkLabel(body, text="min (0 disables auto tracking)",
                     font=F["tiny"], text_color=C["muted"]).grid(
            row=row, column=1, sticky="e", padx=(200, 0))

        status = ctk.CTkLabel(win, text="", font=F["tiny"], text_color=C["red"])
        status.pack(anchor="w", padx=26, pady=(8, 0))

        foot = tk.Frame(win, bg=C["dark"])
        foot.pack(fill="x", padx=26, pady=20)
        W.Ghost(foot, "TEST CONNECTION", icon="cloud-server",
                cmd=lambda: self._profile_test(status),
                width=170, height=38).pack(side="left")
        W.Btn(foot, "SAVE PROFILE", cmd=lambda: self._profile_save(status, win),
              color=C["teal"], width=190, height=40,
              icon="server-sucess-tick").pack(side="left", padx=12)
        W.Ghost(foot, "WIPE DATABASE", icon="close-cross",
                cmd=lambda: self._profile_wipe(status),
                width=170, height=38).pack(side="right")

    def _profile_save(self, status, win):
        v = self._prof_vars
        username = v["user"].get().strip()
        if not username:
            status.configure(text="! username required")
            return
        user = db.get_user() or {}
        new_pass = v["pass"].get()
        if new_pass:
            digest, salt = db.hash_password(new_pass)
        else:
            digest, salt = user.get("password_hash", ""), user.get("password_salt", "")
        db.save_user(username, password_hash=digest, password_salt=salt)
        dev = db.get_device_plain() or {}
        dev["host"] = v["host"].get().strip() or dev.get("host", "")
        dev["username"] = v["dev_user"].get().strip() or dev.get("username", "")
        if v["dev_pass"].get():
            dev["password"] = v["dev_pass"].get()
        if v["secret"].get():
            dev["secret"] = v["secret"].get()
        db.save_device(dev)
        try:
            interval = int(self._prof_interval.get())
        except ValueError:
            interval = 15
        db.set_setting("auto_interval", str(max(0, interval)))
        db.set_setting("auto_collect", "1")
        db.log_event("INFO", "PROFILE", "vault credentials updated")
        self.user = db.get_user()
        if self._ticker_id:
            self.after_cancel(self._ticker_id)
            self._ticker_id = None
        self._schedule_ticker()
        try:
            self.engine.reload_devices()
        except Exception as exc:  # noqa: BLE001
            status.configure(text=f"! device reload failed: {exc}")
            return
        status.configure(text_color=C["green"])
        status.configure(text="vault saved + engine reloaded")
        self.toast.show("PROFILE SAVED", C["green"])
        win.after(700, win.destroy)

    def _profile_test(self, status):
        v = self._prof_vars
        dev = db.get_device_plain() or {}
        host = v["host"].get().strip() or dev.get("host", "")
        username = v["dev_user"].get().strip() or dev.get("username", "")
        password = v["dev_pass"].get() or dev.get("password", "")
        if not (host and username and password):
            status.configure(text="! host / username / password required",
                             text_color=C["red"])
            return
        status.configure(text="testing connection\u2026", text_color=C["muted"])
        self.update_idletasks()
        name = self.engine.test_connection(host, username, password)
        if name:
            status.configure(text=f"BACKEND REACHABLE // {name}",
                             text_color=C["green"])
            self.toast.show("BACKEND UP", C["green"])
        else:
            status.configure(text="! device unreachable", text_color=C["red"])

    def _profile_wipe(self, status):
        from tkinter import messagebox
        if not messagebox.askyesno(
                "WIPE DATABASE",
                "Erase the SQLite vault (users, devices, history)?\n"
                "Device credentials fall back to config/devices.yaml."):
            return
        db.wipe_all()
        vault.drop_key()
        self.engine.reload_devices()
        self.user = db.get_user()
        self.toast.show("DATABASE WIPED", C["red"])
        status.configure(text="vault erased \u2014 restart to re-run setup",
                         text_color=C["yellow"])

    # ================= auto-collect ticker =================

    def _schedule_ticker(self):
        try:
            interval = int(db.get_setting("auto_interval", "15"))
        except ValueError:
            interval = 15
        if interval > 0:
            self._ticker_id = self.after(interval * 60000, self._tick)

    def _tick(self):
        self._ticker_id = None
        try:
            enabled = db.get_setting("auto_collect", "1") == "1"
            interval = int(db.get_setting("auto_interval", "15"))
        except ValueError:
            enabled, interval = True, 15
        if enabled and self.backend_up and self._busy_depth == 0:
            self._run_telemetry("SNAPSHOT")
        self._schedule_ticker()

    # ================= menus =================

    def _build_menubar(self):
        menubar = tk.Menu(self)
        m_sys = tk.Menu(menubar, tearoff=0)
        m_sys.add_command(label="Health Check", command=self._manual_health)
        m_sys.add_command(label="Analytics // History", command=self._open_analytics)
        m_sys.add_command(label="Profile", command=self._open_profile)
        m_sys.add_separator()
        m_sys.add_command(label="Toggle Terminal Feed", command=self._flip_console)
        m_sys.add_command(label="Quit", command=self.destroy)
        menubar.add_cascade(label="SYSTEM", menu=m_sys)

        m_nav = tk.Menu(menubar, tearoff=0)
        m_nav.add_command(label="Hub (1)", command=lambda: self._switch("hub"))
        m_nav.add_command(label="Provision (2)", command=lambda: self._switch("provision"))
        m_nav.add_command(label="Telemetry (3)", command=lambda: self._switch("telemetry"))
        m_nav.add_command(label="Audit (4)", command=lambda: self._switch("audit"))
        menubar.add_cascade(label="VIEW", menu=m_nav)

        m_dev = tk.Menu(menubar, tearoff=0)
        m_dev.add_command(label="Ping RESTCONF", command=lambda: self.engine.connect())
        m_dev.add_command(label="Snapshot",
                          command=lambda: self._run_telemetry("SNAPSHOT"))
        m_dev.add_command(label="Collect Running Config",
                          command=lambda: self.engine.collect())
        menubar.add_cascade(label="DEVICE", menu=m_dev)

        m_prov = tk.Menu(menubar, tearoff=0)
        m_prov.add_command(label="Preview Payload", command=self._preview)
        m_prov.add_command(label="Deploy (LIVE)",
                           command=lambda: self._menu_deploy(True))
        m_prov.add_command(label="Deploy (DRY-RUN)",
                           command=lambda: self._menu_deploy(False))
        m_prov.add_command(label="Load YAML -> Form", command=self._load_yaml)
        menubar.add_cascade(label="PROVISION", menu=m_prov)

        m_aud = tk.Menu(menubar, tearoff=0)
        m_aud.add_command(label="Collect + Scan",
                          command=lambda: self.engine.scan(True))
        m_aud.add_command(label="Scan Latest",
                          command=lambda: self.engine.scan(False))
        m_aud.add_command(label="Drift Check", command=lambda: self.engine.drift())
        m_aud.add_command(label="Set Baseline",
                          command=lambda: self.engine.set_baseline())
        menubar.add_cascade(label="AUDIT", menu=m_aud)

        m_help = tk.Menu(menubar, tearoff=0)
        m_help.add_command(label="Help / About",
                           command=lambda: self._show_help("hub"))
        menubar.add_cascade(label="HELP", menu=m_help)

        self.config(menu=menubar)

    # ================= shell =================

    def _build_shell(self):
        self.grid_columnconfigure(0, minsize=NAV["width"])
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.nav = tk.Frame(self, bg=C["dark"], width=NAV["width"])
        self.nav.grid(row=0, column=0, sticky="nsew")
        self.nav.grid_propagate(False)

        self.main = ctk.CTkFrame(self, fg_color=C["bg"], corner_radius=0)
        self.main.grid(row=0, column=1, sticky="nsew")
        self.main.grid_columnconfigure(0, weight=1)
        self.main.grid_rowconfigure(2, weight=1)

    def _build_nav(self):
        logo = tk.Frame(self.nav, bg=C["dark"])
        logo.pack(fill="x", padx=16, pady=(20, 16))

        chip = ctk.CTkFrame(logo, width=46, height=46, corner_radius=12,
                            fg_color=C["teal"])
        chip.pack(side="left")
        chip.pack_propagate(False)
        ctk.CTkLabel(chip, text="Company", font=F["brand"], text_color=C["white"]).pack()
        right = tk.Frame(logo, bg=C["dark"])
        right.pack(side="left", padx=(12, 0))
        ctk.CTkLabel(right, text="AUTO//ENGINE", font=F["brand_sm"],
                     text_color=C["cream"], anchor="w").pack(anchor="w")
        ctk.CTkLabel(right, text="CISCO NETWORK AUTOMATION", font=F["tiny"],
                     text_color=C["muted"], anchor="w").pack(anchor="w", pady=(2, 0))

        tk.Frame(self.nav, bg=C["dark3"], height=1).pack(fill="x", padx=16, pady=(0, 14))

        ctk.CTkLabel(self.nav, text="WORKSPACES", font=F["tiny"],
                     text_color=C["muted"], anchor="w").pack(fill="x", padx=20, pady=(0, 6))

        items = [("HUB", "hub", "cloud-server"),
                 ("PROVISION", "provision", "network-switch-chart-screen"),
                 ("TELEMETRY", "telemetry", "server-sucess-tick"),
                 ("AUDIT", "audit", "router-error-screen")]
        self.nav_imgs = {}
        for text, key, icon_name in items:
            idle_img = IC.ckimg(icon_name, 20, C["muted"])
            active_img = IC.ckimg(icon_name, 20, C["teal_l"])
            self.nav_imgs[key] = (idle_img, active_img)
            btn = ctk.CTkButton(
                self.nav, text=text, command=lambda k=key: self._switch(k),
                height=NAV["item_h"], corner_radius=R["nav"], border_width=0,
                fg_color=C["dark"], hover_color=C["dark2"],
                text_color=C["muted"], font=F["small"], image=idle_img,
                compound="left", anchor="w", border_spacing=18,
            )
            btn.pack(fill="x", padx=12, pady=2)
            self.nav_buttons[key] = btn

        status = tk.Frame(self.nav, bg=C["dark"])
        status.pack(side="bottom", fill="x", padx=14, pady=(8, 16))
        card = ctk.CTkFrame(status, fg_color=C["dark2"], corner_radius=10)
        card.pack(fill="x")
        row = tk.Frame(card, bg=C["dark2"])
        row.pack(fill="x", padx=12, pady=(10, 4))
        self.backend_dot = tk.Label(row, text="  ", bg=C["muted"], font=F["icon"],
                                    width=3, height=1)
        self.backend_dot.pack(side="left")
        head = tk.Frame(row, bg=C["dark2"])
        head.pack(side="left", padx=(6, 0))
        self.backend_nav = ctk.CTkLabel(head, text="BACKEND // OFFLINE",
                                        font=F["small"], text_color=C["muted"])
        self.backend_nav.pack(anchor="w")
        ctk.CTkLabel(card, text=self.engine.device_host(), font=F["tiny"],
                     text_color=C["muted"], anchor="w").pack(anchor="w", padx=12, pady=(2, 4))
        if self.user:
            W.Tag(card, "WELCOME BACK, " + self.user["username"].upper(),
                  C["dark3"], text_color=C["teal_l"], height=24).pack(
                anchor="w", padx=12, pady=(0, 10))
        else:
            ctk.CTkLabel(card, text="F5 INTERNAL CHECK // KEYS 1-4", font=F["tiny"],
                         text_color=C["dim"], anchor="w").pack(anchor="w", padx=12, pady=(0, 10))

    def _build_main(self):
        self.toast = Toast(self.main)

        header = tk.Frame(self.main, bg=C["bg"])
        header.grid(row=0, column=0, sticky="ew", padx=26, pady=(16, 8))
        header.grid_columnconfigure(0, weight=1)

        self.page_title = ctk.CTkLabel(header, text="CONTROL HUB",
                                       font=F["h1"], text_color=C["ink"], anchor="w")
        self.page_title.grid(row=0, column=0, sticky="w")
        self.page_sub = ctk.CTkLabel(header, text="", font=F["small"],
                                     text_color=C["muted"], anchor="w")
        self.page_sub.grid(row=1, column=0, sticky="w", pady=(3, 0))

        chip_right = tk.Frame(header, bg=C["bg"])
        chip_right.grid(row=0, column=1, rowspan=2, sticky="e")
        W.Ghost(chip_right, "PROFILE", icon="cartoon-laptop-terminal",
                cmd=self._open_profile,
                width=108, height=34).pack(side="left", padx=(0, 10))
        W.Ghost(chip_right, "HELP", icon="network-switch-closed",
                cmd=lambda: self._show_help(self.current),
                width=96, height=34).pack(side="left", padx=(0, 10))
        chip_wrap, chip = W.Card(chip_right, shadow=False)
        chip_wrap.pack(side="left")
        ctk.CTkLabel(chip, text="DEVICE // CATALYST 8000", font=F["tiny"],
                     text_color=C["muted"], anchor="w").pack(anchor="w", padx=14, pady=(8, 0))
        ctk.CTkLabel(chip, text=self.engine.device_host(), font=F["h2"],
                     text_color=C["ink"], anchor="w").pack(anchor="w", padx=14, pady=(2, 0))
        ctk.CTkLabel(chip, text="RESTCONF :443 // IOS-XE 17.15", font=F["tiny"],
                     text_color=C["teal"], anchor="w").pack(anchor="w", padx=14, pady=(0, 8))

        status = tk.Frame(self.main, bg=C["bg"])
        status.grid(row=1, column=0, sticky="ew", padx=26, pady=(2, 8))
        status.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(status, text="NODE STATUS", font=F["tiny"],
                     text_color=C["muted"], anchor="w").grid(row=0, column=0, sticky="w")
        self.status_tag = ctk.CTkLabel(
            status, text="CHECKING", font=F["badge"], fg_color=C["muted"],
            text_color=C["white"], width=92, height=28, corner_radius=999)
        self.status_tag.grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.status_dev = ctk.CTkLabel(status, text="DEVICE ?", font=F["small"],
                                       text_color=C["ink"], anchor="w")
        self.status_dev.grid(row=0, column=2, sticky="w", padx=(14, 0))
        self.running_tag = ctk.CTkLabel(status, text="", font=F["small"],
                                        text_color=C["teal"], anchor="w")
        self.running_tag.grid(row=0, column=4, sticky="w", padx=(14, 0))
        self.status_last = ctk.CTkLabel(status, text="LAST CHECK --:--:--",
                                        font=F["small"], text_color=C["muted"], anchor="w")
        self.status_last.grid(row=0, column=5, sticky="e")
        W.Btn(status, "CHECK NOW", cmd=self._manual_health, color=C["teal"],
              width=124, height=34).grid(row=0, column=6, sticky="e", padx=(12, 0))

        self.progress = ctk.CTkProgressBar(status, width=260, height=6,
                                           corner_radius=3, fg_color=C["border"],
                                           progress_color=C["teal"], mode="determinate")
        self.progress.grid(row=1, column=0, columnspan=7, sticky="ew", pady=(8, 0))
        self.progress.set(0)

        self.stack = tk.Frame(self.main, bg=C["bg"])
        self.stack.grid(row=2, column=0, sticky="nsew")
        self.stack.grid_columnconfigure(0, weight=1)
        self.stack.grid_rowconfigure(0, weight=1)

        dock = tk.Frame(self.main, bg=C["bg"])
        dock.grid(row=3, column=0, sticky="ew", padx=26, pady=(6, 12))
        dock.grid_columnconfigure(0, weight=1)

        toggle_bar = tk.Frame(dock, bg=C["dark"], highlightthickness=0)
        toggle_bar.grid(row=0, column=0, sticky="ew")
        note = tk.Frame(toggle_bar, bg=C["dark"])
        note.pack(side="left", padx=14, pady=(7, 5))
        self._console_toggle = ctk.CTkLabel(
            note, text="\u25be TERMINAL FEED", font=F["small"], text_color=C["teal_l"],
            anchor="w", cursor="hand2")
        self._console_toggle.pack(side="left")
        self._console_hint = ctk.CTkLabel(note, text=" click to collapse ", font=F["tiny"],
                                          text_color=C["dim"], anchor="w")
        self._console_hint.pack(side="left", padx=(6, 0))
        self._console_collapsed = False
        self._console_toggle.bind("<Button-1>", lambda _: self._flip_console())
        toggle_bar.bind("<Button-1>", lambda _: self._flip_console())

        self.console = Console(dock, height=5)
        self.console.grid(row=1, column=0, sticky="nsew", pady=(2, 0))

    # ================= views plumbing =================

    def _view_frame(self, key):
        frame = tk.Frame(self.stack, bg=C["bg"])
        frame.place(relwidth=1, relheight=1, x=0, y=0)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)
        self.views[key] = frame
        return frame

    def _view_content(self, key, padx=26, pady=(0, 0)):
        """Scrollable content body for a view frame (never clips)."""
        frame = self.views[key]
        body = ctk.CTkScrollableFrame(
            frame, fg_color=C["bg"], corner_radius=0, scrollbar_button_color=C["border"])
        body.pack(fill="both", expand=True, padx=padx, pady=pady)
        body.grid_columnconfigure(0, weight=1)
        return body

    def _switch(self, key):
        if key not in self.views:
            return
        self.current = key
        frame = self.views[key]
        frame.place(x=0, y=26)
        frame.lift()
        for y in (22, 18, 14, 10, 6, 3, 1, 0):
            self.after(ANIM_MS, lambda yy=y, f=frame: f.place(x=0, y=yy))

        titles = {
            "hub": ("CONTROL HUB", "Choose a workflow \u2014 everything is explained"),
            "provision": ("PROVISION WORKSPACE",
                          "Declare + validate + commit \u2014 YANG over RESTCONF :443"),
            "telemetry": ("TELEMETRY DECK",
                          "Live operational state \u2014 Catalyst 8000 cloud node"),
            "audit": ("SECURITY AUDIT",
                      "Hardening benchmarks + config drift"),
        }
        title, sub = titles[key]
        self.page_title.configure(text=title)
        self.page_sub.configure(text=sub)
        for k, btn in self.nav_buttons.items():
            active = k == key
            idle_img, active_img = self.nav_imgs[k]
            btn.configure(
                fg_color=C["dark2"] if active else C["dark"],
                text_color=C["cream"] if active else C["muted"],
                image=active_img if active else idle_img,
            )

    # ================= HUB view =================

    def _build_hub_view(self):
        self._view_frame("hub")
        body = self._view_content("hub")
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)
        self.hub_cards = []

        # ---- hero card ----
        _wrap, hero = W.Card(body)
        _wrap.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(16, 12))
        hero.grid_columnconfigure(1, weight=1)
        tile = tk.Frame(hero, bg=C["teal_muted"])
        tile.grid(row=0, column=0, rowspan=2, sticky="nsw", padx=18, pady=18)
        W.IconLabel(tile, "cloud-server", 40, C["teal"]).grid(row=0, column=0)
        ctk.CTkLabel(hero, text="AUTOMATE THE CATALYST 8000",
                     font=F["brand"], text_color=C["ink"], anchor="w").grid(
            row=0, column=1, sticky="w", padx=(14, 0), pady=(14, 0))
        ctk.CTkLabel(hero, text="RESTCONF // YANG // IOS-XE 17.15 // CLOUD "
                                "SANDBOX \u2014 every workflow below is two clicks "
                                "away.", font=F["body"], text_color=C["muted"],
                     anchor="w", justify="left").grid(
            row=1, column=1, sticky="w", padx=(14, 0), pady=(2, 16))

        # ---- quick start ----
        _wrap, quick = W.Card(body)
        _wrap.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        bar = tk.Frame(quick, bg=C["card"])
        bar.pack(fill="x", padx=16, pady=16)
        for text, cmd, color, icon_name in (
            ("SNAPSHOT DEVICE", lambda: self._run_telemetry("SNAPSHOT"),
             C["teal"], "server-sucess-tick"),
            ("COLLECT CONFIG", self.engine.collect, C["green"], "cloud-server"),
            ("RUN AUDIT", lambda: self.engine.scan(True), C["red"],
             "router-error-screen"),
            ("HEALTH CHECK", self._manual_health, C["yellow"],
             "network-switch-closed"),
        ):
            W.Btn(bar, text=text, cmd=cmd, color=color, width=180,
                  icon=icon_name).pack(side="left", padx=(0, 12))
        self.action_buttons.extend([
            b for b in bar.winfo_children() if isinstance(b, ctk.CTkButton)])

        # ---- trends card (SQLite memory) ----
        _wrap, trends = W.Card(body)
        _wrap.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 12))
        body.grid_rowconfigure(2, minsize=210)
        inner = tk.Frame(trends, bg=C["card"])
        inner.pack(fill="x", padx=16, pady=14)
        inner.grid_columnconfigure(5, weight=1)

        title = tk.Frame(inner, bg=C["card"])
        title.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 8))
        W.Tag(title, "TRENDS // DATABASE MEMORY", C["teal_l"],
              text_color=C["dark"], height=26).pack(side="left")
        self._trends["meta"] = ctk.CTkLabel(
            title, text="", font=F["tiny"], text_color=C["muted"])
        self._trends["meta"].pack(side="right")

        chart_cells = [
            ("CPU LOAD %", "cpu", C["teal_l"]),
            ("MEMORY %", "mem", C["blue"]),
            ("IFACES UP", "up", C["green"]),
            ("ERRORS", "errors", C["red"]),
        ]
        for col, (label, key, color) in enumerate(chart_cells):
            cell = tk.Frame(inner, bg=C["dark"], highlightthickness=1,
                            highlightbackground=C["dark3"])
            cell.grid(row=1, column=col, padx=(0, 10), pady=(0, 8))
            ctk.CTkLabel(cell, text=label, font=F["label"],
                         text_color=C["muted"]).pack(padx=8, pady=(6, 0))
            cv = tk.Canvas(cell, width=150, height=64, bg=C["dark"],
                           highlightthickness=0)
            cv.pack(padx=8, pady=(2, 0))
            val = ctk.CTkLabel(cell, text="?", font=F["mono"],
                               text_color=color)
            val.pack(padx=8, pady=(0, 6))
            self._trends.setdefault("charts", {})[key] = cv
            self._trends.setdefault("vals", {})[key] = val

        right = tk.Frame(inner, bg=C["card"])
        right.grid(row=0, column=5, rowspan=2, sticky="nsew",
                   padx=(6, 0), pady=(0, 8))
        self._trends["actions"] = ctk.CTkLabel(
            right, text="NO ACTIONS YET", font=F["mono"],
            text_color=C["dim"], anchor="w", justify="left")
        self._trends["actions"].pack(anchor="w", pady=(0, 8))
        W.Btn(right, "OPEN ANALYTICS", cmd=self._open_analytics,
              color=C["teal"], width=180, height=34,
              icon="server-sucess-tick").pack(anchor="w")

        # ---- workflow grid ----
        workflows = [
            ("PROVISION A BRANCH",
             "Create a VLAN subinterface + gateway IP from a declared payload. "
             "Preview the exact JSON before pushing.",
             C["yellow"], "02", self._switch, "provision",
             "network-switch-chart-screen"),
            ("LIVE TELEMETRY",
             "One-click snapshot: CPU, memory, interfaces up/down, ARP "
             "neighbours, BGP families.",
             C["teal"], "03", self._switch, "telemetry",
             "server-sucess-tick"),
            ("SECURITY AUDIT",
             "Hardening benchmark (transport / enable secret / syslog) plus "
             "config drift against your baseline.",
             C["red"], "04", self._switch, "audit",
             "router-error-screen"),
            ("CLEANUP // ROLLBACK",
             "Delete a deployed branch safely \u2014 the exact mirror of "
             "provision.",
             C["green"], "02", self._set_action_delete, None,
             "network-switch-closed"),
        ]
        build_row = {0: (4, 0), 1: (4, 1), 2: (5, 0), 3: (5, 1)}
        body.grid_rowconfigure(4, minsize=188)
        body.grid_rowconfigure(5, minsize=188)
        for i, (title, sub, color, tag, cmd, arg, icon_name) in enumerate(workflows):
            cell = tk.Frame(body, bg=C["bg"])
            cell.grid(row=build_row[i][0], column=build_row[i][1],
                      sticky="nsew", padx=6, pady=6)
            W.HubCard(cell, color, tag, title, sub,
                      lambda c=cmd, a=arg: c(a) if a else c(),
                      icon_name=icon_name).pack(fill="both", expand=True)
            self.hub_cards.append(cell)

    def _set_action_delete(self):
        self.var_action.set("delete_branch")
        self._switch("provision")

    # ================= provision view =================

    def _build_provision_view(self):
        frame = self._view_frame("provision")
        body = tk.Frame(frame, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=26, pady=(16, 22))
        body.grid_columnconfigure(0, weight=3, minsize=520)
        body.grid_columnconfigure(1, weight=2, minsize=360)
        body.grid_rowconfigure(0, weight=1)

        self.var_action = tk.StringVar(value="add_branch")
        self.var_site = tk.StringVar(value="Maroc-Chimie")
        self.var_device = tk.StringVar(value=self.engine.device_names()[0])
        self.var_vlan = tk.StringVar(value="30")
        self.var_vname = tk.StringVar(value="CHIMIE")
        self.var_subnet = tk.StringVar(value="192.168.30.0/24")
        self.var_gw = tk.StringVar(value="192.168.30.1")
        self.var_wan = tk.StringVar(value="10.0.30.2")
        self.var_trunk = tk.StringVar(value="GigabitEthernet1")
        self.var_port = tk.StringVar(value="FastEthernet0/3")
        self.var_pc = tk.StringVar(value="192.168.30.20")
        self.var_dry = tk.BooleanVar(value=True)

        # ---------- left card: 3-step wizard ----------
        _wrap, card = W.Card(body)
        _wrap.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        card.grid_columnconfigure(0, weight=1)

        W.SectionTitle(card, "01", "PROVISION WIZARD",
                       "DECLARE -> VALIDATE -> COMMIT // YANG OVER RESTCONF :443",
                       color=C["teal"]).grid(row=0, column=0, sticky="ew",
                                             padx=20, pady=(16, 6))
        card.grid_rowconfigure(2, weight=1)
        stepper = tk.Frame(card, bg=C["card"])
        stepper.grid(row=1, column=0, sticky="ew", padx=20, pady=(0, 8))
        self._prov_step = 1
        self.step_chips = {}
        for idx, (label) in ((1, "DECLARE"), (2, "VALIDATE"), (3, "COMMIT")):
            chip = W.StepChip(stepper, idx, label,
                              command=lambda i=idx: self._prov_goto(i))
            chip.pack(side="left", padx=(0, 8))
            self.step_chips[idx] = chip
        self.step_host = ctk.CTkScrollableFrame(
            card, fg_color="transparent", corner_radius=0)
        self.step_host.grid(row=2, column=0, sticky="nsew",
                            padx=4, pady=(0, 16))
        self.step_host.grid_columnconfigure(0, weight=1)
        self.step_host.grid_rowconfigure(0, weight=1)

        self.step_pages = {}
        for n in (1, 2, 3):
            page = tk.Frame(self.step_host, bg=C["card"])
            page.grid_columnconfigure(1, weight=1)
            page.grid_columnconfigure(3, weight=1)
            self.step_pages[n] = page
        self._build_wizard_declare()
        self._build_wizard_review()
        self._build_wizard_commit()
        self._goto_step(1)

        # ---------- right card: mission inventory ----------
        _wrap2, card2 = W.Card(body)
        _wrap2.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        W.SectionTitle(card2, "02", "MISSION // INVENTORY",
                       "DECLARATIVE SOURCE OF TRUTH", color=C["teal"]
                       ).grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 6))
        self.inventory_box = tk.Text(
            card2, bg=C["card"], fg=C["ink"], font=F["mono"],
            relief="flat", borderwidth=0, padx=18, pady=6, wrap="word",
            height=20,
        )
        self.inventory_box.grid(row=1, column=0, sticky="nsew", padx=4, pady=(0, 6))
        self.inventory_box.insert("1.0", self._yaml_text())
        self.inventory_box.configure(state="disabled")
        card2.grid_rowconfigure(1, weight=1)

        hint_bar = tk.Frame(card2, bg=C["card"])
        hint_bar.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 16))
        self.action_hint = ctk.CTkLabel(
            hint_bar, font=F["small"], text_color=C["ink"], anchor="w", justify="left",
            text="DEPLOY BRANCH: PREVIEW, THEN PUSH THE PAYLOAD \u2014 WHAT YOU SEE IS WHAT SENDS.",
            wraplength=320)
        self.action_hint.pack(fill="x")

        self.var_action.trace_add("write", lambda *_: self._on_action_change())
        self._on_action_change()

    # ---------- wizard steps (identical logic, re-parented into step_pages)

    def _build_wizard_declare(self):
        page = self.step_pages[1]
        form = tk.Frame(page, bg=C["card"])
        form.grid(row=0, column=0, columnspan=4, sticky="nsew", padx=14)
        form.grid_columnconfigure(1, weight=1)
        form.grid_columnconfigure(3, weight=1)

        _, self.m_action = W.Opt(form, "ACTION", self.var_action,
                                 ["add_branch", "delete_branch", "add_endpoint"],
                                 icon="network-switch-chart-screen")
        self.m_action._wrap.grid(row=0, column=0, sticky="w", padx=(0, 10))
        _, self.m_device = W.Opt(form, "TARGET DEVICE", self.var_device,
                                 self.engine.device_names(),
                                 icon="network-switch-closed")
        self.m_device._wrap.grid(row=0, column=2, sticky="ew", padx=(0, 0))

        _, _f_site = W.Field(form, "SITE NAME", self.var_site,
                             hint="Who owns this VLAN / subinterface",
                             icon="cloud-server")
        _f_site._wrap.grid(row=1, column=0, sticky="w", padx=(0, 10), pady=(10, 0))
        self.entries = {"site_name": _f_site}
        _, e_vlan = W.Field(form, "VLAN ID (2-4094)", self.var_vlan, width=200,
                            hint="Becomes the subinterface number",
                            icon="network-switch-with-cable")
        e_vlan._wrap.grid(row=1, column=2, sticky="ew", pady=(10, 0))
        self.entries["vlan"] = e_vlan
        _, e_vname = W.Field(form, "VLAN NAME", self.var_vname,
                             icon="network-switch-closed")
        e_vname._wrap.grid(row=2, column=0, sticky="w", padx=(0, 10), pady=(10, 0))
        self.entries["vlan_name"] = e_vname
        _, e_gw = W.Field(form, "GATEWAY IP", self.var_gw,
                          hint="Router-side address of this subnet",
                          icon="router-stacked-pile")
        e_gw._wrap.grid(row=2, column=2, sticky="ew", pady=(10, 0))
        self.entries["gateway"] = e_gw

        _, self.f_subnet = W.Field(form, "SUBNET", self.var_subnet,
                                   icon="network-switch-with-cable")
        self.f_subnet._wrap.grid(row=3, column=0, sticky="w", padx=(0, 10), pady=(10, 0))
        self.entries["subnet"] = self.f_subnet
        _, self.f_wan = W.Field(form, "WAN IP (/30)", self.var_wan,
                                icon="router-warning-beside-it")
        self.f_wan._wrap.grid(row=3, column=2, sticky="ew", pady=(10, 0))
        self.entries["wan"] = self.f_wan
        _, self.f_trunk = W.Field(form, "TRUNK PORT", self.var_trunk,
                                  icon="network-switch-with-cable")
        self.f_trunk._wrap.grid(row=4, column=0, sticky="w", padx=(0, 10), pady=(10, 0))
        self.entries["trunk"] = self.f_trunk
        _, self.f_port = W.Field(form, "ACCESS PORT", self.var_port,
                                 icon="switch-device")
        self.f_port._wrap.grid(row=4, column=2, sticky="ew", pady=(10, 0))
        self.entries["port"] = self.f_port
        _, self.f_pc = W.Field(form, "PC IP", self.var_pc,
                               icon="network-switch-closed")
        self.f_pc._wrap.grid(row=5, column=0, sticky="w", padx=(0, 10), pady=(10, 0))
        self.entries["pc"] = self.f_pc

        nav = tk.Frame(page, bg=C["card"])
        nav.grid(row=1, column=0, columnspan=4, sticky="ew", padx=14, pady=(14, 18))
        self.validate_btn = W.Btn(nav, "VALIDATE >>", cmd=lambda: self._prov_goto(2),
                                  color=C["teal"], width=200, primary=True,
                                  icon="network-switch-chart-screen")
        self.validate_btn.pack(side="left")
        W.HintLabel(nav, "Fields validate live; NEXT is gated until the declared "
                         "mission is clean.").pack(side="left", padx=(12, 0))

    def _build_wizard_review(self):
        page = self.step_pages[2]
        host = tk.Frame(page, bg=C["card"])
        host.grid(row=0, column=0, columnspan=4, sticky="nsew", padx=14)
        ctk.CTkLabel(host, text="VALIDATION MATRIX // GREEN = READY TO COMMIT",
                     font=F["h2"], text_color=C["ink"], anchor="w").pack(
            anchor="w", pady=(0, 10))
        self.review_host = tk.Frame(host, bg=C["card"])
        self.review_host.pack(fill="x")
        W.HintLabel(host, "Every declared value is checked before anything "
                          "touches the device.").pack(anchor="w", pady=(8, 0))

        nav = tk.Frame(page, bg=C["card"])
        nav.grid(row=1, column=0, columnspan=4, sticky="ew", padx=14, pady=(14, 18))
        W.Btn(nav, "MODIFY", cmd=lambda: self._goto_step(1), color=C["blue"],
              width=140, icon="network-switch-closed").pack(side="left")
        W.Btn(nav, "PREVIEW PAYLOAD", cmd=self._preview, color=C["blue"],
              width=190, icon="router-stacked-pile").pack(side="left", padx=(10, 0))
        self.commit_btn = W.Btn(nav, "COMMIT >>", cmd=lambda: self._prov_goto(3),
                                color=C["teal"], width=200, primary=True,
                                icon="network-switch-chart-screen")
        self.commit_btn.pack(side="left", padx=(10, 0))
        W.HintLabel(nav, "preview = the exact JSON + URL that RESTCONF will send"
                         ).pack(side="left", padx=(12, 0))

    def _build_wizard_commit(self):
        page = self.step_pages[3]
        ctk.CTkLabel(page, text="PAYLOAD PREVIEW // THE EXACT RESTCONF CALL",
                     font=F["h2"], text_color=C["ink"], anchor="w").grid(
            row=0, column=0, columnspan=4, sticky="w", padx=14, pady=(0, 8))
        self.preview_box = tk.Text(
            page, bg=C["card"], fg=C["ink"], font=F["mono"], relief="flat",
            borderwidth=0, padx=14, pady=10, wrap="none", height=16,
            highlightthickness=1, highlightbackground=C["border"],
        )
        self.preview_box.grid(row=1, column=0, columnspan=4, sticky="nsew",
                              padx=14, pady=(0, 12))
        self.preview_box.tag_config("m", foreground=C["yellow"])

        nav = tk.Frame(page, bg=C["card"])
        nav.grid(row=2, column=0, columnspan=4, sticky="ew", padx=14, pady=(0, 18))
        self.deploy_btn = W.Btn(nav, "> DEPLOY", cmd=self._deploy,
                                color=C["teal"], width=170, primary=True)
        self.deploy_btn.pack(side="left")
        self.action_buttons.append(self.deploy_btn)
        W.Btn(nav, "LOAD YAML", cmd=self._load_yaml, color=C["green"],
              width=130, icon="cloud-server").pack(side="left", padx=(10, 0))
        W.Btn(nav, "BACK", cmd=lambda: self._goto_step(2), color=C["muted"],
              width=110, icon="network-switch-closed").pack(side="left", padx=(10, 0))
        dry = tk.Frame(nav, bg=C["card"])
        dry.pack(fill="x")
        W.Switch(dry, self.var_dry, text="DRY-RUN").pack(side="right")
        ctk.CTkLabel(dry, text="no push", font=F["tiny"],
                     text_color=C["muted"]).pack(side="right", padx=(0, 4))

    def _style_steps(self):
        cur = self._prov_step
        for k, chip in self.step_chips.items():
            on = k <= cur
            chip.configure(
                fg_color=C["teal"] if on else C["paper_tag"],
                text_color=C["white"] if on else C["dim"],
                hover_color=C["teal_h"] if on else C["teal_muted"],
            )

    def _goto_step(self, n):
        self._prov_step = n
        for k, page in self.step_pages.items():
            page.pack_forget()
        self.step_pages[n].pack(fill="both", expand=True)
        self._style_steps()

    def _prov_goto(self, n):
        cur = self._prov_step
        if n <= cur:
            self._goto_step(n)
            return
        try:
            data = self._collect_form()
        except ValueError as e:
            self.toast.show(str(e), C["red"])
            return
        errs = self._field_errors(data)
        for entry in self.entries.values():
            entry.clear_error()
        self._apply_errors(errs)
        if errs:
            self.console.write(f"[FAIL] VALIDATION: {len(errs)} field(s) need fixing.\n")
            self.toast.show("VALIDATION REQUIRED // FIX THE RED FIELDS", C["red"])
            self._goto_step(1)
            return
        self._render_review(data)
        if n == 3:
            self._preview_inline(data)
        self._goto_step(n)

    def _render_review(self, data):
        for w in self.review_host.winfo_children():
            w.destroy()
        action = data["action"]
        rows = [("SITE NAME", data.get("site_name") or "\u2014")]
        vlan = str(data.get("department_vlan") or data.get("vlan_id") or "")
        rows.append(("VLAN ID", vlan or "\u2014"))
        if action == "add_branch":
            rows += [
                ("VLAN NAME", data.get("vlan_name") or "\u2014"),
                ("GATEWAY", data.get("gateway") or "\u2014"),
                ("SUBNET", data.get("department_subnet") or "\u2014"),
                ("WAN IP", data.get("router_wan_ip") or "\u2014"),
                ("TRUNK PORT", data.get("router_trunk_port") or "\u2014"),
            ]
        elif action == "add_endpoint":
            rows += [("ACCESS PORT", data.get("port") or "\u2014"),
                     ("PC IP", data.get("pc_ip") or "\u2014")]
        else:
            rows.append(("DELETE TARGET",
                         f"subinterface for vlan {data.get('vlan_id')}"))
        for name, val in rows:
            W.CheckRow(self.review_host, name, f"declared value: {val}",
                       status="OK", tag="PASS").pack(fill="x", pady=(0, 4))

    def _preview_inline(self, data):
        box = self.preview_box

        def write(text):
            if not box.winfo_exists():
                return
            box.configure(state="normal")
            box.delete("1.0", "end")
            box.insert("1.0", (text or "// preview failed") + "\n")
            box.configure(state="disabled")
            box.see("1.0")

        self._preview_write = write
        write(f"GENERATING RESTCONF CALLS FOR {data['action'].upper()} ...\n"
              f"(discovering interface)\n")
        self.engine.preview(data)

    def _yaml_text(self):
        try:
            with open(os.path.join(BASE, "config", "branches.yaml")) as fh:
                return fh.read()
        except OSError:
            return "config/branches.yaml not found."

    def _on_action_change(self):
        action = self.var_action.get()

        def _show(mapping):
            for f in (self.f_subnet, self.f_wan, self.f_trunk,
                      self.f_port, self.f_pc):
                f._wrap.grid_remove()
            for key in mapping:
                entry = self.entries[key]
                row, col = mapping[key]
                entry._wrap.grid(row=row, column=col,
                                 sticky="ew" if col else "w",
                                 padx=(0, 10) if col == 0 else (0, 0),
                                 pady=(10, 0))
                entry.clear_error()

        if action == "add_branch":
            _show({"subnet": (3, 0), "wan": (3, 2), "trunk": (4, 0)})
            self.deploy_btn.configure(text="> DEPLOY")
            self.action_hint.configure(
                text="DEPLOY BRANCH: mapping for the VLAN " + self.var_vlan.get() +
                     " subinterface + gateway push via RESTCONF PUT.")
        elif action == "delete_branch":
            _show({})
            self.deploy_btn.configure(text="> DELETE BRANCH")
            self.action_hint.configure(
                text="DELETE BRANCH: removes the subinterface for the VLAN ID "
                     "above (RESTCONF DELETE). Instant rollback.")
        else:
            _show({"port": (4, 2), "pc": (5, 0)})
            self.deploy_btn.configure(text="> ADD ENDPOINT")
            self.action_hint.configure(
                text="ADD ENDPOINT targets a switch. Cat8000 is a ROUTER sandbox \u2014 "
                     "payload previews work, live push is limited.")

    def _collect_form(self):
        action = self.var_action.get()
        data = {"action": action, "device": self.var_device.get()}
        if action == "add_branch":
            data.update(site_name=self.var_site.get().strip(),
                        department_vlan=int(self.var_vlan.get()),
                        vlan_name=self.var_vname.get().strip(),
                        department_subnet=self.var_subnet.get().strip(),
                        gateway=self.var_gw.get().strip(),
                        router_wan_ip=self.var_wan.get().strip(),
                        router_trunk_port=self.var_trunk.get().strip())
        elif action == "delete_branch":
            data.update(site_name=self.var_site.get().strip(),
                        vlan_id=int(self.var_vlan.get()))
        else:
            data.update(site_name=self.var_site.get().strip(),
                        vlan_id=int(self.var_vlan.get()),
                        port=self.var_port.get().strip(),
                        pc_ip=self.var_pc.get().strip())
        return data

    def _field_errors(self, data):
        errs = {}
        try:
            vlan = int(data.get("department_vlan") or data.get("vlan_id"))
            if not 2 <= vlan <= 4094:
                errs["vlan"] = "VLAN must be 2-4094"
        except (TypeError, ValueError):
            errs["vlan"] = "VLAN must be a number 2-4094"
        if data.get("action") != "delete_branch" and not VLAN_RE.match(
                data.get("vlan_name", "")):
            errs["vlan_name"] = "a-z 0-9 - _ only, max 32"
        if not data.get("site_name"):
            errs["site_name"] = "Site name is required"
        if data["action"] == "add_branch":
            if not _valid_ip(data.get("gateway", "")):
                errs["gateway"] = "Bad IPv4"
            if not SUBNET_RE.match(data.get("department_subnet", "")):
                errs["subnet"] = "Expect 192.168.30.0/24"
            if not _valid_ip(data.get("router_wan_ip", "")):
                errs["wan"] = "Bad IPv4 (/30)"
        elif data["action"] == "add_endpoint":
            if not _valid_ip(data.get("pc_ip", "")):
                errs["pc"] = "Bad IPv4"
        return errs

    def _apply_errors(self, errs):
        for key, msg in errs.items():
            entry = self.entries.get(key)
            if entry:
                entry.set_error(msg)

    def _deploy(self):
        try:
            data = self._collect_form()
        except ValueError as e:
            self.toast.show(str(e), C["red"])
            return
        errs = self._field_errors(data)
        for entry in self.entries.values():
            entry.clear_error()
        self._apply_errors(errs)
        if errs:
            self.console.write(f"[FAIL] VALIDATION: {len(errs)} field(s) need fixing.\n")
            self.toast.show("FIX THE RED FIELDS", C["red"])
            return
        dry = self.var_dry.get()
        if data["action"] == "delete_branch":
            self.console.write(
                f"[INFO] QUEUE DELETE branch {data['site_name']} (vlan "
                f"{data['vlan_id']})\n")
            self.engine.delete_branch(data)
        else:
            self.console.write(
                f"[INFO] QUEUE {data['action'].upper()} -> {data['site_name']} "
                f"({'DRY-RUN' if dry else 'LIVE'})\n")
            self.engine.provision(data, dry)

    def _menu_deploy(self, live):
        try:
            data = self._collect_form()
        except ValueError as e:
            self.console.write(f"[FAIL] {e}\n")
            return
        errs = self._field_errors(data)
        if errs:
            self.console.write(f"[FAIL] VALIDATION: {list(errs.values())[0]}\n")
            return
        self.engine.provision(data, not live)

    def _preview(self):
        try:
            data = self._collect_form()
        except ValueError as e:
            self.toast.show(str(e), C["red"])
            return
        errs = self._field_errors(data)
        for entry in self.entries.values():
            entry.clear_error()
        self._apply_errors(errs)
        if errs:
            self.toast.show("FIX THE RED FIELDS FIRST", C["red"])
            return
        win, body, _close = W.new_modal(self, "PAYLOAD PREVIEW", 760, 540)
        box = tk.Text(body, bg=C["card"], fg=C["ink"], font=F["mono"],
                      relief="flat", borderwidth=0, padx=14, pady=10,
                      wrap="none", state="disabled")
        box.grid(row=0, column=0, sticky="nsew")
        box.tag_config("m", foreground=C["yellow"])
        box.see("end")

        def write(text):
            if not win.winfo_exists():
                return
            box.configure(state="normal")
            box.delete("1.0", "end")
            box.insert("end", text + "\n")
            box.configure(state="disabled")

        self._preview_write = write
        write(f"GENERATING RESTCONF CALLS FOR {data['action'].upper()} ...\n"
              f"(discovering interface)\n")
        self.engine.preview(data)

        bar = tk.Frame(body, bg=C["bg"])
        bar.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        W.Btn(bar, "COPY", cmd=lambda: self._copy_box(box),
              color=C["green"], width=120, height=36).pack(side="left")
        if data["action"] != "delete_branch":
            W.Btn(bar, "DEPLOY LIVE", cmd=lambda: self.engine.provision(data, False),
                  color=C["yellow"], width=150, height=36).pack(side="left", padx=(10, 0))
        else:
            W.Btn(bar, "DELETE", cmd=lambda: self.engine.delete_branch(data),
                  color=C["red"], width=130, height=36).pack(side="left", padx=(10, 0))
        W.Btn(bar, "CLOSE", cmd=_close, color=C["muted"],
              width=120, height=36).pack(side="right")

    def _copy_box(self, box):
        text = box.get("1.0", "end")
        self.clipboard_clear()
        self.clipboard_append(text)
        self.toast.show("COPIED TO CLIPBOARD", C["green"])

    def _load_yaml(self):
        item = self.engine.load_provisioning_yaml()
        if not item:
            self.console.write("[WARN] branches.yaml has no provisioning actions.\n")
            self.toast.show("NO YAML ACTION", C["red"])
            return
        self.var_action.set(item.get("action", "add_branch"))
        self.var_site.set(item.get("site_name", ""))
        self.var_vlan.set(str(item.get("department_vlan") or item.get("vlan_id") or ""))
        self.var_vname.set(item.get("vlan_name", ""))
        self.var_subnet.set(item.get("department_subnet") or item.get("subnet", ""))
        self.var_gw.set(item.get("gateway", ""))
        self.var_wan.set(item.get("router_wan_ip", ""))
        self.var_trunk.set(item.get("router_trunk_port") or item.get("trunk_port", ""))
        self.var_pc.set(item.get("pc_ip", ""))
        self.console.write("[OK] Inventory loaded into form from branches.yaml.\n")

    # ================= telemetry view =================

    def _build_telemetry_view(self):
        frame = self._view_frame("telemetry")
        body = tk.Frame(frame, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=26, pady=(16, 22))
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(1, weight=1)

        _head, hb = W.Card(body)
        _head.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        bar = tk.Frame(hb, bg=C["card"])
        bar.pack(fill="x", padx=18, pady=14)

        def tele(label):
            self._run_telemetry(label)

        for text, label, color, icon_name in (
            ("SNAPSHOT", "SNAPSHOT", C["teal"], "server-sucess-tick"),
            ("INTERFACES", "interfaces", C["blue"], "network-switch-with-cable"),
            ("ARP TABLE", "arp", C["blue"], "network-switches-stacked-pile"),
            ("OSPF STATE", "ospf", C["blue"], "router-stacked-pile"),
            ("BGP DATA", "bgp", C["blue"], "network-switch-chart-screen"),
            ("FULL COLLECT", "collect", C["green"], "cloud-server"),
        ):
            btn = W.Btn(bar, text, cmd=lambda l=label: tele(l), color=color,
                        width=128, icon=icon_name)
            btn.pack(side="left", padx=(0, 10))
            self.action_buttons.append(btn)

        _body, inner = W.Card(body)
        _body.grid(row=1, column=0, sticky="nsew")
        inner.grid_columnconfigure(0, weight=1)
        inner.grid_rowconfigure(0, weight=1)
        self.telemetry_card_inner = inner
        self.telemetry_box = tk.Text(
            inner, bg=C["card"], fg=C["ink"], font=F["mono"],
            relief="flat", borderwidth=0, padx=14, pady=10, wrap="none",
            state="disabled")
        self.telemetry_box.pack(fill="both", expand=True)
        self._show_telemetry(
            "PRESS SNAPSHOT FOR A LIVE DEVICE HEALTH SUMMARY\n"
            "(CPU / MEMORY / INTERFACES / ARP / BGP).\n\n"
            "INTERFACES TRANSLATES THE YANG JSON INTO A LIVE TOPOLOGY MAP\n"
            "  (PORT LEDS + CLOUD/ROUTER/SWITCH MAP + PER-IFACE STATS).\n\n"
            "OR PICK A RAW OPERATIONAL TREE TO DRILL INTO THE YANG DATA.")

    def _run_telemetry(self, label):
        paths = {
            "interfaces": "Cisco-IOS-XE-interfaces-oper:interfaces",
            "arp": "Cisco-IOS-XE-arp-oper:arp-data",
            "ospf": "Cisco-IOS-XE-ospf-oper:ospf-oper-data",
            "bgp": "Cisco-IOS-XE-bgp-oper:bgp-state-data",
        }
        if label == "SNAPSHOT":
            self.engine.snapshot()
        elif label == "collect":
            self.engine.collect()
        else:
            self.engine.telemetry_raw(paths[label])

    def _show_telemetry(self, text):
        self.telemetry_box.configure(state="normal")
        self.telemetry_box.delete("1.0", "end")
        self.telemetry_box.insert("1.0", text)
        self.telemetry_box.configure(state="disabled")

    # ================= topology layer =================

    def _topology_hostname(self):
        return (self.backend_hostname or self.engine.device_host()
                or "CAT8000").upper()

    def _open_topology(self, ifaces):
        if self.current != "telemetry":
            self._switch("telemetry")
        inner = self.telemetry_card_inner
        if self.topo_panel is None:
            self.telemetry_box.pack_forget()
            self.topo_panel = TopologyPanel(
                inner, hostname=self._topology_hostname(),
                on_refresh=lambda: self._run_telemetry("interfaces"),
                on_raw=self._show_raw_telemetry,
                on_back=self._close_topology,
            )
        self._auto_console = False
        self.topo_panel.place(x=0, y=0, relwidth=1, relheight=1)
        self.topo_panel.set_data(self._topology_hostname(), ifaces)
        if not self._console_collapsed:
            self._collapse_console()
            self._auto_console = True
        self.toast.show("INTERFACES // RENDERED AS TOPOLOGY", C["teal"])

    def _show_raw_telemetry(self):
        self._close_topology()
        self._show_telemetry(self._topo_raw or "// no raw JSON captured")
        self.toast.show("RAW YANG JSON // INTERFACES-OPER", C["blue"])

    def _close_topology(self):
        if self.topo_panel is not None:
            self.topo_panel.destroy()
            self.topo_panel = None
        if self._auto_console:
            self._auto_console = False
            if self._console_collapsed:
                self._flip_console()
        if self.telemetry_card_inner.winfo_ismapped() and \
                not self.telemetry_box.winfo_ismapped():
            self.telemetry_box.pack(fill="both", expand=True)

    # ================= audit view =================

    def _build_audit_view(self):
        frame = self._view_frame("audit")
        body = tk.Frame(frame, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=26, pady=(16, 22))
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(2, weight=1)

        _card, main_card = W.Card(body)
        _card.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        bar = tk.Frame(main_card, bg=C["card"])
        bar.pack(fill="x", padx=18, pady=12)
        scan_btn = W.Btn(bar, "COLLECT + SCAN", cmd=lambda: self.engine.scan(True),
                         color=C["teal"], width=210, primary=True,
                         icon="router-error-screen")
        scan_btn.pack(side="left")
        latest_btn = W.Btn(bar, "SCAN LATEST", cmd=lambda: self.engine.scan(False),
                           color=C["blue"], width=180, icon="network-switch-closed")
        latest_btn.pack(side="left", padx=(10, 0))
        drift_btn = W.Btn(bar, "DRIFT CHECK", cmd=lambda: self.engine.drift(),
                          color=C["green"], width=170,
                          icon="network-switch-sucess-tick-beside")
        drift_btn.pack(side="left", padx=(10, 0))
        base_btn = W.Btn(bar, "SET BASELINE", cmd=lambda: self.engine.set_baseline(),
                         color=C["muted"], width=170, icon="cloud-server")
        base_btn.pack(side="left", padx=(10, 0))
        self.action_buttons.extend([scan_btn, latest_btn, drift_btn, base_btn])

        self.audit_meta = ctk.CTkLabel(body, text="NO SCAN YET \u2014 3 CHECKS: "
                                                  "TELNET, ENABLE SECRET, SYSLOG",
                                       font=F["small"], text_color=C["muted"],
                                       anchor="w")
        self.audit_meta.grid(row=1, column=0, sticky="ew", pady=(0, 6))

        self.audit_scroll = ctk.CTkScrollableFrame(
            body, fg_color=C["card"], corner_radius=10, border_width=1,
            border_color=C["border"],
        )
        self.audit_scroll.grid(row=2, column=0, sticky="nsew", pady=(0, 0))
        self.audit_scroll.grid_columnconfigure(0, weight=1)

    def _render_audit(self, payload):
        for child in self.audit_scroll.winfo_children():
            child.destroy()
        if not payload or not payload.get("results"):
            self.audit_meta.configure(text="NO COLLECTED CONFIG FOUND")
            return
        self.audit_meta.configure(text=f"SOURCE // {payload['filename']}")
        for i, r in enumerate(payload["results"]):
            status = r["status"]
            color = {"PASS": C["green"], "FAIL": C["red"], "WARN": C["yellow"]}.get(
                status, C["muted"])
            icon_status = {"PASS": "OK", "FAIL": "BAD", "WARN": "WARN"}.get(
                status, "IDLE")
            row = W.CheckRow(self.audit_scroll, r["check"], r["detail"],
                             status=icon_status, tag=status)
            row.configure(highlightthickness=1,
                          highlightbackground=C["red"] if status == "FAIL"
                          else C["border"])
            row.grid(row=i, column=0, sticky="ew", pady=(0, 10))

    def _render_drift(self, payload):
        for child in self.audit_scroll.winfo_children():
            child.destroy()
        if not payload:
            self.audit_meta.configure(text="DRIFT CHECK FAILED")
            return
        if payload.get("baseline"):
            self.audit_meta.configure(
                text="BASELINE CAPTURED \u2014 RUN DRIFT CHECK AGAIN AFTER CHANGES")
            row = W.CheckRow(self.audit_scroll, "BASELINE",
                             "NO BASELINE EXISTED \u2014 CREATED FROM LIVE CONFIG",
                             status="OK", tag="PASS")
            row.configure(highlightthickness=1, highlightbackground=C["green"])
            row.grid(row=0, column=0, sticky="ew", pady=(0, 10))
            return
        diff = payload.get("diff") or []
        if not diff:
            self.audit_meta.configure(text="DRIFT // IN SYNC \u2014 LIVE MATCHES BASELINE")
            row = W.CheckRow(self.audit_scroll, "DRIFT STATUS",
                             f"OK +{payload['added']} / -{payload['removed']}",
                             status="OK", tag="SYNC")
            row.configure(highlightthickness=1, highlightbackground=C["green"])
            row.grid(row=0, column=0, sticky="ew", pady=(0, 10))
            return
        self.audit_meta.configure(
            text=f"DRIFT // {payload['added']} LINES ADDED, "
                 f"{payload['removed']} REMOVED (BASELINE vs LIVE)")
        tex = tk.Text(self.audit_scroll, bg=C["dark"], fg=C["cream"], font=F["mono"],
                      relief="flat", borderwidth=0, padx=14, pady=10, wrap="none",
                      height=20)
        tex.grid(row=0, column=0, sticky="ew")
        tex.tag_config("add", foreground=C["green"])
        tex.tag_config("del", foreground=C["red"])
        tex.tag_config("ctx", foreground=C["muted"])
        tex.configure(state="normal")
        for line in diff:
            if line.startswith("+") and not line.startswith("+++"):
                tex.insert("end", line + "\n", "add")
            elif line.startswith("-") and not line.startswith("---"):
                tex.insert("end", line + "\n", "del")
            else:
                tex.insert("end", line + "\n", "ctx")
        tex.configure(state="disabled")

    # ================= task / busy handling =================

    def _on_task_start(self, label):
        if label == "PING":
            return
        self._busy_depth += 1
        self._last_label = label
        self.after(0, self._refresh_busy)

    def _on_task_done(self, label, log_text, result):
        try:
            self.after(0, lambda: self._handle_task(label, log_text, result))
        except (RuntimeError, tk.TclError):
            pass  # app closed while the task thread was finishing

    def _handle_task(self, label, log_text, result):
        if label == "PING":
            self._checking = False
            self._stop_pulse()
            self._set_backend(bool(result), result if result else None)
            if not result and log_text:
                self.console.write(log_text)
            return
        if self._busy_depth > 0:
            self._busy_depth -= 1
        if log_text:
            self.console.write(log_text)
        if label == "CONNECT":
            self._set_backend(bool(result))
            if result:
                self.toast.show("BACKEND UP // RESTCONF OK", C["green"])
            else:
                self.toast.show("BACKEND DOWN", C["red"])
        elif label in ("TELEMETRY", "SNAPSHOT"):
            if label == "SNAPSHOT":
                self._refresh_trends()
            if isinstance(result, str):
                if label == "TELEMETRY":
                    self._topo_raw = result
                    ifaces = parse_interfaces(result)
                    if ifaces:
                        self._open_topology(ifaces)
                        self.toast.show(
                            f"TOPOLOGY // {len(ifaces)} INTERFACES PARSED",
                            C["green"])
                        self.after(0, self._refresh_busy)
                        return
                self._show_telemetry(result)
            self.toast.show("STATE FETCHED", C["green"] if result else C["red"])
        elif label == "AUDIT":
            self._render_audit(result)
            self.toast.show("AUDIT COMPLETE",
                            C["green"] if result and result.get("results") else C["red"])
        elif label == "DRIFT":
            self._render_drift(result)
            self.toast.show("DRIFT COMPARED",
                            C["green"] if result and result.get("diff") else C["blue"])
        elif label == "BASELINE":
            self._render_drift({"baseline": True, "diff": [], "added": 0, "removed": 0})
            self.toast.show("BASELINE CAPTURED", C["green"] if result else C["red"])
        elif label == "PREVIEW":
            write = getattr(self, "_preview_write", None)
            if write:
                write(result or "// preview failed")
            else:
                self.console.write(result or "// preview failed")
        elif label == "PROVISION":
            self.toast.show("DEPLOYED OK" if result else "DEPLOY FAILED",
                            C["green"] if result else C["red"])
        elif label == "DELETE":
            self.toast.show("BRANCH DELETED" if result else "DELETE FAILED",
                            C["green"] if result else C["red"])
        elif label == "COLLECT":
            self.toast.show("COLLECTED TO logs/", C["green"] if result else C["red"])
        self.after(0, self._refresh_busy)

    def _refresh_busy(self):
        if self._busy_depth <= 0:
            self._busy_depth = 0
            self.running_tag.configure(text="")
            if self._progress_id:
                self.after_cancel(self._progress_id)
                self._progress_id = None
            self.progress.set(0)
        else:
            label = self._last_label or ""
            self.running_tag.configure(text=f"RUNNING // {label}")
            if not self._progress_id:
                self._progress_tick(0.0)
        self._apply_action_state()

    def _progress_tick(self, v):
        self.progress.set(v)
        if self._busy_depth > 0:
            nv = v + 0.08 if v < 0.92 else 0.0
            self._progress_id = self.after(60, lambda: self._progress_tick(nv))
        else:
            self._progress_id = None

    def _apply_action_state(self):
        ok = bool(self.backend_up) and self._busy_depth <= 0
        for b in self.action_buttons:
            try:
                b.configure(state="normal" if ok else "disabled")
            except tk.TclError:
                pass

    # ================= backend health + animations =================

    def _schedule_health(self):
        self.after(self.HEALTH_MS, self._schedule_health)
        self._manual_health()

    def _manual_health(self):
        if self._checking:
            return
        self._checking = True
        self.status_tag.configure(text="CHECKING", fg_color=C["muted"])
        self._start_pulse()
        self.engine.ping_backend()

    def _start_pulse(self):
        if self._blink_id:
            self.after_cancel(self._blink_id)
            self._blink_id = None

        def tick(alt):
            if not self._checking:
                self._pulse_id = None
                return
            color = C["yellow"] if alt else C["muted"]
            self.backend_dot.configure(bg=color)
            self.status_tag.configure(fg_color=C["dark"] if alt else C["cream"])
            self._pulse_id = self.after(240, tick, not alt)

        tick(True)

    def _stop_pulse(self):
        if self._pulse_id:
            self.after_cancel(self._pulse_id)
            self._pulse_id = None
        if self._blink_id:
            self.after_cancel(self._blink_id)
            self._blink_id = None

    def _start_blink(self, up):
        self._stop_pulse()
        if up:
            self.backend_dot.configure(bg=C["green"])
            return

        def tick(alt):
            self.backend_dot.configure(bg=C["red"] if alt else "#7A000A")
            self._blink_id = self.after(600, tick, not alt)

        tick(True)

    def _set_backend(self, up, hostname=None):
        changed = self.backend_up != up
        self.backend_up = up
        self.backend_hostname = hostname
        color = C["green"] if up else C["red"]
        self.status_tag.configure(text="ONLINE" if up else "OFFLINE", fg_color=color)
        self.status_dev.configure(
            text=("DEVICE " + hostname) if hostname else "DEVICE UNREACHABLE")
        self.status_last.configure(text="LAST CHECK " + time.strftime("%H:%M:%S"))
        self.backend_nav.configure(
            text="BACKEND // ONLINE" if up else "BACKEND // OFFLINE",
            text_color=C["green"] if up else C["red"])
        self._start_blink(up)
        self._apply_action_state()
        if changed:
            self.toast.show("BACKEND ONLINE" if up else "BACKEND OFFLINE", color)

    # ================= console dock =================

    def _collapse_console(self):
        if not self._console_collapsed:
            self._flip_console()

    def _flip_console(self):
        """Collapse / restore the terminal feed dock row."""
        if self._console_collapsed:
            self.console.grid(row=1, column=0, sticky="nsew", pady=(2, 0))
            self._console_toggle.configure(text="\u25be TERMINAL FEED")
            self._console_hint.configure(text=" click to collapse ")
            self._console_collapsed = False
        else:
            self.console.grid_remove()
            self._console_toggle.configure(text="\u25b8 TERMINAL FEED (hidden)")
            self._console_hint.configure(text=" click to expand ")
            self._console_collapsed = True

    # ================= help =================

    def _show_help(self, which):
        text = HELP_TEXT.get(which, HELP_TEXT["hub"])
        win, body, _close = W.new_modal(self, "HELP // " + which.upper(), 560, 420)
        box = tk.Text(body, bg=C["card"], fg=C["ink"], font=F["mono"],
                      relief="flat", borderwidth=0, padx=18, pady=12, wrap="word")
        box.grid(row=0, column=0, sticky="nsew")
        box.tag_config("head", foreground=C["blue"], font=F["h1"])
        first, rest = text.split("\n", 1)
        box.insert("1.0", first + "\n\n", "head")
        box.insert("end", rest)
        box.configure(state="disabled")


def _valid_ip(s):
    return bool(IPV4_RE.match(s)) and all(0 <= int(p) <= 255 for p in s.split("."))


if __name__ == "__main__":
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")
    app = App()
    app.mainloop()
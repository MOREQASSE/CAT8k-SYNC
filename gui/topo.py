"""TOPOLOGY LAYER: translate the raw YANG interfaces JSON into a live map.

parse_interfaces()  -> flat, typed interface objects from
                       Cisco-IOS-XE-interfaces-oper JSON text.
TopologyPanel       -> ttk-free canvas map: cloud / router / switch / endpoint
                       nodes (tinted svg glyphs from gui/icons), a clickable
                       port list, and a per-interface stats detail panel.
"""
import ipaddress
import json
import tkinter as tk

import customtkinter as ctk
from PIL import ImageTk

from gui import icons
from gui import widgets as W
from gui.theme import C, F

# ---------------------------------------------------------------- parsing

OPER_OK = "if-oper-state-ready"
ADMIN_UP = "if-state-up"


class Iface:
    """One entry of Cisco-IOS-XE-interfaces-oper:interfaces/interface."""

    def __init__(self, **kw):
        self.name = kw.get("name", "")
        self.index = kw.get("index")
        self.admin = kw.get("admin", "")
        self.oper = kw.get("oper", "")
        self.speed = kw.get("speed", 0)
        self.ipv4 = kw.get("ipv4", "") or "0.0.0.0"
        self.mask = kw.get("mask", "")
        self.mac = kw.get("mac", "")
        self.description = kw.get("description", "")
        self.mtu = kw.get("mtu")
        self.vrf = kw.get("vrf", "")
        self.last_change = kw.get("last_change", "")
        self.in_octets = kw.get("in_octets", 0)
        self.out_octets = kw.get("out_octets", 0)
        self.in_pkts = kw.get("in_pkts", 0)
        self.out_pkts = kw.get("out_pkts", 0)
        self.rx_pps = kw.get("rx_pps", 0)
        self.tx_pps = kw.get("tx_pps", 0)
        self.rx_kbps = kw.get("rx_kbps", 0)
        self.tx_kbps = kw.get("tx_kbps", 0)
        self.in_errors = kw.get("in_errors", 0)
        self.out_errors = kw.get("out_errors", 0)
        self.crc_errors = kw.get("crc_errors", 0)
        self.flaps = kw.get("flaps", 0)
        self.in_discards = kw.get("in_discards", 0)
        self.out_discards = kw.get("out_discards", 0)
        self.in_8021q = kw.get("in_8021q", 0)
        self.out_8021q = kw.get("out_8021q", 0)
        self.duplex = kw.get("duplex", "")
        self.neg_speed = kw.get("neg_speed", "")
        self.auto_neg = kw.get("auto_neg")
        self.media = kw.get("media", "")

    @property
    def is_subif(self):
        return "." in self.name

    @property
    def site(self):
        """Branch site guessed from the description ('Maroc-Chimie CHIMIE')."""
        return (self.description or "").split(" ")[0]

    def state(self):
        if self.oper == OPER_OK and self.admin == ADMIN_UP:
            return "OK"
        if self.admin != ADMIN_UP:
            return "BAD"
        if self.oper in ("if-oper-state-dormant", "if-oper-state-present",
                         "if-oper-state-unknown", ""):
            return "WARN"
        return "BAD"

    def speed_label(self):
        try:
            v = int(self.speed)
        except (TypeError, ValueError):
            return self.speed or "?"
        if v >= 10**9:
            return f"{v // 10**9} Gbps"
        if v >= 10**6:
            return f"{v // 10**6} Mbps"
        return f"{v} bps"

    def subnet(self):
        try:
            net = ipaddress.IPv4Network(f"{self.ipv4}/{self.mask}",
                                        strict=False)
            return str(net)
        except (ValueError, TypeError):
            return ""

    def vlan(self):
        return self.name.split(".")[-1] if self.is_subif else ""


def _num(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def parse_interfaces(text):
    """Raw JSON string -> list[Iface]; None if it does not look like the
    interfaces operational tree."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return None
    root = (data.get("Cisco-IOS-XE-interfaces-oper:interfaces")
            or data.get("interfaces") or data)
    if not isinstance(root, dict):
        return None
    items = root.get("interface")
    if not isinstance(items, list) or not items:
        return None
    out = []
    for it in items:
        if not isinstance(it, dict):
            continue
        stats = it.get("statistics") or {}
        ether = it.get("ether-state") or {}
        es = it.get("ether-stats") or {}
        out.append(Iface(
            name=it.get("name", ""),
            index=it.get("if-index"),
            admin=it.get("admin-status", ""),
            oper=it.get("oper-status", ""),
            speed=it.get("speed", 0),
            ipv4=it.get("ipv4", ""),
            mask=it.get("ipv4-subnet-mask", ""),
            mac=it.get("phys-address", ""),
            description=it.get("description", ""),
            mtu=it.get("mtu"),
            vrf=it.get("vrf", ""),
            last_change=it.get("last-change", ""),
            in_octets=_num(stats.get("in-octets")),
            out_octets=_num(stats.get("out-octets")),
            in_pkts=_num(stats.get("in-unicast-pkts")),
            out_pkts=_num(stats.get("out-unicast-pkts")),
            rx_pps=_num(stats.get("rx-pps")),
            tx_pps=_num(stats.get("tx-pps")),
            rx_kbps=_num(stats.get("rx-kbps")),
            tx_kbps=_num(stats.get("tx-kbps")),
            in_errors=_num(stats.get("in-errors")),
            out_errors=_num(stats.get("out-errors")),
            crc_errors=_num(stats.get("in-crc-errors")),
            flaps=_num(stats.get("num-flaps")),
            in_discards=_num(stats.get("in-discards")),
            out_discards=_num(stats.get("out-discards")),
            in_8021q=_num(es.get("in-8021q-frames")),
            out_8021q=_num(es.get("out-8021q-frames")),
            duplex=ether.get("negotiated-duplex-mode", ""),
            neg_speed=ether.get("negotiated-port-speed", ""),
            auto_neg=ether.get("auto-negotiate"),
            media=ether.get("media-type", ""),
        ))
    return out or None


def _human_bytes(v):
    try:
        v = int(v)
    except (TypeError, ValueError):
        return "0"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if v < 1024 or unit == "TB":
            return f"{v:.0f} {unit}" if unit == "B" else f"{v:.1f} {unit}"
        v /= 1024
    return f"{v:.1f} TB"


STATE_STYLE = {
    "OK":   ("UP", C["green"], "server-sucess-tick"),
    "BAD":  ("DOWN", C["red"], "server-error-cross"),
    "WARN": ("DEGRADED", C["yellow"], "router-warning-beside-it"),
}

# ---------------------------------------------------------------- panel

_GRID_W = 1500          # full pannable grid (scrollbars reveal it)
_GRID_H = 900
_LIGHT = "#F8FAFC"      # light text on the dark grid
_LIGHT_DIM = "#8FA3B8"  # secondary light text on the dark grid
_DOT = "#26303F"

# role -> icon file (names map to gui/icons/*.svg verbatim)
NODE_ICONS = {
    "cloud":       "cloud-server",                  # the only cloud glyph
    "router":      "router-stacked-pile",           # plain stacked router
    "access_sw":   "access-switch-cable",           # access + cable glyph
    "switch":      "network-switch-closed",         # closed network switch
    "endpoint":    "isometric-desktop-computer",    # branch site client
}


class GridCanvas(tk.Frame):
    """Dark pannable grid with icon + text nodes, scrollbars and wheel pan.

    Used docked (inside TopologyPanel) and standalone in the expanded
    overlay; both render the same data through set_data().
    """

    def __init__(self, master, hostname="CAT8000", ifaces=()):
        super().__init__(master, bg=C["bg"])
        self.hostname = hostname
        self.ifaces = list(ifaces)
        self._imgs = []
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(
            self, bg=C["dark"], highlightthickness=3,
            highlightbackground=C["border"])
        self.canvas.grid(row=0, column=0, sticky="nsew")
        ysc = tk.Scrollbar(self, command=self.canvas.yview, bg=C["dark"],
                           troughcolor=C["dark"], bd=0,
                           highlightthickness=0, activebackground=C["dim"])
        ysc.grid(row=0, column=1, sticky="ns")
        xsc = tk.Scrollbar(self, orient="horizontal",
                           command=self.canvas.xview, bg=C["dark"],
                           troughcolor=C["dark"], bd=0,
                           highlightthickness=0, activebackground=C["dim"])
        xsc.grid(row=1, column=0, sticky="ew")
        self.canvas.configure(yscrollcommand=ysc.set,
                              xscrollcommand=xsc.set)
        self.canvas.bind("<Configure>", lambda _e: self._redraw_map())
        self.canvas.bind("<MouseWheel>",
                         lambda e: self.canvas.yview_scroll(
                             -1 if e.delta > 0 else 1, "units"))
        self.canvas.bind("<Shift-MouseWheel>",
                         lambda e: self.canvas.xview_scroll(
                             -1 if e.delta > 0 else 1, "units"))
        self._redraw_map()

    def set_data(self, hostname, ifaces):
        self.hostname = hostname or self.hostname
        self.ifaces = list(ifaces)
        self._redraw_map()

    def _redraw_map(self):
        c = self.canvas
        c.delete("all")
        self._imgs.clear()
        c.configure(scrollregion=(0, 0, _GRID_W, _GRID_H))
        for x in range(18, _GRID_W, 26):
            for y in range(18, _GRID_H, 26):
                c.create_rectangle(x, y, x + 2, y + 2, outline="", fill=_DOT)

        trunk = [i for i in self.ifaces if i.is_subif]
        trunk_line = None
        if trunk:
            t = trunk[0]
            state = t.state()
            color = STATE_STYLE[state][1]
            trunk_line = (t, color)
        cloud = (10, 6)
        router = (115, 90)
        switch = (265, 190)
        endpoint = (380, 290)

        c.create_line(56, 29, 115, 122, fill=C["teal_l"], width=3)
        if trunk_line:
            t, color = trunk_line
            c.create_line(179, 122, 265, 213, fill=color, width=3)
            c.create_line(311, 213, 380, 313, fill=C["muted"], width=2,
                          dash=(4, 4))
            c.create_text(245, 206, anchor="e",
                          text=f"TRUNK // {t.name} // VLAN {t.vlan()}",
                          fill=C["yellow"], font=F["tiny"])

        self._node(c, cloud[0], cloud[1], "cloud", "INTERNET // WLAN",
                   "CLOUD SANDBOX", C["blue"])
        self._node(c, router[0], router[1], "router", self.hostname,
                   "IOS-XE 17.15 // RESTCONF :443", C["teal"], big=True)
        if trunk:
            self._node(c, switch[0], switch[1], "access_sw",
                       "ACCESS SWITCH", f"BRANCH // {trunk[0].site}",
                       C["teal"])
            self._node(c, endpoint[0], endpoint[1], "endpoint",
                       "ENDPOINT", trunk[0].subnet() or "SUBNET ?",
                       C["green"])

    def _node(self, c, x, y, role, title, sub, color, big=False):
        size = 64 if big else 46
        img = ImageTk.PhotoImage(icons.render(NODE_ICONS[role], size, color))
        self._imgs.append(img)
        c.create_image(x, y, image=img, anchor="nw")
        cx = x + size // 2
        c.create_text(cx, y + size + 8, text=title.upper(), fill=_LIGHT,
                      font=F["small"], anchor="n")
        c.create_text(cx, y + size + 27, text=sub, fill=_LIGHT_DIM,
                      font=F["tiny"], anchor="n")


class TopologyPanel(tk.Frame):
    """Live interface topology: port list + pannable canvas map + inspector.

    Callbacks: on_refresh() re-fetches interfaces; on_raw() shows the raw
    JSON; on_back() returns to the telemetry deck.
    """

    def __init__(self, master, hostname="CAT8000", on_refresh=None,
                 on_raw=None, on_back=None):
        super().__init__(master, bg=C["bg"])
        self.hostname = hostname
        self.ifaces = []
        self._sel = None
        self._port_rows = []
        self._port_leds = {}
        self._imgs = []

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        bar = tk.Frame(self, bg=C["card"])
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        bar.grid_columnconfigure(0, weight=1)
        left = tk.Frame(bar, bg=C["card"])
        left.grid(row=0, column=0, sticky="w")
        W.IconLabel(left, "network-switch-with-cable", 26,
                    C["teal"]).pack(side="left", padx=(0, 10))
        self.meta = ctk.CTkLabel(left, text="0 INTERFACES", font=F["h2"],
                                 text_color=C["ink"], anchor="w")
        self.meta.pack(side="left")
        ctk.CTkLabel(left, text="  //  click a port to inspect",
                     font=F["small"], text_color=C["muted"]).pack(side="left")
        W.Btn(bar, "RAW JSON", cmd=on_raw, color=C["blue"], width=120,
              height=34, icon="network-switch-chart-screen").grid(
            row=0, column=1, sticky="e", padx=(10, 0))
        W.Btn(bar, "REFRESH", cmd=on_refresh, color=C["teal"], width=130,
              height=34, icon="server-sucess-tick").grid(
            row=0, column=2, sticky="e", padx=(8, 0))
        W.Btn(bar, "< TELEMETRY", cmd=on_back, color=C["muted"], width=140,
              height=34, icon="network-switch-closed").grid(
            row=0, column=3, sticky="e", padx=(8, 0))
        W.Btn(bar, "EXPAND", cmd=self._expand_grid, color=C["dark"],
              width=140, height=38, icon="expand-arrows",
              icon_color=C["cream"]).grid(
            row=0, column=4, sticky="e", padx=(8, 0))

        body = tk.Frame(self, bg=C["bg"])
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(1, weight=1)

        self.ports_host = ctk.CTkScrollableFrame(
            body, fg_color=C["bg"], width=212, corner_radius=0,
            scrollbar_button_color=C["border"],
            scrollbar_button_hover_color=C["muted"])
        self.ports_host.grid(row=0, column=0, sticky="ns", padx=(0, 10))

        self.map_canvas = GridCanvas(body)
        self.map_canvas.grid(row=0, column=1, sticky="nsew")
        self.canvas = self.map_canvas.canvas

        self.detail_host = ctk.CTkScrollableFrame(
            body, fg_color=C["bg"], width=268, corner_radius=0,
            scrollbar_button_color=C["border"],
            scrollbar_button_hover_color=C["muted"])
        self.detail_host.grid(row=0, column=2, sticky="ns", padx=(10, 0))
        self._detail_content = tk.Frame(self.detail_host, bg=C["bg"])
        self._detail_content.pack(fill="both", expand=True)

        self._empty_detail()

    # ---------------- data ----------------

    def set_data(self, hostname, ifaces):
        self.hostname = hostname or self.hostname
        self.ifaces = list(ifaces)
        self.map_canvas.set_data(self.hostname, self.ifaces)
        self._rebuild_ports()
        self._select(self.ifaces[0] if self.ifaces else None)
        up = sum(1 for i in self.ifaces if i.state() == "OK")
        down = sum(1 for i in self.ifaces if i.state() == "BAD")
        total = len(self.ifaces)
        self.meta.configure(text=f"{total} INTERFACES  //  {up} UP  //  {down} DOWN")

    # ---------------- expanded overlay ----------------

    def _expand_grid(self):
        """Big overlay window with the full pannable grid + red close."""
        win = tk.Toplevel(self)
        win.title("Company // EXPANDED TOPOLOGY GRID")
        win.configure(bg=C["dark"])
        win.geometry("1440x880+40+30")
        win.attributes("-topmost", True)
        self._expanded = win

        head = tk.Frame(win, bg=C["dark"])
        head.pack(fill="x", padx=18, pady=(14, 10))
        W.IconLabel(head, "expand-arrows", 24, C["teal_l"]).pack(
            side="left", padx=(0, 10))
        ctk.CTkLabel(head, text="EXPANDED TOPOLOGY GRID", font=F["h1"],
                     text_color=C["cream"]).pack(side="left")
        W.Btn(head, "CLOSE", cmd=win.destroy, color=C["red"], width=150,
              height=40, icon="close-cross").pack(side="right")

        body = tk.Frame(win, bg=C["dark"])
        body.pack(fill="both", expand=True, padx=18, pady=(0, 18))
        grid = GridCanvas(body, hostname=self.hostname, ifaces=self.ifaces)
        grid.pack(fill="both", expand=True)
        win.protocol("WM_DELETE_WINDOW", win.destroy)

    def _rebuild_ports(self):
        for row in self._port_rows:
            row.destroy()
        self._port_rows = []
        self._port_leds = {}
        for ifc in self.ifaces:
            row = tk.Frame(self.ports_host, bg=C["card"],
                           highlightthickness=3, highlightbackground=C["border"])
            row.pack(fill="x", pady=(0, 8))
            row.grid_columnconfigure(1, weight=1)
            state = ifc.state()
            _, color, _icon = STATE_STYLE[state]
            led = tk.Frame(row, bg=color, width=16, height=16)
            led.grid(row=0, column=0, rowspan=2, padx=(10, 8), pady=10)
            ctk.CTkLabel(row, text=ifc.name, font=F["h2"], text_color=C["ink"],
                         anchor="w").grid(row=0, column=1, sticky="w",
                                          pady=(8, 0), padx=(0, 10))
            ctk.CTkLabel(row, text=(ifc.ipv4 + "  //  " + ifc.speed_label()),
                         font=F["tiny"], text_color=C["muted"], anchor="w").grid(
                row=1, column=1, sticky="w", pady=(0, 8), padx=(0, 10))
            self._port_leds[ifc.name] = led

            def pick(_e, i=ifc):
                self._select(i)

            def bind_all(w, fn):
                w.bind("<Button-1>", fn)
                for ch in w.winfo_children():
                    bind_all(ch, fn)

            bind_all(row, pick)
            row.configure(cursor="hand2")
            self._port_rows.append(row)

    # ---------------- detail ----------------

    def _empty_detail(self):
        for w in self._detail_content.winfo_children():
            w.destroy()
        ctk.CTkLabel(self._detail_content, text="NO INTERFACE SELECTED",
                     font=F["h2"], text_color=C["muted"]).pack(pady=60)

    def _select(self, ifc):
        self._sel = ifc
        for name, led in self._port_leds.items():
            base = C["green"] if next(
                (i.state() for i in self.ifaces if i.name == name), "OK") == "OK" \
                else C["red"]
            row = led.master
            row.configure(highlightbackground=C["teal"] if name == ifc.name
                          else C["border"])
        if ifc is None:
            self._empty_detail()
            return
        self._build_detail(ifc)

    def _build_detail(self, ifc):
        for w in self._detail_content.winfo_children():
            w.destroy()
        host = tk.Frame(self._detail_content, bg=C["card"],
                        highlightthickness=3, highlightbackground=C["border"])
        host.pack(fill="x")
        state = ifc.state()
        label, color, icon_name = STATE_STYLE[state]

        head = tk.Frame(host, bg=C["card"])
        head.pack(fill="x", padx=14, pady=(12, 6))
        W.IconLabel(head, icon_name, 30, color).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(head, text=ifc.name.upper(), font=F["h2"],
                     text_color=C["ink"]).pack(side="left")
        W.Tag(head, label, color, width=74).pack(side="right")

        def row(label_text, value, col_color=C["ink"]):
            r = tk.Frame(host, bg=C["card"])
            r.pack(fill="x", padx=14)
            ctk.CTkLabel(r, text=label_text, font=F["tiny"],
                         text_color=C["muted"], width=84, anchor="w").pack(
                side="left")
            ctk.CTkLabel(r, text=value or "\u2014", font=F["mono"],
                         text_color=col_color, anchor="w").pack(
                side="left", fill="x", expand=True)

        row("IPv4", ifc.ipv4 + ("/" + ifc.mask if ifc.mask else ""))
        row("MAC", ifc.mac)
        row("SPEED", ifc.speed_label())
        row("NEGOTIATED", ifc.neg_speed or "\u2014")
        row("DUPLEX", (ifc.duplex or "\u2014").replace("-", " "))
        row("AUTO-NEG", str(bool(ifc.auto_neg)).upper() if ifc.auto_neg is not None else "\u2014")
        row("MTU", str(ifc.mtu) if ifc.mtu else "\u2014")
        row("VRF", ifc.vrf or "GLOBAL")
        if ifc.description:
            row("DESCRIPTION", ifc.description)
        row("LAST CHANGE", ifc.last_change.replace("T", " ").replace("+00:00", " Z")
            if ifc.last_change else "\u2014")

        tk.Frame(host, bg=C["border"], height=3).pack(fill="x", pady=(12, 8))

        def cell(label_text, value, bad=False):
            c = tk.Frame(host, bg=C["card"])
            c.pack(fill="x", padx=14, pady=2)
            ctk.CTkLabel(c, text=label_text, font=F["tiny"],
                         text_color=C["muted"], width=84, anchor="w").pack(
                side="left")
            ctk.CTkLabel(c, text=value, font=F["h2"],
                         text_color=C["red"] if bad else C["ink"],
                         anchor="w").pack(side="left", fill="x", expand=True)

        cell("RX KBPS", str(ifc.rx_kbps))
        cell("TX KBPS", str(ifc.tx_kbps))
        cell("RX PPS", str(ifc.rx_pps))
        cell("TX PPS", str(ifc.tx_pps))
        cell("IN OCTETS", _human_bytes(ifc.in_octets))
        cell("OUT OCTETS", _human_bytes(ifc.out_octets))
        cell("IN ERRORS", str(ifc.in_errors), bad=ifc.in_errors > 0)
        cell("OUT ERRORS", str(ifc.out_errors), bad=ifc.out_errors > 0)
        cell("CRC ERRORS", str(ifc.crc_errors), bad=ifc.crc_errors > 0)
        cell("FLAPS", str(ifc.flaps), bad=ifc.flaps > 0)
        cell("IN 802.1Q", str(ifc.in_8021q))
        cell("OUT 802.1Q", str(ifc.out_8021q))
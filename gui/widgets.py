"""Soft SaaS widget factories (CustomTkinter, rounded surfaces, hairline
borders, subtle shadows).

Every primitive returns a widget already styled to the modern light tokens.
Hover states, focus tints, runtime-tinted icon library (gui/icons) for
glyphs.  API is identical to the old brutalist set so call sites keep
working unchanged.
"""
import tkinter as tk

import customtkinter as ctk

from gui import icons
from gui.theme import C, F, R

STATE_ICONS = {
    "OK":    ("server-sucess-tick", C["green"]),
    "GOOD":  ("router-sucess-tick-beside-it", C["green"]),
    "BAD":   ("server-error-cross", C["red"]),
    "WARN":  ("router-warning-beside-it", C["yellow"]),
    "IDLE":  ("network-switch-closed", C["muted"]),
    "META":  ("cloud-server", C["teal"]),
}

_LIGHT_FILLS = {"transparent", "transparentlight"}


def _mix(hex_a, hex_b, t):
    a = tuple(int(hex_a[i:i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(hex_b[i:i + 2], 16) for i in (1, 3, 5))
    return "#{:02x}{:02x}{:02x}".format(*(round(a[i] + (b[i] - a[i]) * t) for i in range(3)))


def hover(color):
    return _mix(color, "#000000", 0.12)


def pressed(color):
    return _mix(color, "#000000", 0.25)


def on_color(color):
    """Readable text color for a button/chip fill."""
    if color in _LIGHT_FILLS or color in (C["paper_tag"], C["cream"],
                                          C["teal_muted"], C["yellow_soft"],
                                          C["red_soft"], C["green_soft"],
                                          C["blue_soft"]):
        return C["ink"]
    return C["white"]


def _bind_hover_lift(widget, lift_px=3):
    """Compatibility hook: soft hover lift (shadow grows on enter)."""
    original_y = widget.winfo_y()

    def _on_enter(_e):
        widget.place(y=original_y - lift_px)

    def _on_leave(_e):
        widget.place(y=original_y)

    widget.bind("<Enter>", _on_enter)
    widget.bind("<Leave>", _on_leave)


def IconLabel(master, name, size=24, color=None):
    """Square canvas stamp of a tinted svg glyph."""
    color = color or C["teal"]
    return ctk.CTkLabel(
        master, text="", image=icons.ckimg(name, size, color),
        width=size + 8, height=size + 4,
    )


def Btn(master, text, cmd=None, color=None, width=None, height=40,
        font=None, outline=True, primary=False, icon=None,
        icon_color=None, compound="left"):
    color = color or C["teal"]
    img = None
    if icon:
        img = icons.ckimg(icon, int(height * 0.48), icon_color or on_color(color))
    return ctk.CTkButton(
        master, text=text, command=cmd,
        width=width, height=height,
        corner_radius=R["btn"],
        border_width=1,
        border_color=_mix(color, "#000000", 0.18),
        fg_color=color,
        hover_color=hover(color),
        text_color=on_color(color),
        font=font or F["btn"],
        anchor="center", image=img, compound=compound,
    )


def Ghost(master, text, cmd=None, width=None, height=40, icon=None):
    """Soft outline button for secondary actions on light surfaces."""
    img = None
    if icon:
        img = icons.ckimg(icon, int(height * 0.46), C["muted"])
    return ctk.CTkButton(
        master, text=text, command=cmd,
        width=width, height=height,
        corner_radius=R["btn"], border_width=1, border_color=C["border"],
        fg_color=C["card"], hover_color=C["paper_tag"],
        text_color=C["dim"], font=F["btn"], anchor="center",
        image=img, compound="left",
    )


def Label(master, text, font=None, color=None, anchor="w", justify=None):
    return ctk.CTkLabel(
        master, text=text, font=font or F["body"],
        text_color=color or C["ink"], anchor=anchor, justify=justify,
    )


def Tag(master, text, color, text_color=None, font=None, width=None, height=26):
    """Rounded status pill / counter (width=None -> auto-size to text)."""
    return ctk.CTkLabel(
        master, text=text, font=font or F["badge"],
        text_color=text_color or on_color(color),
        width=0 if width is None else width, height=height,
        corner_radius=R["pill"], fg_color=color,
        anchor="center",
    )


def HintLabel(master, text):
    """Small muted explanatory text below a section."""
    return ctk.CTkLabel(
        master, text=text, font=F["tiny"], text_color=C["muted"],
        anchor="w", justify="left",
    )


def Field(master, label_text, variable, width=210, height=42, placeholder="",
          font=None, hint=None, icon=None, icon_color=None):
    """Labeled text input with leading icon chip, focus tint and inline
    error slot.

    Returns (container, entry). The entry gains two helpers:
      entry.set_error(msg) / entry.clear_error()
    """
    wrap = ctk.CTkFrame(master, fg_color="transparent")
    wrap.grid_columnconfigure(1, weight=1)
    ctk.CTkLabel(
        wrap, text=label_text.upper(), font=F["label"],
        text_color=C["muted"], anchor="w",
    ).grid(row=0, column=0, columnspan=2, sticky="w")

    icon_chip = None
    ecol = 0
    if icon:
        icon_chip = IconLabel(wrap, icon, 20, icon_color or C["teal"])
        icon_chip.grid(row=1, column=0, sticky="w", padx=(0, 6))
        ecol = 1
    entry = ctk.CTkEntry(
        wrap, textvariable=variable, placeholder_text=placeholder,
        width=width, height=height,
        corner_radius=R["field"], border_width=1, border_color=C["border"],
        fg_color=C["card"], text_color=C["ink"],
        font=font or F["mono"],
    )
    entry.grid(row=1, column=ecol, sticky="ew", pady=(4, 4))
    err = ctk.CTkLabel(wrap, text="", font=F["tiny"], text_color=C["red"],
                       anchor="w", height=12)
    err.grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 2))

    def set_error(msg):
        if msg:
            err.configure(text=f"! {msg}")
            entry.configure(border_color=C["red"])
            if icon_chip:
                icon_chip.configure(image=icons.ckimg(
                    STATE_ICONS["BAD"][0], 20, C["red"]))
        else:
            err.configure(text="")
            entry.configure(border_color=C["border"])
            if icon_chip and icon:
                icon_chip.configure(image=icons.ckimg(
                    icon, 20, icon_color or C["teal"]))

    entry.set_error = set_error
    entry.clear_error = lambda: set_error(None)
    entry._wrap = wrap

    row = 3
    if hint:
        ctk.CTkLabel(
            wrap, text=hint, font=F["tiny"], text_color=C["muted"], anchor="w",
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(1, 0))
        row += 1
    return wrap, entry


def Opt(master, label_text, variable, values, width=214, height=42,
        icon=None):
    wrap = ctk.CTkFrame(master, fg_color="transparent")
    wrap.grid_columnconfigure(1, weight=1)
    ctk.CTkLabel(
        wrap, text=label_text.upper(), font=F["label"],
        text_color=C["muted"], anchor="w",
    ).grid(row=0, column=0, columnspan=2, sticky="w")
    if icon:
        IconLabel(wrap, icon, 20, C["teal"]).grid(row=1, column=0, sticky="w",
                                                  padx=(0, 6))
    menu = ctk.CTkOptionMenu(
        wrap, variable=variable, values=values,
        width=width, height=height,
        corner_radius=R["field"],
        fg_color=C["card"], button_color=C["border"],
        button_hover_color=C["paper_tag"],
        dropdown_fg_color=C["card"], dropdown_hover_color=C["teal_muted"],
        dropdown_text_color=C["ink"], text_color=C["ink"], font=F["small"],
        anchor="center",
    )
    menu.grid(row=1, column=1, sticky="ew", pady=(4, 0))
    menu._wrap = wrap
    return wrap, menu


def Switch(master, variable, text="", color=None):
    color = color or C["green"]
    return ctk.CTkSwitch(
        master, variable=variable, text=text,
        width=52, height=24,
        corner_radius=R["pill"],
        border_width=1, border_color=C["border"],
        fg_color=C["paper_tag"], progress_color=color,
        button_color=C["white"], button_hover_color=C["card"],
        font=F["small"], text_color=C["ink"],
    )


def Card(master, shadow=True):
    """Soft surface card: hairline border, slight radius, subtle shadow.

    Body is gridded (not placed) so the card reports a real requested size
    to its parent and works inside scroll containers.
    """
    wrap = tk.Frame(master, bg=C["bg"])
    wrap.grid_columnconfigure(0, weight=1)
    wrap.grid_rowconfigure(0, weight=1)
    if shadow:
        sh = tk.Frame(wrap, bg=C["shadow"])
        sh.grid(row=0, column=0, sticky="nsew", padx=(3, 0), pady=(3, 0))
    body = ctk.CTkFrame(
        wrap, fg_color=C["card"],
        corner_radius=R["card"],
        border_width=1, border_color=C["border"],
    )
    body.grid(row=0, column=0, sticky="nsew")
    return wrap, body


def Divider(master, color=None):
    tk.Frame(master, bg=color or C["border"], height=1).pack(fill="x")


def SectionTitle(master, index, title, sub=None, color=None):
    """Modern section header: soft accent chip + title + subtitle."""
    color = color or C["teal"]
    row = tk.Frame(master, bg=C["card"])
    row.grid_columnconfigure(2, weight=1)
    ctk.CTkLabel(row, text=index, font=F["badge"], fg_color=_mix(color, "#FFFFFF", 0.82),
                 text_color=color, corner_radius=8, width=36, height=36,
                 anchor="center").grid(row=0, column=0, sticky="nw", padx=(2, 0))
    head = tk.Frame(row, bg=C["card"])
    head.grid(row=0, column=1, sticky="nw", padx=(12, 0))
    ctk.CTkLabel(head, text=title.upper(), font=F["h1"], text_color=C["ink"],
                 anchor="w").pack(anchor="w")
    if sub:
        ctk.CTkLabel(head, text=sub, font=F["small"], text_color=C["muted"],
                     anchor="w").pack(anchor="w", pady=(2, 0))
    return row


def console_box(master, height=190):
    """Rendered log dock (dark rounded, monospace)."""
    box = ctk.CTkTextbox(
        master, height=height,
        corner_radius=R["card"], border_width=1, border_color=C["dark3"],
        fg_color=C["dark"], text_color=C["cream"], font=F["mono"],
        wrap="word",
    )
    box.configure(state="disabled")
    return box


def HubCard(master, color, icon, title, sub, cmd, icon_name=None):
    """Modern action card: white surface, soft accent icon tile, hover tint."""
    base = C["card"]
    tint = _mix(color, "#FFFFFF", 0.85)
    border_idle = C["border"]
    border_hot = _mix(color, "#FFFFFF", 0.45)

    wrap = tk.Frame(master, bg=C["bg"])
    card = tk.Frame(wrap, bg=base, highlightthickness=1,
                    highlightbackground=border_idle)
    card.place(x=0, y=0, relwidth=1, relheight=1)

    if icon_name:
        icon_tile = tk.Frame(card, bg=tint)
        icon_tile.place(x=18, y=18, width=52, height=52)
        icon_lbl = IconLabel(icon_tile, icon_name, 30, color)
        icon_lbl.place(x=11, y=11)
    else:
        icon_tile = tk.Frame(card, bg=tint)
        icon_tile.place(x=18, y=18, width=52, height=52)
        icon_lbl = ctk.CTkLabel(icon_tile, text=icon, font=F["icon"],
                                text_color=color)
        icon_lbl.place(x=12, y=13)
    title_lbl = ctk.CTkLabel(card, text=title.upper(), font=F["h1"],
                             text_color=C["ink"], anchor="w")
    title_lbl.place(x=84, y=20)
    sub_lbl = ctk.CTkLabel(card, text=sub, font=F["small"],
                           text_color=C["muted"],
                           anchor="w", justify="left",
                           wraplength=300)
    sub_lbl.place(x=84, y=46, relwidth=0.72)

    go = ctk.CTkButton(
        card, text="OPEN  \u2192", font=F["small"], text_color=color,
        fg_color=tint, hover_color=_mix(color, "#FFFFFF", 0.7),
        corner_radius=R["pill"], border_width=0,
        width=96, height=28, anchor="center",
        command=cmd if cmd else None,
    )
    go.place(x=18, rely=1.0, y=-40)

    def _enter(_e):
        card.configure(highlightbackground=border_hot)
        title_lbl.configure(text_color=color)

    def _leave(_e):
        card.configure(highlightbackground=border_idle)
        title_lbl.configure(text_color=C["ink"])

    for w in (card, icon_lbl, title_lbl, sub_lbl, go):
        w.bind("<Enter>", _enter)
        w.bind("<Leave>", _leave)
        w.configure(cursor="hand2")

    return wrap


def CheckRow(master, name, caption="", status="OK", icon_size=22, tag=None):
    """Diagnostic row: tinted status glyph + title + caption (+ optional tag).

    status is one of STATE_ICONS keys (OK/GOOD/BAD/WARN/IDLE/META).
    Returns the (unplaced) row Frame so the caller chooses pack/grid.
    """
    icon_name, icon_color = STATE_ICONS.get(status, STATE_ICONS["IDLE"])
    row = tk.Frame(master, bg=C["card"])
    row.grid_columnconfigure(2, weight=1)
    IconLabel(row, icon_name, icon_size, icon_color).grid(row=0, column=0,
                                                          sticky="w", padx=(0, 10))
    head = tk.Frame(row, bg=C["card"])
    head.grid(row=0, column=2, sticky="w")
    head.grid_columnconfigure(0, weight=1)
    ctk.CTkLabel(head, text=name.upper(), font=F["small"],
                 text_color=C["ink"], anchor="w").grid(row=0, column=0, sticky="w")
    if caption:
        ctk.CTkLabel(head, text=caption, font=F["tiny"],
                     text_color=C["muted"], anchor="w").grid(
            row=1, column=0, sticky="w", pady=(1, 0))
    if tag:
        W_tag = Tag(row, str(tag), _mix(icon_color, "#FFFFFF", 0.55), height=24)
        W_tag.grid(row=0, column=3, sticky="e", padx=(8, 0))
    return row


def StepChip(master, index, label, command, active=False, done=False):
    """Pill stepper chip used inside multistep forms.

    States: idle (grey pill) -> done (soft accent) -> active (accent).
    """
    if done or active:
        fg = C["teal"]
        tx = C["white"]
        hov = hover(C["teal"])
    else:
        fg = C["paper_tag"]
        tx = C["dim"]
        hov = C["teal_muted"]
    return ctk.CTkButton(
        master, text=f"0{index} // {label}", command=command,
        width=150, height=30,
        corner_radius=R["pill"], border_width=0,
        fg_color=fg, hover_color=hov,
        text_color=tx, font=F["small"], anchor="center",
    )


def new_modal(root_parent, title, width=720, height=520):
    """Rounded SaaS dialog. Returns (win, body, close)."""
    win = ctk.CTkToplevel(root_parent)
    win.title(title)
    win.geometry(f"{width}x{height}")
    win.transient(root_parent)
    win.attributes("-topmost", True)
    win.configure(fg_color=C["bg"])
    win.resizable(True, True)
    win.minsize(480, 320)

    bar = tk.Frame(win, bg=C["dark"])
    bar.pack(fill="x")
    ctk.CTkLabel(bar, text="  " + title.upper(), font=F["h1"],
                 text_color=C["cream"], anchor="w").pack(side="left", pady=10)
    close = ctk.CTkLabel(bar, text="\u2715", font=F["h1"], text_color=C["red"],
                         cursor="hand2")
    close.pack(side="right", padx=16)

    body = tk.Frame(win, bg=C["bg"])
    body.pack(fill="both", expand=True, padx=24, pady=(20, 24))
    body.grid_columnconfigure(0, weight=1)
    body.grid_rowconfigure(0, weight=1)

    def _close():
        win.destroy()

    close.bind("<Button-1>", lambda _e: _close())
    win.bind("<Escape>", lambda _e: _close())
    return win, body, _close

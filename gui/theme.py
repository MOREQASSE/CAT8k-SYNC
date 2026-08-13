"""Modern SaaS design tokens (light theme, soft surfaces) for the Company
automation dashboard.

Key names mirror the old brutalist set so all call sites keep working;
values move to a soft, rounded, Linear/Vercel-style palette.
"""

C = {
    # surfaces
    "bg":          "#F4F6F9",   # app canvas
    "card":        "#FFFFFF",   # cards / panels
    "paper_tag":   "#F1F4F9",   # soft muted fill
    "cream":       "#F8FAFC",   # text on dark
    "ink":         "#0F172A",   # primary text
    "dim":         "#334155",   # hover on dark
    "muted":       "#64748B",   # secondary text
    "border":      "#E3E8EF",   # hairline borders
    "shadow":      "#DDE3EA",   # card shadow tint
    "white":       "#FFFFFF",
    "black":       "#0B1220",

    # dark surfaces (sidebar / terminal / toasts)
    "dark":        "#0F172A",
    "dark2":       "#1E293B",
    "dark3":       "#27364B",

    # accent scale (teal/cyan)
    "teal":        "#0E7490",
    "teal_h":      "#155E75",
    "teal_l":      "#06B6D4",
    "teal_muted":  "#E0F2FE",
    "teal_soft":   "#ECFDF5",

    # semantic
    "yellow":      "#F59E0B",
    "yellow_h":    "#D97706",
    "yellow_soft": "#FEF3C7",
    "red":         "#EF4444",
    "red_h":       "#DC2626",
    "red_soft":    "#FEE2E2",
    "green":       "#10B981",
    "green_h":     "#059669",
    "green_soft":  "#D1FAE5",
    "blue":        "#3B82F6",
    "blue_h":      "#2563EB",
    "blue_soft":   "#DBEAFE",
}

_SANS = "Segoe UI"
_MONO = "Consolas"

F = {
    "brand":    (_SANS, 20, "bold"),
    "brand_sm": (_SANS, 11, "bold"),
    "h1":       (_SANS, 15, "bold"),
    "h2":       (_SANS, 13, "bold"),
    "body":     (_SANS, 13),
    "mono":     (_MONO, 11),
    "small":    (_SANS, 11, "bold"),
    "tiny":     (_SANS, 10),
    "btn":      (_SANS, 12, "bold"),
    "badge":    (_SANS, 11, "bold"),
    "icon":     (_SANS, 15, "bold"),
    "big":      (_SANS, 20, "bold"),
    "label":    (_SANS, 10, "bold"),
}

R = {
    "card":   12,     # card corner radius
    "btn":    8,      # button radius
    "field":  8,      # input radius
    "pill":   999,    # pills / chips
    "nav":    8,      # sidebar items
}

NAV = {
    "width":         236,
    "item_h":        42,
    "logo_h":        84,
}

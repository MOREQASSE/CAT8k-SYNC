"""Rasterized, runtime-tinted icon library for the Company dashboard.

gui/icons/*.svg are single-color (fill="currentColor") glyphs. We render
each one with resvg (bundled native rasterizer, no system deps) after
rewriting its color, then scale to target size and cache:

    icons.get(name, size, color)           -> PIL RGBA image
    icons.ckimg(name, size, color)         -> ctk.CTkImage (for CTkButton/CTkLabel)
"""
import io
import os

import customtkinter as ctk
from PIL import Image
from resvg_py import svg_to_bytes

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
_fs_cache = {}
_pil_cache = {}

# semantic icon keys -> file names (names match files verbatim)
NAMES = [
    "cloud-server",
    "close-cross",
    "expand-arrows",
    "network-switch-chart-screen",
    "network-switch-closed",
    "network-switch-sucess-tick-beside",
    "network-switch-with-cable",
    "network-switch-with-warning-beside",
    "network-switches-stacked-pile",
    "router-error-screen",
    "router-stacked-pile",
    "router-sucess-tick-beside-it",
    "router-warning-beside-it",
    "server-error-cross",
    "server-sucess-tick",
    "switch-device",
]


def names():
    files = [f[:-4] for f in os.listdir(_DIR) if f.endswith(".svg")]
    return sorted(set(files))


def _source(name):
    if name not in _fs_cache:
        with open(os.path.join(_DIR, name + ".svg"), encoding="utf-8") as fh:
            _fs_cache[name] = fh.read()
    return _fs_cache[name]


def render(name, size=24, color="#0D7377"):
    """Rendered RGBA PIL image (transparent bg, tinted glyph), cached."""
    key = (name, size, color)
    img = _pil_cache.get(key)
    if img is not None:
        return img
    svg = _source(name).replace("currentColor", color)
    try:
        png = svg_to_bytes(svg_string=svg, width=size)
        img = Image.open(io.BytesIO(png)).convert("RGBA")
    except Exception:
        img = Image.new("RGBA", (size, size), color + "FF")
        _pil_cache[key] = img
        return img
    bbox = img.getchannel("A").getbbox()
    if bbox:
        img = img.crop(bbox)
    if img.width > size or img.height > size:
        img.thumbnail((size, size), Image.LANCZOS)
    _pil_cache[key] = img
    return img


def ckimg(name, size=24, color="#0D7377"):
    """ctk.CTkImage for use in CTkButton/CTkLabel (image=...)."""
    img = render(name, size, color)
    return ctk.CTkImage(light_image=img, dark_image=img, size=(img.width, img.height))
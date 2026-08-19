"""Dual-instance device backend resolver.

Two live instances share this app:

  * normal      — the public Catalyst 8000 instance, reachable from any
                  network (device credentials sealed in the ambient vault).
  * reservation — the IOS XE on Cat8kv reservation, reachable ONLY while the
                  Cisco Secure Client tunnel is up (vpn record + the whole
                  reservation device inventory it exposes).

Selection is persisted in SQLite as the ``device.backend`` setting:

  * "normal"      — always the public instance (device table is used).
  * "reservation" — always the Cat8kv reservation (vpn record + companion
                    credential sets).
  * "auto"        — a cheap TCP probe of the reservation device host:443
                    decides: when the tunnel answers, the reservation wins;
                    otherwise the public instance is used. The probe result
                    is cached for PROBE_TTL seconds and invalidated on every
                    connect / disconnect / save cycle so a mode flip is
                    visible immediately.

The resolved instance is ALSO persisted (``device.identity`` +
``device.identity_at``) so other pages can serve instance-specific
content based on which one is active.

Every device-access path funnels through ``active_device()``
(connector.load_devices, cli_runner, netconf_explorer, webapp ping), so a
single resolution here switches ALL endpoints at once.
"""
import time

from src import db
from src import vpn as vpnlib

BACKENDS = ("auto", "normal", "reservation")
LEGACY = {"vault": "normal", "vpn": "reservation"}
IDENTITY_NORMAL = "cat8000-public"
IDENTITY_RESERVATION = "cat8000v-reservation"
PROBE_TTL = 15.0          # seconds before the tunnel probe is re-issued
VPN_RESTCONF_PORT = 443

# Defaults for the Cat8kv reservation (DevNet 'Catalyst 8000v Credentials').
# The VPN quick-access login (vpn.username / vpn.password) authenticates the
# AnyConnect endpoint only — the device itself uses this separate SSH/RESTCONF
# login. Users may override any of these in the profile; secrets are
# Fernet-sealed once saved.
DEFAULT_DEVICE_HOST = "10.10.20.48"
DEFAULT_DEVICE_USERNAME = "developer"
DEFAULT_DEVICE_PASSWORD = "C1sco12345"

_probe = {"ts": 0.0, "ok": False, "host": ""}


def invalidate():
    """Drop the cached probe — call after any VPN connect/disconnect/save."""
    _probe["ts"] = 0.0


def _coerce(mode):
    mode = str(mode or "").strip().lower()
    return LEGACY.get(mode, mode)


def get_backend():
    """Persisted backend preference, safe default 'auto'."""
    mode = _coerce(db.get_setting("device.backend", "auto") or "auto")
    return mode if mode in BACKENDS else "auto"


def set_backend(mode):
    """Persist and apply a backend preference; returns the new info dict."""
    mode = _coerce(mode)
    if mode not in BACKENDS:
        raise ValueError(f"backend must be one of {', '.join(BACKENDS)}")
    db.set_setting("device.backend", mode)
    invalidate()
    return active_info()


def vpn_device():
    """The reservation backend when fully configured, else None.

    The VPN-side device host (vpn.device_host) is the management IP /
    hostname of the IOS XE on Cat8kv instance inside the tunnel, taken from
    the DevNet reservation page ('Catalyst 8000v Credentials'). Its device
    login (vpn.device_username / vpn.device_password) is a SEPARATE
    credential pair from the AnyConnect quick-access login — with the
    reservation's documented defaults applied when not overridden."""
    rec = db.get_vpn_plain() or {}
    host = str(rec.get("device_host") or DEFAULT_DEVICE_HOST).strip()
    username = str(rec.get("device_username")
                   or rec.get("username") or DEFAULT_DEVICE_USERNAME).strip()
    password = str(rec.get("device_password")
                   or rec.get("password") or DEFAULT_DEVICE_PASSWORD)
    if not (host and username and password):
        return None
    return {
        "name": "Cat8000-VPN",
        "device_type": "cisco_ios",
        "host": host,
        "username": username,
        "password": password,
        "secret": password,
        "port": 22,
        "fast_cli": True,
        "global_delay_factor": 2,
        "restconf_https": True,
        "restconf_verify_ssl": False,
        "restconf_port": VPN_RESTCONF_PORT,
        "netconf_port": 830,
        "source": "reservation",
    }


def _probe_vpn():
    """Cached tunnel truth: can we reach the reservation device host?"""
    dev = vpn_device()
    if not dev:
        _probe.update(ts=0.0, ok=False, host="")
        return False
    host = dev["host"]
    now = time.monotonic()
    if _probe["host"] != host or now - _probe["ts"] > PROBE_TTL:
        ok = vpnlib.tunnel_probe(host, VPN_RESTCONF_PORT)
        _probe.update(ts=now, ok=bool(ok), host=host)
    return _probe["ok"]


def active_device():
    """Effective device dict (with 'source' key) for the current backend,
    or the vault device when the preferred backend is unusable."""
    mode = get_backend()
    vpn = vpn_device()

    if mode == "reservation" and vpn:
        return dict(vpn)
    if mode == "reservation":
        # misconfigured reservation — degrade to the public instance
        mode = "auto"

    if mode == "auto":
        if vpn and _probe_vpn():
            return dict(vpn)
        return _normal_device()

    # explicit normal instance
    return _normal_device()


def _normal_device():
    dev = db.get_device_plain()
    if not dev:
        return None
    dev = dict(dev)
    dev["source"] = "normal"
    return dev


def _identity_for(active):
    return (IDENTITY_RESERVATION if (active or {}).get("source") == "reservation"
            else IDENTITY_NORMAL)


def _persist_identity(ident):
    """SQLite marker of WHICH instance is active right now — for future
    instance-specific page serving. Written only on change."""
    current = db.get_setting("device.identity", "")
    if current != ident:
        db.set_setting("device.identity", ident)
        db.set_setting("device.identity_at", db.now())


def active_info():
    """{mode, source, host, tunnel, reason, vpn_host, identity} — for the
    profile UI, the fabric pill and diagnostics."""
    mode = get_backend()
    vpn = vpn_device()
    if mode == "reservation" and not vpn:
        return {"mode": mode, "source": "normal", "host": _normal_host(),
                "tunnel": False, "reason": "vpn-device-host-missing",
                "vpn_host": "", "identity": IDENTITY_NORMAL}
    active = active_device()
    _persist_identity(_identity_for(active))
    tunnel = bool(vpn and _probe_vpn())
    return {
        "mode": mode,
        "source": (active or {}).get("source", "normal") if active else "normal",
        "host": (active or {}).get("host", ""),
        "tunnel": tunnel,
        "reason": None,
        "vpn_host": (vpn or {}).get("host", ""),
        "identity": _identity_for(active),
    }


def _normal_host():
    dev = db.get_device_plain()
    return (dev or {}).get("host", "")
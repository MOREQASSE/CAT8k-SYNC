"""Sandbox VPN control — drives the Cisco Secure Client / AnyConnect CLI.

The app never establishes the tunnel itself; it shells out to the vendor
client (vpncli.exe) with the Quick Access credentials stored in the vault
(vpn_address / vpn_username / vpn_password). The password is fed via
subprocess stdin only and is never logged or echoed back.

Tunnel truth = TCP probe of the vaulted device host:restconf_port — the
client's own state string is parsed as secondary info (locale-tolerant:
English + French UI).
"""
import os
import re
import socket
import subprocess

CLIENT_CANDIDATES = [
    r"C:\Program Files (x86)\Cisco\Cisco Secure Client\vpncli.exe",
    r"C:\Program Files\Cisco\Cisco Secure Client\vpncli.exe",
    r"C:\Program Files (x86)\Cisco\Cisco Secure Client\vpn.exe",
    r"C:\Program Files\Cisco\Cisco Secure Client\vpn.exe",
    r"C:\Program Files (x86)\Cisco\Cisco AnyConnect Secure Mobility Client\vpncli.exe",
    r"C:\Program Files\Cisco\Cisco AnyConnect Secure Mobility Client\vpncli.exe",
]

CREATE_NO_WINDOW = 0x08000000

_UI_PROCS = ("csc_ui.exe", "vpnui.exe")


def find_client():
    """First existing vpncli/vpn binary, or None."""
    for path in CLIENT_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


def _close_ui():
    """The Secure Client tray UI holds the VPN connection function and makes
    the CLI fail with 'acquired by another application'. Close it before
    driving the CLI (it auto-restarts on next login)."""
    for proc in _UI_PROCS:
        try:
            subprocess.run(["taskkill", "/F", "/IM", proc],
                           capture_output=True, timeout=10,
                           creationflags=CREATE_NO_WINDOW)
        except Exception:  # noqa: BLE001
            pass


def _run(cli, args, script, timeout=60):
    """Run the client in scripted (-s) or plain mode with a redacted context."""
    try:
        proc = subprocess.run(
            [cli] + args,
            input=script.encode("utf-8", errors="replace"),
            capture_output=True,
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW,
        )
        out = (proc.stdout or b"").decode("utf-8", errors="replace")
        err = (proc.stderr or b"").decode("utf-8", errors="replace")
        return out, err, None
    except subprocess.TimeoutExpired:
        return "", "", "timeout"
    except OSError as e:
        return "", "", str(e)


def _parse_state(text):
    """Last '>> state: X' line -> connected / disconnected / unknown."""
    states = re.findall(r">>\s*state:\s*(.+)", text)
    if not states:
        return "unknown"
    last = states[-1].strip().lower()
    if "dé" in last or "dis" in last or "deconnect" in last:
        return "disconnected"
    if "connect" in last:
        return "connected"
    return "unknown"


def tunnel_probe(host, port=443, timeout=4):
    """True when the device's RESTCONF port answers (i.e. tunnel carries traffic)."""
    if not host:
        return False
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def vpn_state(device_host=None, device_port=443):
    """{client, cli, tunnel} — client installed?, client's own state, real probe."""
    cli = find_client()
    client = bool(cli)
    cli_state = "unknown"
    if cli:
        try:
            out, _, _ = _run(cli, ["state"], "", timeout=15)
            cli_state = _parse_state(out)
        except Exception:  # noqa: BLE001
            cli_state = "unknown"
    return {
        "client": client,
        "cli": cli_state,
        "tunnel": tunnel_probe(device_host, device_port),
    }


def vpn_connect(address, username, password, timeout=70):
    """Scripted connect; returns {ok, connected?, error?} (password never echoed)."""
    cli = find_client()
    if not cli:
        return {"ok": False, "error": "client-not-found"}
    _close_ui()
    script = (
        f"connect {address}\n"
        f"{username}\n"
        f"{password}\n"
        "y\n"
        "exit\n"
    )
    out, err, fail = _run(cli, ["-s"], script, timeout=timeout)
    if fail:
        return {"ok": False, "error": "timeout" if fail == "timeout" else "client-error"}
    low = (out + err).lower()
    if "acquise par une autre application" in low or "acquired by another" in low:
        return {"ok": False, "error": "client-busy"}
    if "login failed" in low or "authentication failed" in low or "access denied" in low:
        return {"ok": False, "error": "login-rejected"}
    if _parse_state(out) == "connected":
        return {"ok": True, "connected": True}
    if ("impossible de contacter" in low or "could not connect" in low
            or "connection failed" in low or "vérifiez la connectivité" in low):
        return {"ok": False, "error": "endpoint-unreachable"}
    return {"ok": False, "error": "not-connected"}


def vpn_disconnect(timeout=30):
    cli = find_client()
    if not cli:
        return {"ok": False, "error": "client-not-found"}
    out, _, fail = _run(cli, ["-s"], "disconnect\n", timeout=timeout)
    if fail:
        return {"ok": False, "error": "timeout" if fail == "timeout" else "client-error"}
    state = _parse_state(out)
    if state == "disconnected":
        return {"ok": True, "state": "disconnected"}
    if state == "unknown":
        return {"ok": False, "error": "unknown-state",
                "detail": "client returned no usable state — re-check manually"}
    return {"ok": False, "error": "still-connected", "state": state}

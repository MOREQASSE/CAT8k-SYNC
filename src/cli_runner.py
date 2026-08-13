"""SSH CLI runner — netmiko (cisco_xe) over :22.

Read-only by design: only show/dir/more/ping/traceroute verbs are accepted,
so the web toolbox can never mutate config through this path. Every run is
still recorded in the activity log by the caller.
"""

import re
import time

from src import db

SAFE_VERBS = ("show", "dir", "more", "ping", "traceroute", "terminal")


def _params():
    dev = db.get_device_plain()
    if not dev:
        raise ConnectionError("no device in vault — run setup first")
    return {
        "host": dev["host"],
        "username": dev["username"],
        "password": dev["password"],
        "secret": dev["secret"] or dev["password"],
        "port": int(dev.get("port") or 22),
        "device_type": "cisco_xe",
        "fast_cli": True,
        "global_delay_factor": 2,
        "conn_timeout": 20,
        "timeout": 60,
    }


def run_show(command, timeout=60):
    cmd = str(command or "").strip()
    if not cmd:
        raise ValueError("empty command")
    first = re.split(r"[\s/]+", cmd)[0].lower()
    if first not in SAFE_VERBS:
        raise ValueError(
            f"refused: '{first}' — only read-only verbs allowed "
            f"({', '.join(SAFE_VERBS)})"
        )
    from netmiko import ConnectHandler
    last_error = None
    for attempt in (1, 2):
        try:
            with ConnectHandler(**_params()) as conn:
                out = conn.send_command(cmd, read_timeout=timeout)
            return {"ok": True, "command": cmd, "output": out or "",
                    "len": len(out or "")}
        except Exception as e:  # noqa: BLE001 - transport can flake on first connect
            last_error = e
            if attempt == 1 and "binding" in str(e):
                time.sleep(2)
                continue
            raise
    raise last_error

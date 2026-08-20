import os

import yaml
from netmiko import (
    ConnectHandler,
    NetmikoAuthenticationException,
    NetmikoTimeoutException,
)

from src import db


NON_NETMIKO_KEYS = {
    "name",
    "description",
    "restconf_https",
    "restconf_verify_ssl",
    "restconf_port",
}
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_warned = False


def _load_dotenv():
    """Minimal .env loader (no dependency): KEY=VALUE lines at project root,
    existing environment variables always win."""
    path = os.path.join(ROOT, ".env")
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key, value = key.strip(), value.strip().strip("'\"")
            os.environ.setdefault(key, value)


def _env_creds():
    """Credentials from environment (optional fallback when the vault is empty)."""
    return {
        "username": os.environ.get("CAT8000_USERNAME", "").strip(),
        "password": os.environ.get("CAT8000_PASSWORD", ""),
        "secret": os.environ.get("CAT8000_SECRET", ""),
    }


def load_devices(filepath=None):
    """Device inventory. Source of truth is the encrypted SQLite vault
    (written by the GUI setup / CLI 'setup' / profile page) — or, when the
    dual-mode resolver picks the VPN backend, the reservation device host.
    Falls back to non-secret fields in config/devices.yaml plus optional
    CAT8000_* env credentials; raises if no credentials are resolvable."""
    global _warned
    _load_dotenv()
    from src import device_mode
    rec = device_mode.active_device() or db.get_device_plain()
    if rec:
        return [{
            "name": rec["name"],
            "device_type": "cisco_ios",
            "host": rec["host"],
            "username": rec["username"],
            "password": rec["password"],
            "secret": rec["secret"] or rec["password"],
            "port": int(rec.get("port") or 22),
            "fast_cli": True,
            "global_delay_factor": 2,
            "restconf_https": bool(rec.get("https", True)),
            "restconf_verify_ssl": bool(rec.get("verify_ssl", False)),
            "restconf_port": int(rec.get("restconf_port") or 443),
        }]
    filepath = filepath or os.path.join(ROOT, "config", "devices.yaml")
    if not _warned:
        _warned = True
        print("[WARN] No device in SQLite vault — resolving credentials from "
              "CAT8000_* environment variables.")
    with open(filepath, "r") as f:
        devices = yaml.safe_load(f)["devices"]
    env = _env_creds()
    for dev in devices:
        dev["username"] = env["username"] or dev.get("username", "")
        dev["password"] = env["password"]
        dev["secret"] = env["secret"] or env["password"]
        if not (dev["username"] and dev["password"]):
            raise ValueError(
                "Device credentials missing: open the app Profile page and save "
                "the device login (or run 'python main.py setup'), or set "
                "CAT8000_USERNAME/CAT8000_PASSWORD."
            )
    return devices


def netmiko_params(device_dict):
    return {k: v for k, v in device_dict.items() if k not in NON_NETMIKO_KEYS}


def get_device_params(devices, device_name=None):
    if device_name:
        for dev in devices:
            if dev["name"] == device_name:
                return netmiko_params(dict(dev))
        raise ValueError(f"Device '{device_name}' not found in config/devices.yaml")
    return netmiko_params(dict(devices[0]))


def connect_test(device_name=None, commands=None):
    commands = commands or [
        "show version | include IOS",
        "show ip interface brief",
    ]

    devices = load_devices()
    selected = [(dev["name"], netmiko_params(dev)) for dev in devices]
    if device_name:
        selected = [item for item in selected if item[0] == device_name]
        if not selected:
            raise ValueError(
                f"Device '{device_name}' not found in config/devices.yaml"
            )
    all_ok = True

    for name, dev in selected:
        print("=" * 64)
        print(f"  CONNECTION TEST -> {name} ({dev['host']})")
        print("=" * 64)
        try:
            conn = ConnectHandler(**dev)
            print(f"[OK] SSH session established ({dev['host']}:{dev['port']})")

            conn.enable()
            print("[OK] Privileged EXEC (enable) escalation succeeded")

            for command in commands:
                print(f"\n--- {command} ---")
                output = conn.send_command(command)
                print(output)

            conn.disconnect()
            print(f"\n[OK] {name}: connection test PASSED")
        except NetmikoTimeoutException:
            print(f"[FAIL] {name}: connection timed out")
            all_ok = False
        except NetmikoAuthenticationException:
            print(f"[FAIL] {name}: authentication failed (check username/password)")
            all_ok = False
        except Exception as e:
            print(f"[FAIL] {name}: unexpected error -> {e}")
            all_ok = False

    return all_ok


if __name__ == "__main__":
    ok = connect_test()
    raise SystemExit(0 if ok else 1)

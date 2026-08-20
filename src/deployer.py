import json
import os
import socket
import time
from datetime import datetime

from netmiko import (
    ConnectHandler,
    NetmikoAuthenticationException,
    NetmikoTimeoutException,
)

from src import db
from src.connector import get_device_params, load_devices
from src.restconf_client import RestconfError, get, get_restconf_device, put


def tcp_probe(host, port, timeout=6):
    """Live TCP reachability probe for one transport plane."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError as e:
        print(f"[PREFLIGHT] TCP {host}:{port} unreachable ({e})")
        return False


def preflight_device(rc, require_ssh=False):
    """Probe the device's planes before a deploy: TCP 443 (RESTCONF),
    TCP 22 (CLI/SSH), and a RESTCONF hostname read (auth + app plane).
    Returns (planes_up, hostname, notes). Never raises.
    require_ssh gates on port 22 too — only host deployments need the
    CLI plane (their DHCP lease can only be pushed over SSH)."""
    https_ok = tcp_probe(rc["host"], int(rc.get("port") or 443))
    ssh_ok = tcp_probe(rc["host"], 22) if require_ssh else None
    hostname = ""
    if https_ok:
        try:
            data = get(rc, "Cisco-IOS-XE-native:native/hostname", timeout=15)
            hostname = str(data.get("Cisco-IOS-XE-native:hostname") or "")
        except RestconfError as e:
            print(f"[PREFLIGHT] RESTCONF hostname probe failed: {e}")
    notes = []
    if not https_ok:
        notes.append("HTTPS 443 unreachable — RESTCONF plane down")
    if ssh_ok is False:
        notes.append("SSH 22 unreachable — CLI fallback impossible")
    if https_ok and not hostname:
        notes.append("HTTPS answers but RESTCONF does not — device may be mid-reset")
    if hostname:
        last = ""
        try:
            last = str(db.get_setting("last_seen_hostname", "") or "")
        except Exception:  # noqa: BLE001
            pass
        if last and hostname.lower() != last.lower():
            notes.append(f"device identity changed ({last} -> {hostname}) "
                         f"— likely a sandbox reset; re-run setup if interfaces moved")
        else:
            notes.append(f"device identity: {hostname}")
    planes = https_ok and bool(hostname) and (ssh_ok is not False)
    return planes, hostname, "; ".join(notes) or "no notes"


def _is_transport(text):
    """True when a failure is transport-level (device unreachable / session
    refused) rather than application-level (HTTP status, invalid config)."""
    low = str(text).lower()
    return any(h in low for h in (
        "transport error", "timed out", "connection refused",
        "connection reset", "unreachable", "socket", "max retries",
        "name or service not known", "timeout", "could not connect",
    ))


def build_device_params(action_data):
    devices = load_devices()
    device_name = action_data.get("device", "Cat8000-Sandbox")
    try:
        params = get_device_params(devices, device_name)
    except ValueError:
        # vault/active device record may carry its own name — fall back to it
        params = get_device_params(devices)
    params["host"] = action_data.get("target_router_ip") or action_data.get(
        "router_wan_ip"
    ) or params["host"]
    return params


def save_config_to_file(site_name, action, config_text, output_dir="output"):
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{site_name}_{action}_{timestamp}.txt"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "w") as f:
        f.write(config_text)
    print(f"Config saved to {filepath}")
    return filepath


def deploy_host_via_ssh(action_data):
    """Push the host lease reservation over SSH CLI when the device's
    RESTCONF model does not expose a writable native/ip/dhcp container.
    Retries on transport-level failures — the shared sandbox's SSH plane
    flaps (TCP refused) after resets and under session pressure, and a
    single transient refusal would otherwise reject the whole provision.
    Returns (ok, transport): transport is True when the failure looks
    like a connection-level problem (worth a whole-deploy retry)."""
    try:
        params = build_device_params(action_data)
    except Exception as e:
        print(f"SSH fallback: device params unavailable ({e})")
        return False, False
    config_text = f"ip dhcp excluded-address {action_data['pc_ip']}"
    waits = (2, 4)
    for attempt in (1, 2, 3):
        ok, kind = deploy_via_ssh(params, config_text)
        if ok:
            return True, False
        if kind != "transport":
            return False, False
        if attempt < 3:
            print(f"[SSH] transport failure on attempt {attempt}/3 — "
                  f"retrying in {waits[attempt - 1]}s (sandbox SSH plane flapping)")
            time.sleep(waits[attempt - 1])
    return False, True


def deploy_via_ssh(device_params, config_text):
    try:
        print(f"Connecting to {device_params['host']}...")
        conn = ConnectHandler(**device_params)
        conn.enable()

        commands = [
            line.strip()
            for line in config_text.splitlines()
            if line.strip()
            and not line.strip().startswith("!")
            and not line.strip().startswith("hostname")
        ]

        output = conn.send_config_set(commands)
        print(output)

        conn.save_config()
        print(f"Configuration saved on {device_params['host']}.")
        conn.disconnect()
        return True, "ok"
    except NetmikoTimeoutException as e:
        print(f"SSH connection failed: {e}")
        return False, "transport"
    except NetmikoAuthenticationException as e:
        print(f"SSH authentication failed: {e}")
        return False, "auth"
    except Exception as e:
        print(f"Deployment error: {e}")
        return False, "transport" if _is_transport(str(e)) else "error"


def deploy(action_data, config_text, generate_only=False):
    site_name = action_data["site_name"]

    save_config_to_file(site_name, action_data["action"], config_text)

    if not generate_only:
        device_params = build_device_params(action_data)
        deploy_via_ssh(device_params, config_text)
    else:
        print(f"[Dry-run] Config for {site_name} written to output/ directory only.")


# ============================================================
# RESTCONF provisioning driver (primary — works over HTTPS 443)
# ============================================================

def interface_identity(port, vlan_id=None):
    """Map CLI port string to YANG interface name."""
    short = port.replace("GigabitEthernet", "").replace("gigabitethernet", "").replace("FastEthernet", "").replace("fastethernet", "")
    return f"{short}.{vlan_id}" if vlan_id else short


def get_physical_parent_interface(rc):
    """Discover the device's physical GigabitEthernet to attach subinterfaces."""
    iface_data = get(rc, "Cisco-IOS-XE-native:native/interface")
    gig_list = iface_data.get("Cisco-IOS-XE-native:interface", {}).get(
        "GigabitEthernet", []
    )
    physical = [g["name"] for g in gig_list if "." not in str(g.get("name", ""))]
    if not physical:
        raise RestconfError("No physical GigabitEthernet interface found on device")
    return physical[0]


def build_subinterface_payload(action_data, parent_name):
    trunk_port = action_data["router_trunk_port"]
    vlan_id = action_data.get("vlan_id") or action_data.get("department_vlan")
    name = f"{parent_name}.{vlan_id}"
    # IOS-XE RESTCONF requires the FULL subtree wrapped in the list key:
    return {"GigabitEthernet": [{
        "name": name,
        "description": f"{action_data.get('site_name')} {action_data.get('vlan_name', '')}".strip(),
        "encapsulation": {"dot1Q": {"vlan-id": vlan_id}},
        "ip": {
            "address": {
                "primary": {
                    "address": action_data["gateway"],
                    "mask": "255.255.255.0",
                }
            }
        },
    }]}


def build_subdept_payload(action_data, parent_name):
    trunk_port = action_data["trunk_port"]
    vlan_id = action_data["vlan_id"]
    name = f"{parent_name}.{vlan_id}"
    return {"GigabitEthernet": [{
        "name": name,
        "description": f"{action_data.get('site_name')} {action_data.get('vlan_name', '')}".strip(),
        "encapsulation": {"dot1Q": {"vlan-id": vlan_id}},
        "ip": {
            "address": {
                "primary": {
                    "address": action_data["gateway"],
                    "mask": "255.255.255.0",
                }
            }
        },
    }]}


def build_vlan_payload(action_data):
    vlan_id = (action_data.get("vlan_id") or action_data.get("department_vlan")
               or action_data.get("switch_vlan"))
    return {"vlan": [{"id": vlan_id, "name": action_data.get("vlan_name", "")}]}


def build_operations(action_data, rc):
    """Return [(method, label, path, payload), ...] for a provision action.

    Shared by the live deployer and the GUI payload preview.
    """
    action = action_data["action"]
    if action in ("add_branch", "add_subdept"):
        parent = get_physical_parent_interface(rc)
        print(f"[RESTCONF] Parent interface: GigabitEthernet{parent}")
        if action == "add_branch":
            payload = build_subinterface_payload(action_data, parent)
            vlan_id = action_data.get("vlan_id") or action_data.get("department_vlan")
            vlan_payload = build_vlan_payload(action_data)
        else:
            vlan_id = action_data["vlan_id"]
            payload = build_subdept_payload(action_data, parent)
            vlan_payload = None
        name = payload["GigabitEthernet"][0]["name"]
        operations = [
            ("PUT", "subinterface",
             f"Cisco-IOS-XE-native:native/interface/GigabitEthernet={name}",
             payload),
        ]
        if vlan_payload:
            operations.append(("PUT", "vlan",
                               f"Cisco-IOS-XE-native:native/vlan/Vlan={vlan_id}",
                               vlan_payload))
        return operations
    if action == "add_pc":
        ip = action_data["pc_ip"]
        return [("PUT", "dhcp-reserve",
                 f"Cisco-IOS-XE-native:native/ip/dhcp/excluded-address={ip}",
                 {"ip-address": ip})]
    if action == "add_endpoint":
        raise RestconfError(
            "add_endpoint (switchport config) is not supported on the "
            "Catalyst 8000 router sandbox — use a switch sandbox target.")
    raise RestconfError(f"Unknown action for RESTCONF: {action}")


def deploy_restconf(action_data, device_name=None, dry_run=False, _backoff=(5, 15)):
    site_name = action_data["site_name"]
    action = action_data["action"]
    _, rc = get_restconf_device(device_name or action_data.get("device"))
    print(f"[RESTCONF] {action.upper()} -> {site_name} on {rc['host']}")

    for attempt in range(1, 4):
        if not dry_run:
            planes_up, hostname, notes = preflight_device(
                rc, require_ssh=(action == "add_pc"))
            if hostname:
                try:
                    db.set_setting("last_seen_hostname", hostname)
                except Exception:  # noqa: BLE001
                    pass
            print(f"[PREFLIGHT] attempt {attempt}/3 — "
                  + ("planes up" if planes_up else "planes down") + f" | {notes}")
            if not planes_up:
                db.log_event("WARN", "PROVISION",
                             f"attempt {attempt}/3 planes down — skipping "
                             f"deploy: {notes}")
                if attempt < 3:
                    wait = _backoff[attempt - 1]
                    print(f"[RETRY] planes down on attempt {attempt}/3 — "
                          f"waiting {wait}s before retrying (shared sandbox cycles)")
                    time.sleep(wait)
                continue
        ok, transport = _deploy_once(action_data, rc, dry_run)
        if ok or not transport:
            return bool(ok)
        if attempt < 3:
            wait = _backoff[attempt - 1]
            db.log_event("WARN", "PROVISION",
                         f"attempt {attempt}/3 transport-level failure — "
                         f"waiting {wait}s before retrying")
            print(f"[RETRY] transport-level failure on attempt {attempt}/3 — "
                  f"waiting {wait}s before retrying")
            time.sleep(wait)
    return False


def _deploy_once(action_data, rc, dry_run):
    site_name = action_data["site_name"]
    action = action_data["action"]

    try:
        print("[RESTCONF] Discovering physical parent interface...")
        operations = build_operations(action_data, rc)
    except RestconfError as e:
        print(f"[FAIL] {e}")
        if any(k in str(e).lower() for k in ("connect", "reach", "timeout", "down")):
            print("[HINT] The Catalyst 8000 sandbox backend cycles up/down. "
                  "Wait a few minutes and re-run.")
        return False, _is_transport(str(e))

    out_lines = []
    all_ok = True
    transport = False
    for method, label, path, payload in operations:
        payload_text = json.dumps(payload, indent=2)
        print(f"\n--- {method} {path} ---")
        print(payload_text)
        if dry_run:
            print("[Dry-run] not sent")
            out_lines.append(f"--- {label} -> {path} ({method}) : DRY-RUN ---\n{payload_text}\n")
            continue
        try:
            put(rc, path, payload)
            print("[OK] applied")
            out_lines.append(f"--- {label} -> {path} ({method}) : APPLIED ---\n{payload_text}\n")
        except RestconfError as e:
            print(f"[FAIL] {e}")
            out_lines.append(f"--- {label} -> {path} ({method}) : FAILED ({e}) ---\n{payload_text}\n")
            if label == "vlan":
                print("[WARN] VLAN provisioning unsupported on this Router platform "
                      "(Catalyst 8000 exposes no VLAN database via native model). "
                      "Skipping — subinterface still applied.")
            elif label == "dhcp-reserve" and action == "add_pc":
                print("[WARN] RESTCONF native/ip/dhcp is not writable on this device — "
                      "falling back to SSH CLI (ip dhcp excluded-address).")
                ssh_ok, ssh_transport = deploy_host_via_ssh(action_data)
                if ssh_ok:
                    print("[OK] host lease reservation applied via SSH")
                    out_lines.append(
                        f"--- host-register via SSH : APPLIED ---\nip dhcp "
                        f"excluded-address {action_data['pc_ip']}\n")
                else:
                    print("[FAIL] SSH fallback failed — see SSH output above")
                    out_lines.append("--- host-register via SSH : FAILED ---\n")
                    all_ok = False
                    transport = ssh_transport
            else:
                all_ok = False
                transport = _is_transport(str(e))

    if action == "add_pc" and all_ok and not dry_run:
        db.save_host({
            "label": action_data["site_name"],
            "node_type": action_data.get("node_type") or "pc",
            "vlan_id": action_data.get("vlan_id"),
            "ip": action_data["pc_ip"],
            "mask": action_data.get("mask") or "255.255.255.0",
            "port": action_data.get("port"),
            "gateway": action_data.get("gateway"),
            "subnet": action_data.get("subnet"),
            "device": rc.get("host", ""),
        })
        db.log_event("INFO", "PROVISION",
                     f"host registered {action_data['site_name']} "
                     f"{action_data['pc_ip']} (vlan {action_data.get('vlan_id')})")
        print("[REGISTRY] host recorded in registry + ledger")

    out_dir = "output"
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(out_dir, f"{site_name}_{action}_restconf_{ts}.txt")
    verdict = ("DRY-RUN (nothing sent)" if dry_run
               else ("ALL OPERATIONS APPLIED" if all_ok
                     else "FAILURES — see per-operation status above"))
    with open(out_path, "w") as f:
        f.write(f"{site_name} | {action} | {verdict} | {ts}\n\n")
        f.write("\n".join(out_lines))
    print(f"\n{verdict}")
    print(f"Payloads + outcomes saved to {out_path}")
    return bool(all_ok), transport

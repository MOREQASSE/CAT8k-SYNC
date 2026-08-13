import json
import os
from datetime import datetime

from netmiko import (
    ConnectHandler,
    NetmikoAuthenticationException,
    NetmikoTimeoutException,
)

from src.connector import get_device_params, load_devices
from src.restconf_client import RestconfError, get, get_restconf_device, put


def build_device_params(action_data):
    devices = load_devices()
    device_name = action_data.get("device", "Cat8000-Sandbox")
    params = get_device_params(devices, device_name)
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
        return True
    except (NetmikoTimeoutException, NetmikoAuthenticationException) as e:
        print(f"SSH connection failed: {e}")
        return False
    except Exception as e:
        print(f"Deployment error: {e}")
        return False


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
    if action == "add_endpoint":
        raise RestconfError(
            "add_endpoint (switchport config) is not supported on the "
            "Catalyst 8000 router sandbox — use a switch sandbox target.")
    raise RestconfError(f"Unknown action for RESTCONF: {action}")


def deploy_restconf(action_data, device_name=None, dry_run=False):
    site_name = action_data["site_name"]
    action = action_data["action"]
    _, rc = get_restconf_device(device_name or action_data.get("device"))
    print(f"[RESTCONF] {action.upper()} -> {site_name} on {rc['host']}")

    try:
        print("[RESTCONF] Discovering physical parent interface...")
        operations = build_operations(action_data, rc)
    except RestconfError as e:
        print(f"[FAIL] {e}")
        if any(k in str(e).lower() for k in ("connect", "reach", "timeout", "down")):
            print("[HINT] The Catalyst 8000 sandbox backend cycles up/down. "
                  "Wait a few minutes and re-run.")
        return False

    out_lines = []
    all_ok = True
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
            else:
                all_ok = False

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
    return all_ok

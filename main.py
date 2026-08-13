import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import yaml

from src.connector import connect_test, get_device_params, load_devices
from src.deployer import deploy, deploy_restconf
from src.generator import render_config
from src.parser import collect_config, collect_config_restconf, scan_compliance, print_compliance_report
from src.restconf_client import connect_test_restconf, get_restconf_device


def load_inventory(filepath="config/branches.yaml"):
    with open(filepath, "r") as f:
        return yaml.safe_load(f)


def cmd_connect(args):
    print("\n=== CONNECTION TEST ===\n")
    if args.mode == "ssh":
        print("[Mode] SSH (requires :22 reachable — blocked on Company network)\n")
        ok = connect_test(device_name=args.device)
    else:
        print("[Mode] RESTCONF over HTTPS :443 (default on Company network)\n")
        ok = connect_test_restconf(device_name=args.device)
    return 0 if ok else 1


def cmd_provision(args):
    data = load_inventory(args.inventory)
    actions = data.get("provisioning", [])

    if not actions:
        print("No provisioning actions found in inventory.")
        return 1

    print(f"\n{'=' * 60}")
    print(f"  Company NETWORK AUTO-PROVISIONING ENGINE")
    print(f"{'=' * 60}")
    print(f"Actions to execute: {len(actions)}")
    print(f"Driver: {args.driver.upper()}")
    if args.dry_run:
        print("Mode: DRY RUN (no network changes)\n")
    else:
        print("Mode: LIVE DEPLOY\n")

    for item in actions:
        action = item["action"]
        site_name = item["site_name"]
        print(f"\n--- [{action.upper()}] {site_name} ---")

        if args.driver == "restconf":
            deploy_restconf(item, device_name=item.get("device"), dry_run=args.dry_run)
            continue

        device_params = get_device_params(load_devices(), item.get("device"))
        item.setdefault("username", device_params["username"])
        item.setdefault("password", device_params["password"])
        item.setdefault("secret", device_params["secret"])

        config_text = render_config(action, item)
        print(config_text)

        deploy(item, config_text, generate_only=args.dry_run)

    print(f"\n{'=' * 60}")
    print(f"  All actions completed.")
    print(f"{'=' * 60}")
    return 0


def cmd_collect(args):
    print("\n=== COLLECTING RUNNING CONFIGS ===\n")
    if args.driver == "ssh":
        devices = load_devices()
        selected = [get_device_params(devices, args.device)] if args.device else devices
        for dev in selected:
            collect_config(dev)
    else:
        _, rc = get_restconf_device(args.device)
        collect_config_restconf(rc)
    return 0


def cmd_scan(args):
    print("\n=== RUNNING COMPLIANCE SCAN ===\n")
    log_dir = args.logs
    if not os.path.exists(log_dir):
        print(f"No {log_dir}/ directory found. Run 'collect' first.")
        return 1

    scanned = 0
    for fname in sorted(os.listdir(log_dir)):
        if "running_config" in fname and fname.endswith(".txt"):
            filepath = os.path.join(log_dir, fname)
            with open(filepath) as f:
                config_text = f.read()
            print(f"\nScanning: {fname}")
            results = scan_compliance(config_text)
            print_compliance_report(results)
            scanned += 1

    if scanned == 0:
        print("No running-config files found. Run 'collect' first.")
        return 1
    return 0


def cmd_setup(args):
    """First-run vault setup: store encrypted device credentials in SQLite."""
    import getpass

    from src import db

    db.init()
    from src.connector import connect_test  # noqa: PLC0415

    print("\n=== SECURE VAULT SETUP (data/CAT8k-SYNC.db) ===")
    print("Credentials are encrypted with a Fernet key in data/.secret —")
    print("the GUI profile page and the CLI share this same vault.\n")

    if not db.has_user() and not args.no_identity:
        username = input("Dashboard username (optional, blank to skip) [%s]: "
                         % (args.username or "admin")) or (args.username or "admin")
        passphrase = getpass.getpass("Dashboard passphrase (optional): ")
        if passphrase:
            digest, salt = db.hash_password(passphrase)
            db.save_user(username, password_hash=digest, password_salt=salt)
        else:
            db.save_user(username)
        print(f"[OK] identity '{username}' saved (free login if no passphrase)\n")

    name = input(f"Device name [{args.name}]: ") or args.name
    host = input(f"Host [{args.host}]: ") or args.host
    username = input(f"Device username [{args.username}]: ") or args.username
    password = getpass.getpass("Device password: ")
    secret = getpass.getpass("Enable secret (blank = same as password): ") or password

    db.save_device({
        "name": name, "host": host, "username": username,
        "password": password, "secret": secret,
        "https": True, "verify_ssl": False, "restconf_port": 443,
    })
    db.log_event("INFO", "SETUP", "vault initialized via CLI setup")
    print(f"\n[OK] device '{name}' encrypted into the vault.")

    if not args.skip_test:
        print("\nVerifying RESTCONF reachability...")
        ok = connect_test_restconf()
        print("\n[OK] connection test PASSED" if ok else
              "\n[WARN] connection test FAILED — check host/credentials")
        return 0 if ok else 1
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Company Network Automation Engine — Cisco DevNet Sandbox targets"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_connect = sub.add_parser("connect", help="Test connectivity to target devices")
    p_connect.add_argument("--device", help="Device name from config/devices.yaml")
    p_connect.add_argument("--mode", choices=["restconf", "ssh"], default="restconf",
                           help="Driver to test (default: restconf over HTTPS :443)")
    p_connect.set_defaults(func=cmd_connect)

    p_prov = sub.add_parser("provision", help="Generate and/or push provisioning configs")
    p_prov.add_argument("--inventory", default="config/branches.yaml")
    p_prov.add_argument("--driver", choices=["restconf", "ssh"], default="restconf",
                        help="Deployment driver (default: restconf)")
    p_prov.add_argument("--dry-run", action="store_true",
                        help="Generate configs/payloads only (no network changes)")
    p_prov.set_defaults(func=cmd_provision)

    p_collect = sub.add_parser("collect", help="Pull running configs from devices")
    p_collect.add_argument("--device", help="Device name from config/devices.yaml")
    p_collect.add_argument("--driver", choices=["restconf", "ssh"], default="restconf",
                           help="Collection driver (default: restconf)")
    p_collect.set_defaults(func=cmd_collect)

    p_scan = sub.add_parser("scan", help="Compliance scan on collected configs")
    p_scan.add_argument("--logs", default="logs")
    p_scan.set_defaults(func=cmd_scan)

    p_setup = sub.add_parser("setup", help="Store encrypted device credentials "
                                           "in the SQLite vault (first run)")
    p_setup.add_argument("--name", default="Cat8000-Sandbox")
    p_setup.add_argument("--host", default="devnetsandboxiosxec8k.cisco.com")
    p_setup.add_argument("--username", default="reqasse")
    p_setup.add_argument("--skip-test", action="store_true",
                         help="Do not run the RESTCONF reachability test")
    p_setup.add_argument("--no-identity", action="store_true",
                         help="Skip the dashboard identity step")
    p_setup.set_defaults(func=cmd_setup)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()

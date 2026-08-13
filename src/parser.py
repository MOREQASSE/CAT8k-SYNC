import json
import os
import re
from datetime import datetime

from netmiko import ConnectHandler, NetmikoTimeoutException, NetmikoAuthenticationException

from src.restconf_client import RestconfError, get


SHOW_COMMANDS = {
    "running_config": "show running-config",
    "ip_interface_brief": "show ip interface brief",
    "ip_route": "show ip route",
    "ip_ospf_neighbor": "show ip ospf neighbor",
}


def collect_config(device_params, log_dir="logs"):
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    results = {}

    try:
        print(f"Connecting to {device_params['host']} for config collection...")
        conn = ConnectHandler(**device_params)
        conn.enable()

        for label, command in SHOW_COMMANDS.items():
            output = conn.send_command(command)
            results[label] = output

            filepath = os.path.join(log_dir, f"{device_params['host']}_{label}_{timestamp}.txt")
            with open(filepath, "w") as f:
                f.write(f"Device: {device_params['host']}\n")
                f.write(f"Command: {command}\n")
                f.write(f"Timestamp: {timestamp}\n")
                f.write("=" * 60 + "\n")
                f.write(output)
            print(f"Saved {label} to {filepath}")

        conn.disconnect()
    except (NetmikoTimeoutException, NetmikoAuthenticationException) as e:
        print(f"Connection failed to {device_params['host']}: {e}")
    except Exception as e:
        print(f"Error collecting from {device_params['host']}: {e}")

    return results


def flatten_json(obj, prefix=""):
    """Flatten a nested JSON/YANG tree into 'path: value' text lines."""
    lines = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, (dict, list)):
                lines.extend(flatten_json(v, key))
            else:
                lines.append(f"{key}: {v}")
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            lines.extend(flatten_json(item, f"{prefix}[{i}]"))
    else:
        lines.append(f"{prefix}: {obj}")
    return lines


def collect_config_restconf(restconf_params, log_dir="logs"):
    """Fetch running config + operational state via RESTCONF and cache to disk."""
    os.makedirs(log_dir, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    host = restconf_params["host"]
    results = {}

    endpoints = {
        "running_config": "Cisco-IOS-XE-native:native",
        "interfaces_oper": "Cisco-IOS-XE-interfaces-oper:interfaces",
        "ospf_oper": "Cisco-IOS-XE-ospf-oper:ospf-oper-data",
    }

    try:
        print(f"Fetching state from {host} via RESTCONF...")
        for label, path in endpoints.items():
            try:
                data = get(restconf_params, path)
                results[label] = data
            except RestconfError as e:
                print(f"  [WARN] {label}: {e}")
                continue

            filepath = os.path.join(log_dir, f"{host}_{label}_{timestamp}.json")
            with open(filepath, "w") as f:
                json.dump(data, f, indent=2)
            print(f"Saved {label} -> {filepath}")

        if "running_config" in results:
            text_path = os.path.join(
                log_dir, f"{host}_running_config_{timestamp}.txt"
            )
            with open(text_path, "w") as f:
                f.write("\n".join(flatten_json(results["running_config"])))
            print(f"Saved flattened config for compliance scan -> {text_path}")

    except Exception as e:
        print(f"Error collecting from {host}: {e}")

    return results


def _find(lines, *patterns):
    """First matching line (case-insensitive) for any of the patterns."""
    for line in lines:
        for p in patterns:
            if re.search(p, line, re.IGNORECASE):
                return line
    return None


def _find_all(lines, pattern):
    return [line for line in lines if re.search(pattern, line, re.IGNORECASE)]


def _evidence(*lines):
    """Compact, safe evidence text (max 3 lines, truncated)."""
    out = []
    for l in lines:
        if not l:
            continue
        l = l.strip()
        if len(l) > 150:
            l = l[:150] + "…"
        out.append(l)
        if len(out) >= 3:
            break
    return " | ".join(out)


def scan_compliance(config_text):
    """Hardening audit over the flattened running-config (YANG 'path: value'
    lines OR plain CLI text). Every rule returns a stable dict:
    {id, check, category, severity, status, evidence, remediation_id}.

    Categories follow the classic hardening families (AAA/auth, transport,
    management plane, monitoring, services). remediation_id only for the
    checks the engine can write back via RESTCONF (see gui/engine.py)."""
    lines = config_text.splitlines()
    text = config_text.lower()
    results = []
    W = "WARN"
    F = "FAIL"
    P = "PASS"

    def add(check_id, check, category, severity, status, evidence, remediation_id=None):
        results.append({
            "id": check_id,
            "check": check,
            "category": category,
            "severity": severity,
            "status": status,
            "evidence": evidence,
            "remediation_id": remediation_id,
        })

    # ---- TRANSPORT & SESSION ----
    vty_transport = _find_all(lines, r"line\.vty|line vty")
    telnet_lines = _find_all(lines, r"transport.*input.*(telnet|all)")
    ssh_line = _find(lines, r"ip\.ssh\.version|ip ssh version")
    if ssh_line and re.search(r"(ip\.ssh\.version|ip ssh version)[:\s]*[12]", ssh_line):
        version = re.search(r"(?:ip\.ssh\.version|ip ssh version)[:\s]*(\d+)", ssh_line)
        if version and int(version.group(1)) >= 2:
            add("ssh-version", "SSH version 2 enforced", "TRANSPORT & SESSION",
                "high", P, _evidence(ssh_line))
        else:
            add("ssh-version", "SSH version 2 enforced", "TRANSPORT & SESSION",
                "critical", F, _evidence(ssh_line), "ssh-version")
    else:
        add("ssh-version", "SSH version 2 enforced", "TRANSPORT & SESSION",
            "high", W, _evidence(ssh_line) or "no ip ssh version statement")

    if telnet_lines:
        add("vty-transport", "No unsafe Telnet transport on lines",
            "TRANSPORT & SESSION", "critical", F,
            _evidence(*telnet_lines), "vty-transport")
    elif vty_transport and _find_all(lines, r"transport.*input.*ssh"):
        add("vty-transport", "No unsafe Telnet transport on lines",
            "TRANSPORT & SESSION", "critical", P,
            _evidence(*_find_all(lines, r"transport.*input.*ssh")[:2]))
    else:
        add("vty-transport", "No unsafe Telnet transport on lines",
            "TRANSPORT & SESSION", "high", W,
            "vty present but no explicit transport input restriction")

    timeout_lines = _find_all(lines, r"exec-timeout|exec_timeout")
    vty_present = bool(vty_transport)
    if timeout_lines and vty_present:
        add("exec-timeout", "Idle session timeout (exec-timeout) set on lines",
            "TRANSPORT & SESSION", "medium", P, _evidence(*timeout_lines[:2]))
    elif vty_present:
        add("exec-timeout", "Idle session timeout (exec-timeout) set on lines",
            "TRANSPORT & SESSION", "medium", F,
            "line vty present without exec-timeout", "exec-timeout")
    else:
        add("exec-timeout", "Idle session timeout (exec-timeout) set on lines",
            "TRANSPORT & SESSION", "low", W, "no line vty configured")

    # ---- AUTHENTICATION & AAA ----
    enc_line = _find(lines, r"service\.password-encryption|service password-encryption")
    add("password-encryption", "service password-encryption enabled",
        "AUTH & AAA", "high", P if enc_line else F,
        _evidence(enc_line) or "service password-encryption missing",
        "password-encryption")

    secret_lines = _find_all(lines, r"enable\.secret|enable secret")
    weak_secret = _find_all(lines,
        r"enable.*secret.*(type[:\s]*[07]|encryption[:\s]*[07])|enable\.secret\.type:\s*[07]")
    pw_lines = _find_all(lines, r"enable\.password|enable password")
    if secret_lines and not weak_secret:
        add("enable-secret", "enable secret set with strong hash (type 9/5)",
            "AUTH & AAA", "critical", P, _evidence(*secret_lines[:2]))
    elif secret_lines:
        add("enable-secret", "enable secret set with strong hash (type 9/5)",
            "AUTH & AAA", "critical", F,
            _evidence(*weak_secret[:2]))
    elif pw_lines:
        add("enable-secret", "enable secret set with strong hash (type 9/5)",
            "AUTH & AAA", "critical", F,
            "only legacy 'enable password' found — cleartext/weak", "enable-secret")
    else:
        add("enable-secret", "enable secret set with strong hash (type 9/5)",
            "AUTH & AAA", "critical", F, "enable secret missing", "enable-secret")

    aaa_new = _find(lines, r"aaa.*new-model|aaa\.Cisco-IOS-XE-aaa:new-model")
    auth_lists = _find_all(lines, r"aaa.*authentication\.login|authentication login")
    if aaa_new and auth_lists:
        add("aaa-auth", "AAA new-model with login method (TACACS+/RADIUS/local)",
            "AUTH & AAA", "high", P, _evidence(aaa_new, auth_lists[0]))
    elif aaa_new:
        add("aaa-auth", "AAA new-model with login method (TACACS+/RADIUS/local)",
            "AUTH & AAA", "high", W, _evidence(aaa_new) or "aaa new-model without auth lists")
    else:
        add("aaa-auth", "AAA new-model with login method (TACACS+/RADIUS/local)",
            "AUTH & AAA", "high", F, "aaa new-model not configured")

    tacacs = _find_all(lines, r"tacacs\.Cisco-IOS-XE-aaa:server|tacacs server")
    tacacs_key = _find_all(lines, r"tacacs.*key\.encryption|tacacs.*key key")
    if tacacs and tacacs_key:
        weak = any(re.search(r"encryption[:\s]*[07]|type[:\s]*[07]", k, re.IGNORECASE) for k in tacacs_key)
        add("tacacs-key", "TACACS+ server key not weak (0/7)",
            "AUTH & AAA", "high", F if weak else P,
            _evidence(*tacacs_key[:2]))
    elif tacacs:
        add("tacacs-key", "TACACS+ server key not weak (0/7)",
            "AUTH & AAA", "medium", W, _evidence(*tacacs[:2]))
    else:
        add("tacacs-key", "TACACS+ server key not weak (0/7)",
            "AUTH & AAA", "low", P, "no TACACS+ configured")

    radius = _find_all(lines, r"radius\.Cisco-IOS-XE-aaa:server|radius server")
    radius_key = _find_all(lines, r"radius.*key\.encryption|radius.*key key")
    if radius and radius_key:
        weak = any(re.search(r"encryption[:\s]*[07]|type[:\s]*[07]", k, re.IGNORECASE) for k in radius_key)
        add("radius-key", "RADIUS server key not weak (0/7)",
            "AUTH & AAA", "high", F if weak else P, _evidence(*radius_key[:2]))
    elif radius:
        add("radius-key", "RADIUS server key not weak (0/7)",
            "AUTH & AAA", "medium", W, _evidence(*radius[:2]))
    else:
        add("radius-key", "RADIUS server key not weak (0/7)",
            "AUTH & AAA", "low", P, "no RADIUS configured")

    users = _find_all(lines, r"username\[|^username ")
    weak_users = [u for u in users if re.search(r"secret\.encryption[:\s]*[027]|type[:\s]*[027]|password[:\s]*\S", u)]
    if users and weak_users:
        add("local-users", "Local accounts use strong secrets only",
            "AUTH & AAA", "high", F, _evidence(*weak_users[:2]))
    elif users:
        add("local-users", "Local accounts use strong secrets only",
            "AUTH & AAA", "medium", P, _evidence(*users[:2]))
    else:
        add("local-users", "Local accounts use strong secrets only",
            "AUTH & AAA", "low", P, "no local users defined")

    # ---- MANAGEMENT PLANE ----
    http_server = _find(lines, r"http\.server:\s*true|ip http server")
    http_secure = _find(lines, r"http\.secure-server:\s*true|ip http secure-server")
    if http_server and not http_secure:
        add("http-plane", "HTTPS-only management plane (no plaintext HTTP)",
            "MANAGEMENT PLANE", "critical", F,
            _evidence(http_server), "http-plane")
    elif http_server:
        add("http-plane", "HTTPS-only management plane (no plaintext HTTP)",
            "MANAGEMENT PLANE", "medium", W,
            _evidence(http_server, http_secure), "http-plane")
    else:
        add("http-plane", "HTTPS-only management plane (no plaintext HTTP)",
            "MANAGEMENT PLANE", "medium", P, "http server not enabled")

    acls = _find_all(lines, r"access-list|ip\.access-list")
    if acls:
        add("mgmt-acl", "Management plane restricted by access-list",
            "MANAGEMENT PLANE", "medium", P, _evidence(*acls[:2]))
    else:
        add("mgmt-acl", "Management plane restricted by access-list",
            "MANAGEMENT PLANE", "medium", W, "no ACL restricting management access")

    dns_line = _find(lines, r"ip\.domain\.lookup")
    if dns_line and "false" in dns_line.lower():
        add("domain-lookup", "IP domain-lookup disabled (anti-DNS poisoning)",
            "MANAGEMENT PLANE", "low", P, _evidence(dns_line))
    elif dns_line:
        add("domain-lookup", "IP domain-lookup disabled (anti-DNS poisoning)",
            "MANAGEMENT PLANE", "low", W, _evidence(dns_line))
    else:
        add("domain-lookup", "IP domain-lookup disabled (anti-DNS poisoning)",
            "MANAGEMENT PLANE", "low", W, "domain lookup enabled by default")

    # ---- MONITORING ----
    snmp = _find_all(lines, r"snmp-server community|snmp-server\.community")
    weak_comm = [s for s in snmp if re.search(r"(public|private)\b", s, re.IGNORECASE)]
    if weak_comm:
        add("snmp-community", "No weak SNMP community strings (public/private)",
            "MONITORING", "critical", F, _evidence(*weak_comm[:2]))
    elif snmp:
        add("snmp-community", "No weak SNMP community strings (public/private)",
            "MONITORING", "medium", W,
            _evidence(*snmp[:2]) or "snmp community without ACL binding")
    else:
        add("snmp-community", "No weak SNMP community strings (public/private)",
            "MONITORING", "low", P, "SNMP community not configured")

    has_logging = bool(_find_all(lines, r"logging.*(host|trap)"))
    logging_line = _find(lines, r"logging.*(host|trap)")
    add("syslog", "Syslog host/trap configured",
        "MONITORING", "medium", P if has_logging else W,
        _evidence(logging_line) or "No syslog tracking configured", "syslog")

    ntp_lines = _find_all(lines, r"ntp\.server|ntp server")
    add("ntp", "NTP server configured (time integrity)",
        "MONITORING", "medium", P if ntp_lines else W,
        _evidence(*ntp_lines[:2]) or "No NTP server configured", "ntp")

    # ---- SERVICES & BANNER ----
    banner_lines = _find_all(lines, r"banner")
    add("banner", "Legal banner (motd/login) set",
        "SERVICES & BANNER", "medium", P if banner_lines else W,
        _evidence(*banner_lines[:2]) or "No banner configured", "banner")

    return results


def print_compliance_report(results):
    print(f"\n{'=' * 60}")
    print(f"  COMPLIANCE SCAN RESULTS")
    print(f"{'=' * 60}")
    for r in results:
        status_icon = "✅" if r["status"] == "PASS" else ("⚠️" if r["status"] == "WARN" else "❌")
        print(f"  {status_icon} [{r['status']}] {r['check']}")
        print(f"     {r.get('evidence') or r.get('detail') or ''}")
    print(f"{'=' * 60}")

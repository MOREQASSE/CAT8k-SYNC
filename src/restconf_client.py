import json
import time

import requests
import urllib3

from src.connector import load_devices, netmiko_params

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

RESTCONF_BASE = "restconf/data"
DEFAULT_HEADERS = {
    "Accept": "application/yang-data+json",
    "Content-Type": "application/yang-data+json",
}


class RestconfError(Exception):
    pass


def restconf_params(device_dict):
    """Extract RESTCONF connection parameters from a device dict."""
    return {
        "host": device_dict.get("host"),
        "username": device_dict.get("username"),
        "password": device_dict.get("password"),
        "https": device_dict.get("restconf_https", True),
        "verify_ssl": device_dict.get("restconf_verify_ssl", False),
        "port": device_dict.get("restconf_port", 443),
    }


def get_restconf_device(device_name=None):
    devices = load_devices()
    if device_name:
        for dev in devices:
            if dev["name"] == device_name:
                return dev, restconf_params(dev)
        raise ValueError(f"Device '{device_name}' not found in config/devices.yaml")
    dev = devices[0]
    return dev, restconf_params(dev)


def build_url(params, path):
    scheme = "https" if params["https"] else "http"
    return f"{scheme}://{params['host']}:{params['port']}/{RESTCONF_BASE}/{path.lstrip('/')}"


def _request(params, method, path, payload=None, timeout=60, retries=3, backoff=5):
    url = build_url(params, path)
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            response = requests.request(
                method,
                url,
                auth=(params["username"], params["password"]),
                headers=DEFAULT_HEADERS,
                json=payload,
                verify=params["verify_ssl"],
                timeout=timeout,
            )
        except requests.RequestException as e:
            last_error = RestconfError(
                f"RESTCONF transport error ({method} {path}) attempt {attempt}: {e}"
            )
            if attempt < retries:
                time.sleep(backoff * attempt)
                continue
            break

        if response.status_code == 502 and attempt < retries:
            print(f"[RETRY] {method} {path} -> HTTP 502 (sandbox backend cycling), "
                  f"retrying in {backoff * attempt}s...")
            last_error = RestconfError(
                f"RESTCONF {method} {path} -> HTTP {response.status_code} "
                f"(backend unavailable) after {attempt} attempt(s)"
            )
            time.sleep(backoff * attempt)
            continue

        if response.status_code >= 300:
            raise RestconfError(
                f"RESTCONF {method} {path} -> HTTP {response.status_code}: "
                f"{response.text[:300]}"
            )
        if response.content:
            try:
                return response.json()
            except ValueError:
                return response.text
        return None
    raise last_error


def get(params, path, timeout=60):
    return _request(params, "GET", path, timeout=timeout)


def put(params, path, payload, timeout=60):
    return _request(params, "PUT", path, payload, timeout=timeout)


def patch(params, path, payload, timeout=60):
    return _request(params, "PATCH", path, payload, timeout=timeout)


def post(params, path, payload, timeout=90):
    return _request(params, "POST", path, payload, timeout=timeout)


def delete(params, path, timeout=60):
    return _request(params, "DELETE", path, timeout=timeout)


def connect_test_restconf(device_name=None, timeout=60):
    """Probe RESTCONF availability: fetch device hostname + interface count."""
    dev, params = get_restconf_device(device_name)
    print("=" * 64)
    print(f"  RESTCONF CONNECTION TEST -> {dev['name']} ({params['host']})")
    print("=" * 64)
    try:
        hostname_data = get(params, "Cisco-IOS-XE-native:native/hostname", timeout=timeout)
        hostname = hostname_data["Cisco-IOS-XE-native:hostname"]
        print(f"[OK] Authenticated (user {params['username']})")
        print(f"[OK] Device hostname: {hostname}")

        iface_data = get(
            params, "Cisco-IOS-XE-native:native/interface", timeout=timeout
        )
        ifaces = iface_data.get("Cisco-IOS-XE-native:interface", {})
        count = sum(len(v) for v in ifaces.values() if isinstance(v, list))
        print(f"[OK] Interface groups readable ({count} interfaces)")
        print(f"[OK] {dev['name']}: RESTCONF connection test PASSED")
        return True
    except RestconfError as e:
        print(f"[FAIL] {dev['name']}: {e}")
        return False

# Security

CAT8k-SYNC handles device credentials and can change network configuration, so its security posture is worth stating explicitly: what is encrypted, where the keys live, what is masked, and what the accepted limitations are.

## Credentials at rest

Device passwords and enable secrets are stored encrypted in the SQLite vault, never in plain text. `src/vault.py` uses Fernet (AES-128-CBC with HMAC, from the `cryptography` package): `save_device` encrypts the password and secret before writing, and `get_device_plain` is the only place that decrypts, at call time, for the transport session. The Fernet key lives in `data/.secret`, which is excluded from version control and is not stored inside the database. Deleting `data/.secret` makes the vault unreadable; keep a backup if the database must survive a key rotation.

The dashboard identity is protected with PBKDF2: `hash_password` derives a salted digest and `verify_password` compares digests, so the database never contains a recoverable dashboard password.

## Credentials in motion

Passwords leave the process only in two directions: into the transport session (SSH, RESTCONF, NETCONF) and, for the VPN, into the vendor client's stdin. `src/vpn.py` drives the Cisco Secure Client CLI with the password fed through `subprocess` stdin only; it is never logged, echoed, or stored in a temp file. The VPN password does not even cross the JavaScript boundary in plain text: the bridge methods that return credentials pass through `_masked_creds` and `_masked_vpn`, which replace secrets with placeholders before the response leaves Python. A page inspector sees stars, not secrets.

## Interface exposure

The web server binds `127.0.0.1:17771` only, so the UI and the API bridge are unreachable from other machines. pywebview mode never makes the port reachable either, since the window talks to the same loopback server. The accepted limitation is that the HTTP shim does not validate the `Origin` or `Host` header, which is fine for a loopback-only service: a browser tab on the same machine could issue API calls, but no remote party can reach the port at all. If the app is ever made to bind a non-loopback address, header validation becomes mandatory before any exposure.

## TLS to the device

The sandbox presents a self-signed certificate, so the platform ships with `restconf_verify_ssl: false` for that target. This is a per-device flag in `config/devices.yaml`, not a global switch: a device with a proper certificate should be configured with `restconf_verify_ssl: true`. Enabling verification is the recommended setting for any device that supports it, because with verification off, credentials travel over an authenticated-but-unverified channel.

## Command safety

The operations toolbox runs device commands from the UI. Every command goes through `cliRun`, which runs the command over the device CLI and returns the output, and nothing in the platform pipes the output back into a shell, so there is no command-injection surface on the host. The provisioning payloads come from the project's own templates and the inventory file; treat `branches.yaml` and `config/templates/*.j2` as executable input, and review them before adding an action.

## The ledger

Every scan, provisioning action, and login-adjacent event appends to the audit ledger with an actor and a SHA-256 chain, described in [data.md](data.md). `verifyAudit` replays the chain and reports any broken link. The ledger proves that history was not edited, provided the attacker never had write access to the database in the first place: the chain detects tampering after the fact, it does not prevent it.

## Environment fallback

`.env.example` documents the `CAT8000_USERNAME`, `CAT8000_PASSWORD`, and `CAT8000_SECRET` fallback for scripts and CI. The vault is always preferred; the fallback is only consulted when no device record exists. Keep `.env` out of version control (`.gitignore` already excludes it) and treat the fallback as a development convenience, not a deployment pattern.
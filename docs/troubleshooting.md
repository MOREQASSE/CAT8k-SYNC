# Troubleshooting

Most failures against this platform come from the shared sandbox, not from the code. This page lists the behaviours observed during development and the remedies that worked.

## The sandbox is a shared, resettable device

The public DevNet Sandbox is a single always-on instance that everyone shares. The reserved instances are separate but reset every two to three days, and a reset silently changes the device's state: your branches vanish, the hostname returns to factory, and interface names can differ between instances (`GigabitEthernet0/0/0` on one, `GigabitEthernet0/1/0` on another). When a provisioning action or a scan fails for reasons that make no sense, check whether the device was reset first. The remedy is to re-run the setup step against the current instance and adjust the interface names in `config/branches.yaml`.

## RESTCONF returns 502 or drops sessions

During instance reloads and reservation changes the RESTCONF endpoint answers with 502 or resets the connection. The client raises a transport error instead of a misleading success, and the UI surfaces it in the operation log. Wait a few minutes and retry; if the failure persists, the instance is gone and a fresh one must be selected.

## SSH on port 22 is filtered

On the Company network, outbound SSH to the sandbox is blocked, which is why `connect --mode ssh` fails there while `connect --mode restconf` succeeds. RESTCONF over HTTPS on 443 is the default transport everywhere for this reason. SSH remains useful in environments where it is permitted, and the code paths are shared, so nothing else changes when you switch.

## NETCONF covers a subset of modules

The sandbox exposes a restricted NETCONF implementation: module listing works, but schema retrieval and filter-based `get` succeed only for modules the device actually publishes. An unknown module yields an error rather than an empty result. The models explorer surfaces exactly what the device publishes, so treat a missing module as a device limitation, not a bug.

## The VPN connection is held by the tray UI

Cisco Secure Client's tray process (`csc_ui.exe`, `vpnui.exe`) keeps the connection function and makes the CLI fail with "acquired by another application" (or the French equivalent). `src/vpn.py` closes those processes before driving the CLI and the UI restarts them on next login. If a manual connect fails, close the tray app or re-run from the profile view. The tunnel state shown by the platform is the TCP probe of the device's RESTCONF port, not the client's own claim, so a green tunnel status means traffic actually reaches the device.

## Deleting a subinterface needs a different URI

The sandbox rejects the generic subinterface delete on some instances and requires the specific dot1Q deletion URI. `src/deployer.py` handles this through the parent-interface resolver and the delete operations in the RESTCONF client; if a cleanup fails, confirm the instance's naming and re-run the dry-run before retrying.

## The web app does not start

Check three things in order: the port is free (the server binds `127.0.0.1:17771`), pywebview and its backend are installed (`pip show pywebview`), and the version contract still matches (`probe.py` expects the build string `0.4.0-web` in `api.state()`). If the window fails but the server starts, any browser at `http://127.0.0.1:17771` works, because the HTTP shim speaks to the same `Api` class. If the UI boots but views misbehave, run `gui/web/tools/qa.py`: its verdict tells you which view and which error class broke.

## The vault becomes unreadable

Deleting `data/.secret` or restoring the database without its key makes every decryption fail with a Fernet error. There is no recovery path: keep `data/` (both the database and the key) in a backup, and treat the pair as one unit. To start clean, delete both `data/CAT8k-SYNC.db` and `data/.secret` and re-run setup.

## Logs to consult

Runtime output goes to the console and to `events_log` in the database; provisioning details land in `actions_log`; the audit view replays the ledger. Collected configs and the baseline live in `logs/` as text files. When something fails, read `events_log` first: it is the only log that both the CLI and the web app write to, so it always tells both sides of the story.
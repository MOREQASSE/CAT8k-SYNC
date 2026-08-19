# CLI reference

The command-line interface lives in `main.py` and mirrors the web app's operations. Every command reads credentials from the same vault as the web app, so a device configured through the profile page is immediately usable from the terminal. Run any command with `--help` for the full option list.

## setup

Stores the dashboard identity and the device credentials in the encrypted vault and verifies RESTCONF reachability.

```
venv\Scripts\python.exe main.py setup
```

The command prompts for a dashboard username and passphrase, then for device name, host, username, password, and enable secret. The secret defaults to the password when left blank. Connection parameters are fixed at HTTPS on port 443 with TLS verification off, matching the sandbox. Flags: `--name`, `--host`, `--username` preset the defaults, `--skip-test` skips the reachability test, and `--no-identity` skips the dashboard identity step. Exit code 0 means the connection test passed.

## connect

Tests reachability to a device, either over RESTCONF or SSH.

```
venv\Scripts\python.exe main.py connect --device Cat8000-Sandbox --mode restconf
venv\Scripts\python.exe main.py connect --mode ssh
```

`--mode` accepts `restconf` (default) or `ssh`. Without `--device`, the command uses the device stored in the vault. SSH on port 22 is filtered on the Company network, so `--mode ssh` can fail there while RESTCONF on 443 succeeds; this is a network policy, not a platform fault. Exit code 1 means the connection failed.

## collect

Pulls the running configuration from the device and saves it under `logs/`.

```
venv\Scripts\python.exe main.py collect
venv\Scripts\python.exe main.py collect --device Cat8000-Sandbox --driver ssh
```

Without `--device`, every device in `config/devices.yaml` is collected. With `--driver restconf` (default) the collection runs through the RESTCONF client and stores a structured snapshot in the database in addition to the text file; with `--driver ssh` it uses Netmiko and writes only the text file.

## scan

Runs the compliance scanner over the collected running configs.

```
venv\Scripts\python.exe main.py scan
venv\Scripts\python.exe main.py scan --logs logs
```

The scanner reads every file named `running_config*.txt` in the `logs/` directory (or the `--logs` directory), checks the configuration against the compliance rules, and prints a per-rule report. Run `collect` first: the command refuses to run on an empty log directory.

## provision

Generates and optionally pushes provisioning configuration from `config/branches.yaml`.

```
venv\Scripts\python.exe main.py provision --dry-run
venv\Scripts\python.exe main.py provision --driver restconf
```

Every provisioning action in the inventory is executed in order. `--dry-run` renders the payloads and prints them without touching the network; this is the recommended first step for any new action. `--driver` selects the deployment path: `restconf` (default) sends the Jinja2 payloads as RESTCONF operations, while `ssh` renders CLI-style config text through the generator and pushes it with Netmiko. The actions themselves are described in [inventory.md](inventory.md).

## Exit codes and logging

Commands that perform a test return 0 on success and 1 on failure or when there is nothing to do. Every command appends to `events_log` in the database, and provisioning appends to `actions_log` and the audit ledger, so the audit view in the web app shows CLI activity too.
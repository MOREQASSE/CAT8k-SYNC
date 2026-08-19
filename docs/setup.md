# Setup

This page covers installing the project, the first-run procedure, and the target devices you can point it at.

## Environment

Create a virtual environment inside the repository and install the runtime dependencies. Python 3.10 or newer is required.

```
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
```

The QA suite needs Playwright on top. Install `requirements-dev.txt` and the Chromium browser once:

```
venv\Scripts\python.exe -m pip install -r requirements-dev.txt
venv\Scripts\python.exe -m playwright install chromium
```

## First run

Start the web app from the repository root:

```
venv\Scripts\python.exe gui\webapp.py
```

On the first run the profile view asks for a dashboard identity and the device credentials. The device block stores the host, username, password, and enable secret encrypted with a Fernet key in `data/.secret` inside `data/CAT8k-SYNC.db`. The default values in the form point at the public DevNet Sandbox:

| Field | Default |
| --- | --- |
| Device name | `Cat8000-Sandbox` |
| Host | `devnetsandboxiosxec8k.cisco.com` |
| Username | your DevNet Sandbox username |
| Password | your DevNet Sandbox password |
| RESTCONF | HTTPS, port 443, TLS verification off |

The same first-run can be done from the terminal with `python main.py setup`; see [cli.md](cli.md).

## Target devices

Two kinds of targets exist in the configuration. `config/devices.yaml` lists devices by name with their transport parameters. The repository ships with one entry, `Cat8000-Sandbox`, pointing at the always-on public sandbox. Its parameters are hostname, SSH port 22, RESTCONF on 443 with TLS verification disabled, and `fast_cli` with a global delay factor of 2 for the SSH path.

`config/branches.yaml` describes the network topology: an existing infrastructure with two sites (`Maroc-Phosphore1`, `Maroc-Phosphore2`) plus provisioning actions for a new site (`Maroc-Chimie`). Each provisioning action names the target device, the WAN and trunk interfaces, the department VLAN, and the addressing scheme. See [inventory.md](inventory.md) for the full format.

## Environment-variable fallback

If the vault is empty, the platform falls back to environment variables `CAT8000_USERNAME`, `CAT8000_PASSWORD`, and `CAT8000_SECRET`, documented in `.env.example`. This path is intended for scripts and CI, not for daily use: the vault is always preferred and the fallback is skipped once a device record exists.

## What gets created

The first run creates three things: `data/CAT8k-SYNC.db` (SQLite database and vault), `data/.secret` (the Fernet key, protected by your passphrase), and `logs/` for baseline files and collected configs. All three are excluded from version control by `.gitignore`. Removing the database and the key resets the platform to the first-run state; there is no migration story, so back the database up if it holds history you want to keep.

## Target-device caveats

The public sandbox is a shared device: your configuration persists while the instance is alive, and the reserved instances (which are the same software) reset every two to three days. Interface names can differ between instances (for example `GigabitEthernet0/0/0` versus `GigabitEthernet0/1/0`), so a provisioning action written for one instance may need its interface names adjusted for another. [troubleshooting.md](troubleshooting.md) lists the observed behaviours and their remedies.
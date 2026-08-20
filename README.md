<p align="center">
  <img src="gui/icons/LOGO.png" alt="CAT8k-SYNC logo" width="170">
</p>

<h1 align="center">CAT8k · SYNC</h1>

<p align="center">
  <b>Telemetry, provisioning, audit and analytics for the Cisco Catalyst 8000v — from a browser window or a shell.</b>
</p>

<p align="center">
  <a href="#quick-start"><img src="https://img.shields.io/badge/python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white"></a>
  <a href="docs/webapp.md"><img src="https://img.shields.io/badge/interface-web%20%2B%20cli-0ea5e9?style=flat-square"></a>
  <a href="docs/inventory.md"><img src="https://img.shields.io/badge/restconf-443%20primary-16a34a?style=flat-square"></a>
  <a href="docs/qa.md"><img src="https://img.shields.io/badge/qa-playwright%20suite-ef4444?style=flat-square"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-Apache%202.0-D22128?style=flat-square"></a>
</p>

<p align="center">
  <i>A final-year engineering project (PFA) — built to run against the Cisco DevNet Sandbox, at home, or on any reachable Catalyst 8000v.</i>
</p>

---

## What this is

CAT8k-SYNC is a small network-automation platform for a single Cisco Catalyst 8000v edge router. It collects telemetry and configuration over RESTCONF, with NETCONF and SSH available as secondary transports, stores every observation in a local SQLite database, detects drift, and provisions branch networks through Jinja2-templated RESTCONF operations. Credentials are never stored in plain text: they live in an encrypted SQLite vault and are used only at call time. Every provisioning action and every scan lands in a tamper-evident audit ledger.

The project has two interfaces, both documented in full in `docs/`. The web app (`gui/webapp.py`) is the primary one: it serves the UI over a loopback HTTP server and opens it either in a pywebview native window or in your default browser. The CLI (`main.py`) covers the same ground from a terminal. There is no desktop shell and no separate GUI framework dependency; the entire interface stack is web plus command line.

## Quick start

1. Create a virtual environment and install the runtime dependencies.

```
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
```

2. Launch the web app from the repository root. It binds to `127.0.0.1:17771` only, so no network exposure is involved.

```
venv\Scripts\python.exe gui\webapp.py
```

3. On first run, the app asks for a passphrase and the device credentials, then writes the encrypted vault and the `data/CAT8k-SYNC.db` database. Everything after that works without a passphrase prompt until the next session.

For the command-line route, see `docs/cli.md`. The default target device is the public Cisco DevNet Sandbox IOS XE on Catalyst 8000v (always-on, `devnetsandboxiosxec8k.cisco.com`), which works out of the box with the credentials you enter at setup.

## Repository layout

```
CAT8k-SYNC/
├── main.py                 CLI entry point (setup, connect, collect, scan, provision)
├── probe.py                pywebview bridge health probe (web UI ↔ Python)
├── requirements.txt        runtime dependencies
├── requirements-dev.txt    QA-only dependencies (Playwright)
├── src/                    engine backend: connector, parser, deployer, vault, db, ...
├── gui/
│   ├── webapp.py           web server (127.0.0.1:17771) + Python↔JS API bridge
│   ├── engine.py           orchestrator shared by web app and CLI
│   └── web/                static UI (HTML/CSS/JS), icon sprite, Playwright probes
├── config/
│   ├── devices.yaml        device inventory (host, transports, RESTCONF options)
│   ├── branches.yaml       branch network definitions + provisioning actions
│   └── templates/          Jinja2 payload templates (add_branch, add_subdept, ...)
├── tools/                  standalone device probes (datastores, NETCONF, ...)
├── docs/                   full documentation (architecture, setup, CLI, security, ...)
└── data/                   SQLite database + vault key (created at first run)
```

## Documentation

| Page | Covers |
| --- | --- |
| [docs/index.md](docs/index.md) | Reading guide, project goals, prerequisites |
| [docs/architecture.md](docs/architecture.md) | Layers, modules, transports, data flow |
| [docs/setup.md](docs/setup.md) | Environment, first run, device targets |
| [docs/cli.md](docs/cli.md) | Every `main.py` command with examples |
| [docs/webapp.md](docs/webapp.md) | Web UI, views, API bridge, health probe |
| [docs/inventory.md](docs/inventory.md) | `devices.yaml`, `branches.yaml`, provisioning actions |
| [docs/data.md](docs/data.md) | SQLite schema, telemetry series, audit ledger |
| [docs/security.md](docs/security.md) | Vault, masking, threat model |
| [docs/qa.md](docs/qa.md) | Probe scripts, Playwright suite, observed results |
| [docs/troubleshooting.md](docs/troubleshooting.md) | Known sandbox behaviours and fixes |

## Quality assurance

A Playwright suite (`gui/web/tools/qa.py`) exercises every view of the web UI, and a set of probe scripts (`gui/web/tools/`, `tools/`) validates the Python side against the live device. Both are described in `docs/qa.md`. Screenshots captured during the runs live in `gui/web/screenshots/`.

## License

Licensed under the [Apache License, Version 2.0](LICENSE). Logos and trademarks — including Cisco — belong to their respective owners.

## Project context

This repository was developed as a final-year engineering project (PFA). The accompanying report documents the design, the functional chains, and the measured performance (provisioning cycle of about 5 seconds, telemetry and drift tracking over several weeks). The code is a working prototype against a real device, not a simulator: every number in the report comes from runs against the Cisco DevNet Sandbox.
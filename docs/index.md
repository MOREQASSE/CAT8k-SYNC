# CAT8k-SYNC documentation

CAT8k-SYNC automates a Cisco Catalyst 8000v edge router: it collects telemetry and configuration over RESTCONF, stores everything in a local SQLite database, watches for drift against a saved baseline, and provisions branch networks from Jinja2 templates. Credentials are encrypted at rest in a SQLite vault, and every operation is appended to a tamper-evident audit ledger. The project targets the Cisco DevNet Sandbox IOS XE on Catalyst 8000v, which means it runs against a real device with no lab hardware.

The platform has two interfaces, and they share the same engine. The web app in `gui/webapp.py` serves the UI on a loopback-only HTTP server (`127.0.0.1:17771`) and opens it in a pywebview native window or a plain browser. The CLI in `main.py` covers the same operations from a terminal. Both read the same vault and the same database, so work done in one is visible in the other.

## Reading guide

| Page | Read it when |
| --- | --- |
| [architecture.md](architecture.md) | You want to understand how the pieces fit before touching code |
| [setup.md](setup.md) | You are installing the project or preparing a target device |
| [cli.md](cli.md) | You want the exact CLI commands and their options |
| [webapp.md](webapp.md) | You are running or extending the web interface |
| [inventory.md](inventory.md) | You are adding devices, branches, or provisioning actions |
| [data.md](data.md) | You work with the SQLite schema, telemetry, or the audit ledger |
| [security.md](security.md) | You care about how credentials and the ledger are protected |
| [qa.md](qa.md) | You want to run the probes and the UI regression suite |
| [troubleshooting.md](troubleshooting.md) | Something misbehaves against the sandbox |

## Prerequisites

Python 3.10 or newer on Windows (the VPN driver and the pywebview launcher are Windows-oriented). No Cisco equipment is required: the public DevNet Sandbox covers the always-on device. The only external dependency beyond the packages in `requirements.txt` is the Playwright browser used by the QA suite (`requirements-dev.txt`).

## Conventions used in these pages

Commands assume PowerShell on Windows and run from the repository root unless stated otherwise. `venv\Scripts\python.exe` is used everywhere the virtual environment is installed inside the project. Paths like `data/` and `logs/` are created at first run and are excluded from version control.
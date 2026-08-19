# Architecture

CAT8k-SYNC is a single-repository Python application with a clean seam between the backend engine and the two front ends. The backend lives in `src/` and is transport-agnostic at the top: the engine orchestrates devices, and the transport layer picks SSH, RESTCONF, or NETCONF per operation. The front ends are thin: the CLI maps subcommands to engine functions, and the web app maps JavaScript calls to `Api` methods over pywebview.

## Layers

The engine layer in `gui/engine.py` is the orchestrator shared by both interfaces. It owns the RESTCONF device handle, the compliance scan pipeline, the provisioning flow, the security posture checks, and the remediation actions. It reads the vault for credentials, writes to `data/CAT8k-SYNC.db` through `src/db.py`, and pushes its progress to the UI through the callback set by the caller.

The domain layer in `src/` is where the work happens.

| Module | Responsibility |
| --- | --- |
| `src/connector.py` | Device inventory loading and SSH reachability tests |
| `src/restconf_client.py` | RESTCONF over HTTPS client, session handling, CRUD verbs |
| `src/netconf_explorer.py` | NETCONF module listing, schema fetch, and filter-based `get` |
| `src/parser.py` | Config collection and compliance scanning |
| `src/deployer.py` | Operation building, payload rendering, RESTCONF deployment |
| `src/generator.py` | CLI-style config generation from templates |
| `src/automation.py` | Drift detection between baseline and current config |
| `src/device_mode.py` | Device-mode resolver used by the UI |
| `src/vault.py` | Fernet encryption and decryption of credentials |
| `src/db.py` | SQLite schema, storage, and the audit ledger chain |
| `src/vpn.py` | Cisco Secure Client / AnyConnect CLI driver with a TCP tunnel probe |

The presentation layer has two faces. `gui/webapp.py` runs a `ThreadingHTTPServer` bound to `127.0.0.1:17771`, serves the static UI from `gui/web/`, and exposes the `Api` class to JavaScript. In pywebview mode, `Api` methods are called directly through the bridge; in browser mode, the HTTP shim in `do_GET` maps requests under `/api/` to the same `Api` instance. The CLI in `main.py` is the other face: each subcommand calls the same domain functions, which is why results are identical in both interfaces.

## Transports

RESTCONF over HTTPS on port 443 is the primary transport and the only one used for provisioning. SSH (port 22) is supported for config collection and compliance scans, and NETCONF (port 830) is used read-only for module exploration and schema retrieval. The default target `Cat8000-Sandbox` is the public DevNet Sandbox device, whose TLS certificate is self-signed; the platform therefore ships with `verify_ssl: false` for that target by default, which is documented in [security.md](security.md).

## Data flow

A collection cycle goes through four steps. The engine pulls the running configuration and interface state over RESTCONF, parses the payload into structured records, stores a snapshot with per-interface history in SQLite, and compares the current configuration with the baseline file in `logs/baseline_running_config.txt`. Every step is logged to `events_log` and to the audit ledger, and the UI receives a progress label plus a completion event through the callback.

A provisioning cycle follows the same shape. The engine renders the Jinja2 payload for the requested action (`add_branch`, `add_subdept`, `add_endpoint`), validates it in dry-run mode, then sends it as a RESTCONF PUT or POST. The response and the operation ID are recorded in `actions_log`, and the ledger receives one append per operation.

## Concurrency model

The web app runs its HTTP server on a daemon thread while the main thread hosts the pywebview window. Engine operations that touch the device run in the caller's thread with a lock around the shared RESTCONF session, because the sandbox refuses concurrent sessions to the same device. The collector loop that feeds live telemetry runs on its own thread and never blocks UI calls; it writes to SQLite and the UI polls through `Api.series` and `Api.telemetry`.

## Why this shape

Keeping the engine separate from both front ends means the CLI can provision without the web stack, and the web app can run without a terminal. The vault and database are shared by design, so a developer can verify a provisioning action from the CLI and watch the result appear in the UI's audit view. The next chapters describe each surface in depth.
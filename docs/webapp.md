# Web app

The web app is the primary interface. It serves the full UI from a loopback HTTP server and opens it in a pywebview native window, with a plain-browser fallback for environments without pywebview support. It never binds to anything but `127.0.0.1`, so nothing is exposed to the network.

## Running it

```
venv\Scripts\python.exe gui\webapp.py
```

The launcher starts a `ThreadingHTTPServer` on `127.0.0.1:17771` in a daemon thread, then creates a pywebview window with the EdgeChromium backend. If pywebview cannot open a window, or if you prefer a browser, point any browser at `http://127.0.0.1:17771`; the HTTP shim in the server maps requests under `/api/` to the same `Api` class that the pywebview bridge uses, so both modes behave identically. The port is the module constant `PORT` in `gui/webapp.py`.

## Views

The single-page UI in `gui/web/index.html` is organized as ten views, switched by hash: sign-in, home, provisioning, telemetry, YANG models explorer, operations toolbox, topology, audit, analytics, and profile. Each view talks to the `Api` class and never touches the database directly.

| View | Api methods behind it |
| --- | --- |
| Sign-in | `login`, `logout`, `fields`, `validate` |
| Home | `dashboard`, `hosts`, `health`, `state` |
| Provisioning | `provisionPlan`, `provision`, `deleteSub`, `scanVlans`, `hostRegistry` |
| Telemetry | `telemetry`, `collectTelemetry`, `telemetryRaw`, `series`, `trends` |
| Models explorer | `netconfModules`, `netconfSchema`, `netconfGet`, `netconfNamespace` |
| Operations | `cliRun`, `cliArchiveDiff`, `configHistory`, `configDiff`, `dnsAdd` |
| Topology | `topology`, `topologyRaw`, `ifaceConfig`, `ifaceStateLive` |
| Audit | `audit`, `verifyAudit`, `drift`, `snapshot`, `setBaseline`, `compliance`, `scanCompliance` |
| Analytics | `analyticsDeep`, `stats`, `securityPosture`, `security` |
| Profile | `profile`, `creds`, `updateCreds`, `updateProfile`, `testCreds`, `setMode`, `saveVpn`, `vpnStatus`, `vpnConnect`, `vpnDisconnect` |

The full surface is about seventy methods. A representative subset: `state` returns the platform identity and device mode, `testCreds` verifies vault credentials against the device without saving, `scanVlans` inventories VLANs, `remediate` and `remediateAll` apply the fixes proposed by the security posture checks, and `verifyAudit` replays the ledger chain to prove it is unbroken.

The provisioning view's add-PC flow is a two-step guided form. The first step picks the segment the host joins: an existing branch or the fabric's next free /24, with a live table of the registered hosts. The second step auto-drafts the host node from that context — label from the VLAN, the next free IP from the subnet and registry (`hostRegistry`), and a free access port from interface telemetry — while every value stays editable. A node-type picker (PC, laptop, server, printer, phone) labels the host and drives its icon in the topology. `hostRegistry` is a separate endpoint from the topology `hosts` list: the latter reports which monitored devices are up, the former is the administrative registry of registered host nodes. Deploying runs the same validation as the CLI (`validate`, including the duplicate-IP check via `host_ip_taken` and the node-type whitelist) and then `provision`. `provision` reports the deployment's real outcome: `ok` is false when the RESTCONF write and the SSH fallback both failed, and `detail` carries the failure reason pulled from the deploy log (for example an SSH connection error), so the launch sequence shows the abort card with the actual cause instead of a mission-accomplished card, and a failed deployment never writes a registry record. The topology view renders every registered host as a node on an inner arc around the core, linked to its branch segment (or the core when the segment has no branch), with an icon per node type; registered hosts therefore survive on the map even when they are not part of the live interface telemetry.

## The API bridge

`Api` in `gui/webapp.py` is a plain class whose methods take JSON-serializable arguments and return JSON-serializable values. In pywebview mode, `webview.create_window` is given the `Api` instance as `js_api`, so JavaScript calls `pywebview.api.<method>(...)` directly. The browser mode uses the HTTP shim: a request to `/api/<method>?<args>` is dispatched to the same method and the JSON result is returned. Both paths share the `Api` instance, the engine, and the database, so there is exactly one implementation of every operation.

Results that contain credentials are masked before they leave the bridge: `_masked_res`, `_masked_creds`, and `_masked_vpn` replace password and secret values with placeholders, so a network inspector cannot read secrets out of the page state. Details are in [security.md](security.md).

## Background work

The web app starts a collector thread on launch. It samples interface state and telemetry on a schedule (the interval is configurable in the profile view) and writes the samples to SQLite while the UI polls through `telemetry` and `series`. Device-facing operations hold a lock on the shared RESTCONF session, because the sandbox rejects concurrent sessions from one user. Long operations report progress through a callback that pywebview forwards to the UI as events, and the browser mode falls back to polling.

## Health probe

`probe.py` at the repository root is a standalone check that the bridge is healthy. It starts the server, opens a pywebview window, calls `api.state()` from JavaScript, and verifies that the returned build string equals `0.4.0-web`. Run it with:

```
venv\Scripts\python.exe probe.py
```

A mismatch between the probe's expected string and the app version is the first thing to fix when the UI fails to boot, because it means the bridge contract changed.

## Static assets

The UI is plain HTML, CSS, and JavaScript under `gui/web/`: `index.html`, `css/`, `js/`, and an offline icon sprite built from Lucide plus the project's custom network SVGs by `gui/web/icons/build_sprite.py` (one-time build, the generated `sprite.svg` is committed). Screenshots captured by the QA suite are stored in `gui/web/screenshots/`.
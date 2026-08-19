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
| Provisioning | `provisionPlan`, `provision`, `deleteSub`, `scanVlans` |
| Telemetry | `telemetry`, `collectTelemetry`, `telemetryRaw`, `series`, `trends` |
| Models explorer | `netconfModules`, `netconfSchema`, `netconfGet`, `netconfNamespace` |
| Operations | `cliRun`, `cliArchiveDiff`, `configHistory`, `configDiff`, `dnsAdd` |
| Topology | `topology`, `topologyRaw`, `ifaceConfig`, `ifaceStateLive` |
| Audit | `audit`, `verifyAudit`, `drift`, `snapshot`, `setBaseline`, `compliance`, `scanCompliance` |
| Analytics | `analyticsDeep`, `stats`, `securityPosture`, `security` |
| Profile | `profile`, `creds`, `updateCreds`, `updateProfile`, `testCreds`, `setMode`, `saveVpn`, `vpnStatus`, `vpnConnect`, `vpnDisconnect` |

The full surface is about seventy methods. A representative subset: `state` returns the platform identity and device mode, `testCreds` verifies vault credentials against the device without saving, `scanVlans` inventories VLANs, `remediate` and `remediateAll` apply the fixes proposed by the security posture checks, and `verifyAudit` replays the ledger chain to prove it is unbroken.

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
# QA and probes

The platform carries two layers of verification: standalone probe scripts that exercise the Python side against the live device, and a Playwright suite that drives the web UI. Neither is a test framework in the strict sense; both are runnable scripts that print pass or fail and write screenshots or logs.

## Prerequisites

The Playwright suite needs the dev requirements and a Chromium binary:

```
venv\Scripts\python.exe -m pip install -r requirements-dev.txt
venv\Scripts\python.exe -m playwright install chromium
```

Scripts that touch the live device need the vault populated (run the setup step first) and a reachable sandbox. The UI suite runs offline with a simulated device feed, so it can be run without the sandbox.

## Device probes

`tools/probe_datastores.py` checks the NETCONF datastores: it connects to the device, lists the available datastores, and verifies the expected read-only and candidate stores answer. It is the quickest way to confirm the NETCONF path after an instance reset.

`gui/web/tools/iface_state_live.py` pulls the real interface state through the RESTCONF client and prints it, and `gui/web/tools/analytics_live_device_probe.py` samples live telemetry through the `Api` class without the UI. `gui/web/tools/dual_mode_probe.py` exercises the device-mode resolver and the profile view wiring. `gui/web/tools/live_test.py` runs a broader live round-trip through the engine. These scripts share one pattern: they import the application modules directly, drive them, and print verdict lines.

## UI regression suite

`gui/web/tools/qa.py` is the main suite. It boots the server on the loopback port, drives every view with Playwright, and checks for console errors, page errors, and view errors after each navigation. The suite runs against a simulated device feed, so it validates the UI contract (rendering, charts, tables, toasts, navigation) without depending on sandbox availability. It reports a verdict per view and a final line:

```
CLEAN - no console errors, no page errors, no view errors
```

with the checkpoint count (34 checkpoints across the ten views). Screenshots from the run land in `gui/web/screenshots/`. The chart-focused companions `gui/web/tools/chart_labels_probe.py` and `gui/web/tools/analytics_live_probe.py` verify chart rendering in the analytics view, and `gui/web/tools/vlan_probe.py` validates the VLAN inventory flow in the provisioning view.

The suite's provisioning section now includes an end-to-end pass of the add-PC flow: entering the host registry mode, waiting for the fabric scans and the registry to resolve, checking the registry table shows the node-type column, checking that the auto-draft filled the label, IP, port, VLAN, and gateway, clicking AUTO-DRAFT again, switching the node type to laptop and verifying the picker follows, verifying the deploy button becomes enabled, and driving the deploy launch sequence through to the mission-accomplished card and the host-registered toast. The run closes by switching to the topology view without a page reload — the in-memory mock state survives hash navigation — and asserting that the two seeded hosts plus the newly registered laptop all render as host nodes with their type tags.

## Observed results

Numbers reported in the project report come from runs against the public DevNet Sandbox over the course of the project. The provisioning cycle for the branch action measured about five seconds end to end (rendering, validation, and the RESTCONF deployment steps). The latency probe covered seven transport paths with twenty samples per path. The UI suite ran the full set of checkpoints with zero console, page, or view errors. Telemetry and drift tracking ran for roughly two weeks of continuous collection, with the audit ledger reaching over a hundred chained entries, all verified unbroken.

## When to run what

Run `qa.py` after any change to the UI views, the bridge methods, or the static assets: it is the regression gate for the front end. Run `iface_state_live.py` and `probe_datastores.py` after a sandbox instance reset or a change to the transport code: they confirm the device path before any provisioning work. Run the provisioning dry-run (CLI or the provisioning view) before every live deployment, then confirm the action landed in `actions_log` and the audit view.
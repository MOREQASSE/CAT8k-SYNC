# Inventory and provisioning

The platform is driven by two YAML files under `config/`: `devices.yaml` for the device inventory and `branches.yaml` for the network topology and the provisioning actions. Payloads are rendered from Jinja2 templates in `config/templates/`.

## devices.yaml

Each device entry is a name-keyed block with connection parameters.

```yaml
devices:
  Cat8000-Sandbox:
    device_type: cisco_ios
    host: devnetsandboxiosxec8k.cisco.com
    username: reqasse
    port: 22
    fast_cli: true
    global_delay_factor: 2
    restconf_https: true
    restconf_verify_ssl: false
    restconf_port: 443
```

`device_type`, `host`, `username`, and `port` drive the Netmiko SSH path. The `restconf_*` keys drive the RESTCONF client: HTTPS on port 443, TLS verification disabled because the sandbox presents a self-signed certificate. The username here is the sandbox reservation account; the password and enable secret are never stored in this file, they live in the encrypted vault or the environment fallback.

## branches.yaml

The file has two sections. `existing_infrastructure` lists sites that are already deployed and only collected and monitored. `provisioning` lists actions the platform can deploy.

```yaml
existing_infrastructure:
  - site_name: Maroc-Phosphore1
    router_wan_ip: 10.0.10.1
    router_wan_gateway: 10.0.10.2
  - site_name: Maroc-Phosphore2
    router_wan_ip: 10.0.20.1
    router_wan_gateway: 10.0.20.2

provisioning:
  - action: add_branch
    site_name: Maroc-Chimie
    device: Cat8000-Sandbox
    router_wan_port: GigabitEthernet0/0/0
    router_trunk_port: GigabitEthernet0/0/1
    router_wan_ip: 10.0.30.2
    router_wan_gateway: 10.0.30.1
    department_vlan: 30
    department_gateway: 192.168.30.1
    department_subnet: 255.255.255.0
```

Every provisioning action names the target device, the WAN and trunk interfaces, the VLAN for the department, and the addressing. The deployer fills in the remaining fields from templates: DHCP scope, VLAN name, routing, and ACL entries.

## Actions

Three actions are implemented, one per template file.

`add_branch` (from `add_branch.j2`) deploys a full new branch site: interface addressing, department VLAN with gateway and DHCP pool, routing to the WAN, and the access control for the new subnet. `add_subdept` (from `add_subdept.j2`) adds a department to an existing site, creating its VLAN, gateway, and DHCP scope. `add_endpoint` (from `add_endpoint.j2`) reserves a static address for a single endpoint in an existing department and pins it on the corresponding access port.

`add_pc` registers a host node. The payload names the host's `node_type` (pc, laptop, server, printer, or phone) for the registry record and the topology icon; it defaults to `pc`. Before touching the device, the deployer runs a pre-flight gate: TCP probes on the RESTCONF port and port 22 plus a RESTCONF hostname read, and waits up to two short backoff windows when the planes are down, since the shared sandbox cycles; every skipped attempt is logged as a WARN event under the PROVISION source so the retry window is visible in the log. It then attempts the RESTCONF DHCP reservation on `native/ip/dhcp/excluded-address`; on platforms whose native model does not expose a writable DHCP container (the always-on Catalyst 8000v is one), it falls back to the SSH CLI path and pushes `ip dhcp excluded-address <ip>` over Netmiko, retrying up to three times with short pauses when the SSH plane refuses connections — the shared sandbox's SSH plane flaps after resets and under session pressure. When the SSH fallback exhausts itself, the whole deploy retries (5s then 15s backoff) up to three attempts and the failure detail reports how many attempts ran, for example "3 of 3 attempts failed — SSH connection failed: TCP connection to device failed"; the expected `native/ip/dhcp` 404 is never reported as the reason since it is the trigger for the fallback. Either way a successful deployment writes the host into the `host_registry` table and appends a ledger entry, which is what makes the host visible in the registry and to the duplicate-IP checks; a deployment that fails on both transports reports failure with the failure reason and writes nothing, so the registry only ever reflects hosts the fabric actually accepted. The fallback is logged in the per-action outcome file under `output/`, so the applied transport is always traceable.

## Dry-run first

Every action can be validated without touching the network.

```
venv\Scripts\python.exe main.py provision --dry-run
```

The deployer renders the payload and returns the exact RESTCONF operations it would send, with a validation matrix marking each step ready or blocked. The web provisioning view exposes the same preview through `provisionPlan` before `provision` is called. Only after a dry-run shows a green matrix should a live deployment run.

## How a deployment works

The deployer walks the action step by step. For `add_branch`, it creates the WAN interface addressing, then the department VLAN and gateway, then the DHCP pool, then the routing statements, and finally the ACL entries. Each step is a RESTCONF operation whose payload comes from the Jinja2 template. The parent-interface resolver (`get_physical_parent_interface`) maps a logical interface to its physical parent when the device requires it, which matters on sandbox instances where subinterfaces and physical ports are named differently. Every successful step is recorded in `actions_log`; a failed step aborts the remaining steps for that site and leaves a clear error in the log.

## Adding a new action

Add the action name to `branches.yaml` under `provisioning`, create a matching `config/templates/<action>.j2` with the RESTCONF payload skeleton, and register the step order in `src/deployer.py` next to the existing builders. The web provisioning view lists actions by inventory order, and the CLI picks them up automatically from the same file, so no front-end change is required.
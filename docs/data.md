# Data model

All persistence lives in a single SQLite file, `data/CAT8k-SYNC.db`, managed by `src/db.py`. The schema holds eleven tables: identity, device and VPN records, observation history, audit trails, and a settings key-value store.

## Identity and secrets

`users` holds the dashboard identity with a PBKDF2 password hash and salt (`hash_password`, `verify_password`). `devices` holds the device record: host, username, and the encrypted password and enable secret, plus the RESTCONF flags. `settings` is a key-value table used for UI state such as the collector interval and the selected baseline; `set_setting` and `get_setting` are the only writers. The vault key itself never touches the database: it lives in `data/.secret` and is only read into memory to decrypt credentials.

## Observation history

Four tables store what the platform measures. `snapshot_history` keeps one row per collection cycle with the interface states and the configuration checksum. `iface_history` keeps per-interface time series so a view can show how a port's state or address changed over time. `telemetry_history` stores the raw payload per telemetry path (CPU, memory, and interface counters among others), keyed by kind and path, with a timestamp. `drift_history` records each comparison between the current configuration and the baseline: status, the diff text, and when it happened.

`series(kind, limit)` is the read path the analytics view uses: it returns the last `limit` samples for a telemetry kind as a time-ordered list. `snapshot_timeline` and `iface_history(if_name=...)` serve the topology and history views.

## Audit trails

`audit_history` stores the compliance scan results per run, with the scan filename and the per-rule findings. `actions_log` records every provisioning operation: action name, status, message, payload, and device. `events_log` is the general event log that both interfaces append to. All three are append-only by convention; nothing in the code deletes or rewrites them.

## The host registry

`host_registry` records every host node registered through the `add_pc` provisioning action: label, node type (pc, laptop, server, printer, or phone), VLAN, IP, mask, access port, gateway, subnet, target device, and creation timestamp. `save_host` inserts a record and stores the node type (it defaults to `pc` when omitted), `list_hosts(limit)` is the read path, and `host_ip_taken(ip)` powers the duplicate-IP check in provisioning validation. The registry is the UI's source for the next-free-IP and port suggestions in the add-PC flow and for the registered-host nodes on the topology map, and `wipe_all()` clears it along with the rest of the schema. Databases created before the node type existed are migrated on startup: `init()` checks the table's columns and adds the `node_type` column when missing.

## The audit ledger

`audit_ledger` is the tamper-evidence layer. Each row holds an event type, actor, action, payload, timestamp, the previous entry's checksum, and its own checksum. The chain rule, in `log_ledger`:

```
checksum = sha256(prev_hash + event_type + actor + action + payload + timestamp)
```

The first entry anchors on a genesis hash derived from the schema (`_ledger_genesis`). `verify_ledger()` replays the whole chain: it recomputes every checksum from the previous hash and reports `broken_at` with the offending index if any entry fails. The web audit view calls this through `verifyAudit`, and a broken chain is displayed as an integrity failure, not silently absorbed.

## Reading the database

SQLite is the only store, so any SQLite tool works:

```
venv\Scripts\python.exe -c "import sqlite3; c = sqlite3.connect('data/CAT8k-SYNC.db'); print(c.execute('select count(*) from audit_ledger').fetchone())"
```

Use the module functions from `src/db.py` in application code rather than raw SQL, because the schema is only guaranteed through them. `wipe_all()` resets the database to an empty state and is used by tests and by the profile view's factory reset.
/* api.js — bridge to pywebview python backend. The in-browser mock exists ONLY
   for development/QA (any ?demo / ?qa / ?mock query). Outside the desktop app
   without an explicit demo mode every call resolves to a hard error — the UI
   must show empty states / errors, NEVER invented data.

   The desktop bridge (window.pywebview.api) is injected by pywebview *after*
   the page scripts run, so at load time it may not exist yet. We therefore
   mirror the param-fetching callers and wait briefly for it when the page is
   inside a WebView2 / Edge shell; anywhere else we fail fast on the bridge. */
"use strict";

const API = (() => {
  const DEMO = /[?&](demo|mock|qa)/.test(location.search);
  const delay = (ms) => new Promise((r) => setTimeout(r, ms));

  let bridge = (typeof window.pywebview !== "undefined" && window.pywebview.api) || null;
  window.addEventListener("pywebviewready", () => {
    if (typeof window.pywebview !== "undefined" && window.pywebview.api) {
      bridge = window.pywebview.api;
    }
  });
  /* pywebview first publishes window.pywebview.api as an EMPTY object and only
     then _createApi() attaches the actual methods, so we only trust it once the
     requested method exists. */
  const hasBridge = (name) => {
    const cand = bridge || (typeof window.pywebview !== "undefined"
      ? window.pywebview.api : null);
    if (cand && (name == null || typeof cand[name] === "function")) {
      bridge = cand;
      return cand;
    }
    return null;
  };
  /* wait for the desktop bridge to expose `name`; never longer than the deadline. */
  const waitBridge = (name, ms = 8000) => {
    const b = hasBridge(name);
    if (b) return Promise.resolve(b);
    if (DEMO) return Promise.resolve(null);
    /* the desktop app injects window.pywebview after the page's scripts run,
       so hold on until it arrives instead of giving up on a first read. */
    return new Promise((res, rej) => {
      const t0 = Date.now();
      (function tick() {
        const bb = hasBridge(name);
        if (bb) return res(bb);
        if (Date.now() - t0 > ms) {
          console.warn("[api] bridge timeout after", ms, "ms");
          return rej(new Error("backend bridge timed out"));
        }
        setTimeout(tick, 120);
      })();
    });
  };

  const exec = (target, name, args) => {
    const fn = target && target[name];
    if (typeof fn !== "function") {
      console.warn("[api] method unavailable:", name);
      return Promise.reject(new Error("api method not found: " + name));
    }
    try {
      return Promise.resolve(fn.apply(target, args));
    } catch (e) {
      return Promise.reject(e);
    }
  };

  /* thin wrapper: live calls pywebview.api; mock only under ?demo/qa; otherwise reject. */
  const call = (name, args) => {
    const local = hasBridge(name);
    if (local) return exec(local, name, args);
    if (DEMO) return exec(mock, name, args);
    return waitBridge(name).then((target) => exec(target, name, args));
  };

  /* ---------------- mock backend (mirrors webapp.py Api shapes) ---------------- */
  const mock = {
    _state: {
      mode: null,
      configured: false,
      online: false,
      connected: false,
      theme: "mission",
      session: null,
      profile: { full_name: "Demo Operator", role: "NETWORK OPS", site: "NOC-01" },
      creds: {
        host: "devnetsandboxiosxec8k.cisco.com",
        username: "demo",
        password: "********",
        secret: "********",
      },
      vpn: {
        address: "devnetsandbox-usw1-reservation.cisco.com:20291",
        username: "reqasse",
        password: "********",
        device_host: "10.10.20.48",
        device_username: "developer",
        device_password: "********",
      },
      backend: { mode: "auto", source: "normal", host: "devnetsandboxiosxec8k.cisco.com", tunnel: false, reason: null, vpn_host: "10.10.20.48", identity: "cat8000-public" },
      identity: { instance: "cat8000-public", at: "2026-08-13 15:20:00", preference: "auto" },
      res_creds: {
        devbox: { slug: "devbox", label: "Developer Box", desc: "Linux environment", host: "10.10.20.50", port: 22, username: "developer", password: "********", updated: "" },
        xrv: { slug: "xrv", label: "IOS XRv 9K", desc: "XR router", host: "10.10.20.35", port: 22, username: "developer", password: "********", updated: "" },
        nexus: { slug: "nexus", label: "Nexus 9K", desc: "NX-OS switch", host: "10.10.20.40", port: 22, username: "admin", password: "********", updated: "" },
      },
      version: { app: "CAT8k-SYNC", build: "0.4.0-web", core: "pywebview 6" },
    },
    _series: [
      { name: "cpu", count: 20, unit: "%", vals: [31, 29, 33, 38, 35, 42, 39, 36, 41, 44, 40, 37, 43, 46, 42, 39, 36, 40, 38, 41] },
      { name: "mem", count: 20, unit: "%", vals: [42, 43, 41, 44, 45, 43, 44, 46, 45, 44, 47, 46, 45, 48, 46, 45, 44, 46, 45, 44] },
      { name: "up", count: 20, unit: "if", vals: [10, 10, 11, 11, 10, 11, 11, 12, 11, 12, 11, 12, 11, 11, 12, 12, 11, 12, 12, 12] },
      { name: "errors", count: 20, unit: "err", vals: [0, 0, 0, 0, 2, 0, 0, 0, 0, 4, 1, 0, 0, 6, 2, 1, 0, 3, 5, 8] },
    ],
    actions: [],
    _trends: { x: ["08:00", "09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "15:00", "16:00", "17:00"], values: [10, 10, 11, 11, 10, 11, 11, 12, 12, 12] },
    _hosts: [{ hostname: "R1-CORE", up: true }],
    _stats: { uptime_days: 214, interfaces: 12, subinterfaces: 48, compliance: 92, drift: 3, actions: 32, snapshots: 47, audits: 9, last_sync: "2026-08-06 09:12" },
    _dashboard: {
      stats: {
        uptime_days: 214, snapshots: 47, iface_ups: 512, iface_downs: 6,
        audits: 9, audit_fails: 2, actions: 32, drifts: 3, compliance: 92,
        first_snapshot: "2026-06-08 08:02:11", last_snapshot: "2026-08-10 10:14:33",
      },
      series: {
        cpu: { x: Array.from({ length: 24 }, (_, i) => String((8 + i % 16) % 24).padStart(2, "0") + ":00"),
               vals: Array.from({ length: 24 }, (_, i) => 28 + Math.round(18 * Math.sin(i / 3)) + (i % 5 === 0 ? 9 : 0)) },
        mem: { x: Array.from({ length: 24 }, (_, i) => String((8 + i % 16) % 24).padStart(2, "0") + ":00"),
               vals: Array.from({ length: 24 }, (_, i) => 40 + Math.round(7 * Math.sin(i / 4 + 1))) },
        up: { x: Array.from({ length: 24 }, (_, i) => String((8 + i % 16) % 24).padStart(2, "0") + ":00"),
              vals: Array.from({ length: 24 }, (_, i) => 11 - (i === 12 ? 1 : 0)) },
        errors: { x: Array.from({ length: 24 }, (_, i) => String((8 + i % 16) % 24).padStart(2, "0") + ":00"),
                  vals: Array.from({ length: 24 }, (_, i) => (i >= 19 ? (i - 19) * 4 : 0)) },
      },
      audit_trend: {
        x: ["08-04", "08-05", "08-06", "08-07", "08-08", "08-09"],
        pass: [9, 10, 10, 10, 11, 11], fail: [4, 3, 3, 2, 2, 2], warn: [3, 3, 3, 4, 3, 3],
        score: [56, 62, 62, 62, 68, 68],
      },
      traffic: [
        { name: "Gi0/0/6.100", rx: 842, tx: 515, state: "UP" },
        { name: "Gi0/0/0", rx: 731, tx: 612, state: "UP" },
        { name: "Gi0/0/6.130", rx: 398, tx: 244, state: "UP" },
        { name: "Gi0/0/6.140", rx: 285, tx: 190, state: "UP" },
        { name: "Gi0/0/6.110", rx: 210, tx: 155, state: "UP" },
        { name: "Gi0/0/1", rx: 96, tx: 88, state: "UP" },
        { name: "Gi0/0/6.120", rx: 0, tx: 0, state: "DOWN" },
        { name: "Loopback0", rx: 12, tx: 9, state: "UP" },
      ],
      hourly: Array.from({ length: 24 }, (_, h) =>
        (h >= 8 && h <= 20 ? Math.round(3 + 5 * Math.abs(Math.sin(h / 4)) + (h === 9 || h === 17 ? 6 : 0)) : h % 3 === 0 ? 2 : 0)),
      events: [
        { ts: "2026-08-10 10:14:33", level: "OK", source: "SNIFFER", msg: "polled telemetry — 12 interfaces / 4 neighbours" },
        { ts: "2026-08-10 10:02:14", level: "SYS", source: "VAULT", msg: "key rotated — fernet 256bit" },
        { ts: "2026-08-10 09:55:40", level: "WARN", source: "COMPLIANCE", msg: "BR-ANNABA down — 3 unverified checks" },
        { ts: "2026-08-10 09:41:02", level: "OK", source: "SCAN", msg: "compliance scan — 16 checks / score 68" },
        { ts: "2026-08-10 09:12:44", level: "AUTH", source: "SESSION", msg: "operator login — demo" },
        { ts: "2026-08-10 08:47:10", level: "SYS", source: "VAULT", msg: "credentials updated — devnetsandboxiosxec8k" },
        { ts: "2026-08-10 08:40:33", level: "OK", source: "PROVISION", msg: "branch TIZI deployed — vlan 150" },
        { ts: "2026-08-10 08:40:01", level: "FAIL", source: "PROVISION", msg: "RESTCONF 403 forbidden — retry" },
      ],
      drift_trend: { x: ["08-04", "08-05", "08-06", "08-07", "08-08", "08-09"],
                     status: ["CLEAN", "DRIFT", "CLEAN", "CLEAN", "DRIFT", "CLEAN"] },
    },
    _analytics: (() => {
      /* 96 synthesized samples so 1D/1W/1M/ALL windows all have data */
      const N = 96;
      const X = Array.from({ length: N }, (_, i) => {
        const d = new Date(Date.UTC(2026, 7, 1 + Math.floor(i / 16), 9 + (i % 16) * 0.5 * 2, (i * 7) % 60));
        return d.toISOString().slice(0, 16).replace("T", " ");
      });
      const cpu = Array.from({ length: N }, (_, i) => 30 + Math.round(16 * Math.sin(i / 5)) + (i % 22 === 0 ? 12 : 0));
      const mem = Array.from({ length: N }, (_, i) => 41 + Math.round(6 * Math.sin(i / 8 + 1)));
      const up = Array.from({ length: N }, (_, i) => 11 - (i % 29 === 27 ? 1 : 0));
      const errors = Array.from({ length: N }, (_, i) => (i % 31 > 28 ? (i % 31 - 28) * 9 : 0));
      const avail = up.map((u) => Math.round((100 * u) / 12));
      const arp = Array.from({ length: N }, (_, i) => 118 + Math.round(62 * Math.sin(i / 14)) + i);
      const rx = Array.from({ length: N }, (_, i) => 420 + Math.round(330 * Math.sin(i / 4.4)) + (i % 23 === 0 ? 260 : 0));
      const tx = Array.from({ length: N }, (_, i) => 300 + Math.round(215 * Math.sin(i / 5.2)) + (i % 23 === 0 ? 190 : 0));
      const in_errors = errors;
      const crc = errors.map((e) => Math.max(0, Math.round(e / 3) - 4));
      const flaps = errors.map((e) => Math.max(0, Math.round(e / 6) - 8));
      const talkNames = ["GigabitEthernet0/0/0", "GigabitEthernet0/0/1", "GigabitEthernet0/0/0.100"];
      const talkers = talkNames.map((nm, ti) => ({
        name: nm, state: "UP", rx: rx[N - 1] * (1 - ti * 0.28), tx: tx[N - 1] * (1 - ti * 0.3),
        vals: rx.map((v, i) => Math.max(0, Math.round(v * (1 - ti * 0.28) * (0.86 + 0.28 * Math.sin(i / 6 + ti)) ))),
      }));
      const audit = {
        x: ["08-01", "08-03", "08-05", "08-07", "08-09", "08-11", "08-13"],
        pass: [9, 10, 10, 9, 11, 10, 10], fail: [4, 3, 3, 4, 2, 3, 2],
        warn: [3, 3, 3, 3, 3, 3, 2], score: [56, 62, 62, 56, 68, 66, 71],
      };
      const pkt = {
        labels: ["64", "65-127", "128-255", "256-511", "512-1023", "1024-1518", "1519+"],
        entries: [
          { name: "GigabitEthernet0/0/0", rx: [448, 340045843, 877281960, 1776379079, 7177746466, 0, 749], tx: [243, 363717976, 871387990, 1751781169, 7186675288, 173, 750], total_rx: 10171454431, total_tx: 10173563487 },
          { name: "GigabitEthernet0/0/1", rx: [112040, 299845, 87044510, 284452771, 1173066011, 1487751235, 0], tx: [88, 288340, 83234010, 271845229, 1187716223, 1469450658, 0], total_rx: 3051853412, total_tx: 3011920548 },
          { name: "GigabitEthernet0/0/2", rx: [73842101, 12048704, 2411115, 88000, 88090, 2100, 100], tx: [72100103, 8904712, 182224, 102488, 880, 1550, 88], total_rx: 88400210, total_tx: 81200345 },
          { name: "GigabitEthernet0/0/3", rx: [42103504, 2108892, 20861, 19012, 8800, 84, 902], tx: [40101988, 2433084, 302112, 20990, 4210, 635, 0], total_rx: 44211055, total_tx: 42885019 },
        ],
      };
      const OUT = {
        span: 96, cpu: { x: X, vals: cpu }, mem: { x: X, vals: mem },
        up: { x: X, vals: up }, errors: { x: X, vals: errors },
        avail: { x: X, vals: avail, up, down: up.map((u) => 12 - u) },
        arp: { x: X, vals: arp },
        thr: { x: X, rx, tx },
        errs: { x: X, in_errors, out_errors: in_errors.map((v) => Math.round(v / 2)), crc, flaps },
        talkers, problems: [
          { name: "GigabitEthernet0/0/0.120", state: "DOWN", speed: "1 Gbps", rx: 0, tx: 0, flaps: 14, crc: 9, in_errors: 127, out_errors: 0 },
          { name: "GigabitEthernet0/0/2", state: "UP", speed: "1 Gbps", rx: 84, tx: 81, flaps: 0, crc: 3, in_errors: 41, out_errors: 2 },
        ],
        speeds: { "1 Gbps": 5, "10 Gbps": 1 },
        audit, pkt,
        hourly: Array.from({ length: 24 }, (_, h) => (h >= 8 && h <= 20 ? Math.round(3 + 5 * Math.abs(Math.sin(h / 4)) + (h === 9 || h === 17 ? 6 : 0)) : h % 3 === 0 ? 2 : 0)),
      };
      OUT.grow = () => {
        /* append one timestamped sample — the demo feed advances every poll */
        const last = (a) => a[a.length - 1];
        const w = (v, amp, lo, hi) => Math.max(lo, Math.min(hi, Math.round(v + (Math.random() * 2 - 1) * amp)));
        const d = new Date(String(last(OUT.cpu.x)).replace(" ", "T") + ":00Z");
        d.setUTCHours(d.getUTCHours() + 1);
        const nx = d.toISOString().slice(0, 16).replace("T", " ");
        const u = w(last(OUT.up.vals), 1, 9, 12);
        const e = w(last(OUT.errors.vals), 2, 0, 60);
        OUT.cpu.x.push(nx); OUT.cpu.vals.push(w(last(OUT.cpu.vals), 4, 22, 78));
        OUT.mem.x.push(nx); OUT.mem.vals.push(w(last(OUT.mem.vals), 2, 30, 70));
        OUT.up.x.push(nx); OUT.up.vals.push(u);
        OUT.errors.x.push(nx); OUT.errors.vals.push(e);
        OUT.avail.x.push(nx); OUT.avail.vals.push(Math.round((100 * u) / 12)); OUT.avail.up.push(u); OUT.avail.down.push(12 - u);
        OUT.arp.x.push(nx); OUT.arp.vals.push(w(last(OUT.arp.vals), 12, 60, 340));
        OUT.thr.x.push(nx); OUT.thr.rx.push(w(last(OUT.thr.rx), 90, 40, 1300)); OUT.thr.tx.push(w(last(OUT.thr.tx), 70, 30, 1000));
        OUT.errs.x.push(nx); OUT.errs.in_errors.push(e); OUT.errs.out_errors.push(Math.round(e / 2));
        OUT.errs.crc.push(Math.max(0, Math.round(e / 3) - 4)); OUT.errs.flaps.push(Math.max(0, Math.round(e / 6) - 8));
        OUT.audit.x.push(String(d).slice(5, 10)); OUT.audit.score.push(w(last(OUT.audit.score), 2, 40, 92));
        OUT.audit.pass.push(w(last(OUT.audit.pass), 1, 4, 13)); OUT.audit.fail.push(Math.max(0, w(last(OUT.audit.fail), 1, 0, 9)));
        OUT.audit.warn.push(w(last(OUT.audit.warn), 1, 0, 6));
        OUT.hourly[8 + Math.floor(Math.random() * 13)] += 1;
        return OUT;
      };
      return OUT;
    })(),
    _topology: {
      center: { id: "core", hostname: "CORE-EDGE", role: "core", kind: "router", up: true, model: "ISR4431/K9", ios: "17.9.4a", ipv4: "10.10.20.1", meta: {} },
      devices: [
        { id: "wan", role: "wan", kind: "cloud", hostname: "WAN-UPLINK", site: "SP UPLINK", up: true, state: "up", ipv4: "10.10.20.1", cidr: "10.10.20.1/24", subnet: "10.10.20.0/24", iface: "GigabitEthernet1", meta: { speed: "1 Gbps", duplex: "full", mtu: "1500" } },
        { id: "br-100", role: "branch", kind: "network", hostname: "BR-100", site: "ALGER", up: true, state: "up", vlan: 100, ipv4: "10.1.100.1", cidr: "10.1.100.1/24", subnet: "10.1.100.0/24", iface: "GigabitEthernet0/0/6.100", meta: { speed: "1 Gbps", duplex: "full", mtu: "1500" } },
        { id: "br-110", role: "branch", kind: "network", hostname: "BR-110", site: "ORAN", up: true, state: "up", vlan: 110, ipv4: "10.1.110.1", cidr: "10.1.110.1/24", subnet: "10.1.110.0/24", iface: "GigabitEthernet0/0/6.110", meta: { speed: "1 Gbps", duplex: "full", mtu: "1500" } },
        { id: "br-120", role: "branch", kind: "network", hostname: "BR-120", site: "ANNABA", up: false, state: "down", vlan: 120, ipv4: "10.1.120.1", cidr: "10.1.120.1/24", subnet: "10.1.120.0/24", iface: "GigabitEthernet0/0/6.120", meta: { speed: "1 Gbps", duplex: "full", mtu: "1500" } },
        { id: "br-130", role: "branch", kind: "network", hostname: "BR-130", site: "TLEMCEN", up: true, state: "up", vlan: 130, ipv4: "10.1.130.1", cidr: "10.1.130.1/24", subnet: "10.1.130.0/24", iface: "GigabitEthernet0/0/6.130", meta: { speed: "1 Gbps", duplex: "full", mtu: "1500" } },
        { id: "br-140", role: "branch", kind: "network", hostname: "BR-140", site: "BEJAIA", up: true, state: "up", vlan: 140, ipv4: "10.1.140.1", cidr: "10.1.140.1/24", subnet: "10.1.140.0/24", iface: "GigabitEthernet0/0/6.140", meta: { speed: "1 Gbps", duplex: "full", mtu: "1500" } },
      ],
      links: [
        { id: "c-wan", from: "core", to: "wan", up: true, state: "up", iface: "GigabitEthernet1" },
        { id: "c-br-100", from: "core", to: "br-100", up: true, state: "up", vlan: 100 },
        { id: "c-br-110", from: "core", to: "br-110", up: true, state: "up", vlan: 110 },
        { id: "c-br-120", from: "core", to: "br-120", up: false, state: "down", vlan: 120 },
        { id: "c-br-130", from: "core", to: "br-130", up: true, state: "up", vlan: 130 },
        { id: "c-br-140", from: "core", to: "br-140", up: true, state: "up", vlan: 140 },
      ],
    },
    _telemetry: {
      interfaces: {
        count: 12,
        ts: "2026-08-13 14:32:11",
        entries: [
          { name: "GigabitEthernet0/0/0", status: "up", speed: "1 Gbps", ip: "172.16.2.1/24", duplex: "full" },
          { name: "GigabitEthernet0/0/1", status: "up", speed: "1 Gbps", ip: "10.0.0.1/24", duplex: "full" },
          { name: "GigabitEthernet0/0/0.100", status: "up", speed: "1 Gbps", ip: "10.1.100.1/24", duplex: "full" },
          { name: "GigabitEthernet0/0/0.110", status: "up", speed: "1 Gbps", ip: "10.1.110.1/24", duplex: "full" },
          { name: "GigabitEthernet0/0/0.120", status: "down", speed: "1 Gbps", ip: "10.1.120.1/24", duplex: "full" },
          { name: "GigabitEthernet0/0/0.130", status: "up", speed: "1 Gbps", ip: "10.1.130.1/24", duplex: "full" },
        ],
      },
      arp: [
        { ip: "10.1.100.10", mac: "aabb.cc00.1001", interface: "Gi0/0/0.100", mode: "dynamic", type: "ip", age: "2026-08-11 14:48:01" },
        { ip: "10.1.100.254", mac: "aabb.cc00.0001", interface: "Gi0/0/0", mode: "interface", type: "ip", age: "2026-08-10 11:54:16" },
        { ip: "10.1.20.1", mac: "0050.56bf.1ce8", interface: "GigabitEthernet1", mode: "dynamic", type: "ip", age: "2026-08-11 15:02:44" },
      ],
      ospf: {
        state: "ships-in-the-night",
        state_label: "OSPF SITN // V2 + V3 INDEPENDENT",
        state_hint: "OSPFv2 and OSPFv3 run as two separate, isolated processes on this device — like ships passing in the night. They keep their own router-IDs, configs and neighbor tables, and never share state.",
        summary: "OSPF SITN // V2 + V3 INDEPENDENT · 2 processes",
        count: 2,
        entries: [
          { "process-id": 1, "router-id": "172.16.2.1", state: "up", area: "0.0.0.0" },
          { "process-id": 65000, "router-id": "10.0.0.1", state: "up", area: "0.0.0.1" },
        ],
      },
      bgp: {
        summary: "2 route vrfs · 3 route rds · 19 address-families",
        "rd-count": 3,
        count: 2,
        entries: [
          { vrf: "default", "address-families": "mdt, multicast, unicast, mvpn", "af-count": 19 },
          { vrf: "red", "address-families": "unicast", "af-count": 1 },
        ],
      },
      "pkt-dist": {
        mode: "buckets",
        labels: ["64", "65-127", "128-255", "256-511", "512-1023", "1024-1518", "1519+"],
        count: 4,
        ts: "2026-08-06 09:11:58",
        prev_ts: "2026-08-06 09:10:00",
        entries: [
          {
            name: "GigabitEthernet0/0/0", total_rx: 10171454431, total_tx: 10173563487,
            rx: [448, 340045843, 877281960, 1776379079, 7177746466, 0, 749],
            tx: [243, 363717976, 871387990, 1751781169, 7186675288, 173, 750],
          },
          {
            name: "GigabitEthernet0/0/1", total_rx: 3051853412, total_tx: 3011920548,
            rx: [112040, 299845, 87044510, 284452771, 1173066011, 1487751235, 0],
            tx: [88, 288340, 83234010, 271845229, 1187716223, 1469450658, 0],
          },
          {
            name: "GigabitEthernet0/0/2", total_rx: 88400210, total_tx: 81200345,
            rx: [73842101, 12048704, 2411115, 88000, 88090, 2100, 100],
            tx: [72100103, 8904712, 182224, 102488, 880, 1550, 88],
          },
          {
            name: "GigabitEthernet0/0/3", total_rx: 44211055, total_tx: 42885019,
            rx: [42103504, 2108892, 20861, 19012, 8800, 84, 902],
            tx: [40101988, 2433084, 302112, 20990, 4210, 635, 0],
          },
        ],
        delta: {
          "GigabitEthernet0/0/2": {
            rx: [4280912, 641103, 49018, 3220, 1910, 0, 0],
            tx: [3930887, 492201, 98210, 3104, 52, 0, 0],
          },
          "GigabitEthernet0/0/3": {
            rx: [3984021, 244810, 8218, 801, 42, 0, 18],
            tx: [3810402, 172088, 12012, 640, 30, 0, 0],
          },
        },
      },
      raw: '{"Cisco-IOS-XE-interfaces-oper:interfaces": {"interface": [...]}}',
    },
    _logs: [
      { ts: "2026-08-06 09:11:58", level: "OK", source: "SNIFFER", msg: "polled telemetry — 12 interfaces / 4 neighbours" },
      { ts: "2026-08-06 09:02:14", level: "SYS", source: "VAULT", msg: "key rotated — fernet 256bit" },
      { ts: "2026-08-06 08:55:40", level: "WARN", source: "COMPLIANCE", msg: "BR-ANNABA down — 3 unverified checks" },
    ],
    _audit: [],
    _pickup: { series: "sniffer", row: "branch-automation" },
    _health: { ok: null, host: "", at: null },
    _hostname: "CORE-EDGE",
    _securityChecks: [
      { id: "ssh-version", check: "SSH version 2 enforced", category: "TRANSPORT & SESSION", severity: "high", status: "PASS", evidence: "Cisco-IOS-XE-native:native.ip.ssh.version: 2.0", remediation_id: "ssh-version" },
      { id: "vty-transport", check: "No unsafe Telnet transport on lines", category: "TRANSPORT & SESSION", severity: "critical", status: "PASS", evidence: "line.vty[0].transport.input.input[0]: ssh" },
      { id: "exec-timeout", check: "Idle session timeout (exec-timeout) set on lines", category: "TRANSPORT & SESSION", severity: "medium", status: "FAIL", evidence: "line vty present without exec-timeout", remediation_id: "exec-timeout" },
      { id: "password-encryption", check: "service password-encryption enabled", category: "AUTH & AAA", severity: "high", status: "PASS", evidence: "Cisco-IOS-XE-native:native.service.password-encryption[0]: None", remediation_id: "password-encryption" },
      { id: "enable-secret", check: "enable secret set with strong hash (type 9/5)", category: "AUTH & AAA", severity: "critical", status: "PASS", evidence: "Cisco-IOS-XE-native:native.enable.secret.type: 9" },
      { id: "aaa-auth", check: "AAA new-model with login method (TACACS+/RADIUS/local)", category: "AUTH & AAA", severity: "high", status: "PASS", evidence: "aaa.authentication.login[0].name: default" },
      { id: "tacacs-key", check: "TACACS+ server key not weak (0/7)", category: "AUTH & AAA", severity: "high", status: "FAIL", evidence: "tacacs.server[0].key.encryption: 7" },
      { id: "radius-key", check: "RADIUS server key not weak (0/7)", category: "AUTH & AAA", severity: "high", status: "PASS", evidence: "no RADIUS configured" },
      { id: "local-users", check: "Local accounts use strong secrets only", category: "AUTH & AAA", severity: "high", status: "PASS", evidence: "username[0].secret.encryption: 9" },
      { id: "http-plane", check: "HTTPS-only management plane (no plaintext HTTP)", category: "MANAGEMENT PLANE", severity: "critical", status: "WARN", evidence: "http.server: True | http.secure-server: True", remediation_id: "http-plane" },
      { id: "mgmt-acl", check: "Management plane restricted by access-list", category: "MANAGEMENT PLANE", severity: "medium", status: "WARN", evidence: "no ACL restricting management access" },
      { id: "domain-lookup", check: "IP domain-lookup disabled (anti-DNS poisoning)", category: "MANAGEMENT PLANE", severity: "low", status: "WARN", evidence: "domain lookup enabled by default", remediation_id: "domain-lookup" },
      { id: "snmp-community", check: "No weak SNMP community strings (public/private)", category: "MONITORING", severity: "critical", status: "PASS", evidence: "SNMP community not configured" },
      { id: "syslog", check: "Syslog host/trap configured", category: "MONITORING", severity: "medium", status: "WARN", evidence: "No syslog tracking configured", remediation_id: "syslog" },
      { id: "ntp", check: "NTP server configured (time integrity)", category: "MONITORING", severity: "medium", status: "WARN", evidence: "No NTP server configured", remediation_id: "ntp" },
      { id: "banner", check: "Legal banner (motd/login) set", category: "SERVICES & BANNER", severity: "medium", status: "WARN", evidence: "No banner configured", remediation_id: "banner" },
    ],
    _securityLedger: [
      { id: 8, ts: "2026-08-07 09:41:02", event_type: "SCAN", actor: "demo", action: "compliance-scan", payload: "{\"filename\": \"cat8kv_running_config_20260807.txt\", \"checks\": 16}", prev_hash: "c1f8…aa21", checksum: "3a40d8…b613" },
      { id: 7, ts: "2026-08-07 09:12:44", event_type: "AUTH", actor: "demo", action: "login", payload: "{}", prev_hash: "9be2…71dd", checksum: "c1f8…aa21" },
      { id: 6, ts: "2026-08-07 08:47:10", event_type: "VAULT", actor: "demo", action: "credentials-update", payload: "{\"host\": \"devnetsandboxiosxec8k.cisco.com\"}", prev_hash: "7ac4…90ee", checksum: "9be2…71dd" },
      { id: 5, ts: "2026-08-07 08:40:33", event_type: "WRITE", actor: "demo", action: "provision", payload: "{\"action\": \"add_branch\", \"site_name\": \"TIZI\", \"vlan_id\": 150}", prev_hash: "3f11…c2ab", checksum: "7ac4…90ee" },
      { id: 4, ts: "2026-08-07 08:40:01", event_type: "WRITE", actor: "demo", action: "provision:failed", payload: "{\"error\": \"RESTCONF 403 forbidden\"}", prev_hash: "8d02…77e0", checksum: "3f11…c2ab" },
      { id: 3, ts: "2026-08-07 08:31:55", event_type: "STATE", actor: "demo", action: "drift-check", payload: "{\"status\": \"CLEAN\"}", prev_hash: "6b93…1d4c", checksum: "8d02…77e0" },
      { id: 2, ts: "2026-08-07 08:31:12", event_type: "STATE", actor: "demo", action: "snapshot", payload: "{\"hostname\": \"CORE-EDGE\"}", prev_hash: "e0aa…88f2", checksum: "6b93…1d4c" },
      { id: 1, ts: "2026-08-07 08:20:09", event_type: "AUTH", actor: "demo", action: "login", payload: "{}", prev_hash: "10b4d9bf…b333", checksum: "e0aa…88f2" },
    ],
    _posture: {
      ok: true,
      ts: "2026-08-07 09:40:00",
      error: "",
      summary: { nacm: true, aaa_new_model: true, ssh_v2: true, http_secure: true, http_plain: true },
      items: [
        { kind: "nacm", path: "ietf-netconf-acm:nacm", data: { "ietf-netconf-acm:nacm": { "enable-nacm": true } }, error: "" },
        { kind: "aaa", path: "Cisco-IOS-XE-native:native/aaa", data: { "Cisco-IOS-XE-aaa:aaa": { "new-model": {} } }, error: "" },
        { kind: "ssh", path: "Cisco-IOS-XE-native:native/ip/ssh", data: { "Cisco-IOS-XE-native:ssh": { version: "2.0" } }, error: "" },
        { kind: "http", path: "Cisco-IOS-XE-native:native/ip/Cisco-IOS-XE-http:http", data: { "Cisco-IOS-XE-http:http": { server: true, "secure-server": true } }, error: "" },
      ],
    },
    _inventory: [
      { pn: "ISR4431/K9", sn: "FGC2245A1XX", desc: "Cisco ISR 4431 Integrated Services Router" },
      { pn: "WS-C2960X-24TS-L", sn: "FOC2221B0YY", desc: "Catalyst 2960-X 24-Port GigE" },
      { pn: "PWR-C1-350WAC", sn: "DTN2208C1ZZ", desc: "350W AC Power Supply" },
      { pn: "GLC-T", sn: "FTX1905T1AA", desc: "10/100/1000BASE-T SFP Module" },
    ],
    _ifaceConfig: [
      { name: "GigabitEthernet0/0/0", type: "ethernetCsmacd", enabled: "up", description: "WAN uplink", ip: "10.0.0.1/255.255.255.0" },
      { name: "GigabitEthernet0/0/1", type: "ethernetCsmacd", enabled: "down", description: "", ip: "" },
      { name: "GigabitEthernet0/0/2", type: "ethernetCsmacd", enabled: "down", description: "spare access port", ip: "" },
      { name: "GigabitEthernet0/0/3", type: "ethernetCsmacd", enabled: "down", description: "", ip: "" },
      { name: "Loopback0", type: "softwareLoopback", enabled: "up", description: "management", ip: "10.1.1.1/255.255.255.0" },
    ],
    _fields: {
      site_name: { required: true, type: "text", max: 24, pattern: "^[A-Za-z0-9_-]{1,32}$" },
      department_vlan: { required: true, type: "text", max: 32, pattern: "^[A-Za-z0-9_-]{1,32}$" },
      vlan_id: { required: true, type: "int", min: 2, max: 4094 },
      vlan_name: { required: true, type: "text", max: 32, pattern: "^[A-Za-z0-9_-]{1,32}$" },
      department_subnet: { required: true, type: "ipv4cidr" },
      gateway: { required: true, type: "ipv4" },
      router_wan_ip: { required: false, type: "ipv4" },
      router_trunk_port: { required: false, type: "text", max: 24 },
      port: { required: false, type: "text", max: 24 },
      pc_ip: { required: false, type: "ipv4" },
    },
    validate: (form) => {
      const errs = {};
      const IPV4 = /^\d{1,3}(\.\d{1,3}){3}$/;
      const SUBNET = /^\d{1,3}(\.\d{1,3}){3}\/\d{1,2}$/;
      const NAME = /^[A-Za-z0-9_-]{1,32}$/;
      const rules = {
        site_name: [NAME, "site name: letters, digits, - or _ (1-32)"],
        department_vlan: [NAME, "department vlan: letters, digits, - or _ (1-32)"],
        vlan_id: [null, "vlan id must be 2-4094"],
        vlan_name: [NAME, "vlan name: letters, digits, - or _ (1-32)"],
        department_subnet: [SUBNET, "must be IPv4/CIDR e.g. 10.1.100.0/24"],
        gateway: [IPV4, "must be IPv4 e.g. 10.1.100.1"],
        router_wan_ip: [IPV4, "must be IPv4"],
        router_trunk_port: [/^\S{1,24}$/, "1-24 chars, no spaces"],
        port: [/^\S{1,24}$/, "1-24 chars, no spaces"],
        pc_ip: [IPV4, "must be IPv4"],
      };
      for (const [k, v] of Object.entries(form)) {
        if (v === "" || v == null) continue;
        const rule = rules[k];
        if (!rule || !rule[0]) continue;
        if (k === "vlan_id") {
          const n = Number(v);
          if (!Number.isInteger(n) || n < 2 || n > 4094) errs[k] = rule[1];
        } else if (!rule[0].test(String(v))) {
          errs[k] = rule[1];
        }
      }
      return errs;
    },
    provision: async (form) => {
      await delay(900);
      mock._state.connected = true;
      mock._state.online = true;
      mock._logs.push({
        ts: new Date().toISOString().slice(0, 19).replace("T", " "),
        level: "OK", source: "PROVISION", msg: `deployed ${form.action} // ${form.site_name} // vlan ${form.vlan_id}`,
      });
      if (form.action === "add_branch") {
        mock._topology.devices.push({
          name: form.site_name, role: "branch", vlan: Number(form.vlan_id),
          site: form.site_name, subnet: form.department_subnet,
          ipv4: form.gateway, status: "up", uptime: 0,
        });
      }
      return { ok: true, action: form.action, site_name: form.site_name, vlan_id: form.vlan_id };
    },
    deleteSub: async (form) => {
      await delay(700);
      mock._topology.devices = mock._topology.devices.filter(
        (d) => !(d.role === "branch" && d.vlan === Number(form.vlan_id)));
      return { ok: true, site: form.site_name, vlan_id: form.vlan_id, detail: `demo teardown — subinterface for vlan ${form.vlan_id} removed` };
    },
    ping: async (host) => { await delay(600); return { ok: true, host: host, rtt: 12.4 }; },
    telemetry: async (kind) => { await delay(700); return mock._telemetry[kind] ?? mock._telemetry; },
    collectTelemetry: async (kind) => {
      await delay(900);
      const snap = mock._telemetry[kind] || mock._telemetry;
      if (snap && snap.ts) {
        snap.prev_ts = snap.ts;
        snap.ts = new Date().toISOString().slice(0, 19).replace("T", " ");
      }
      mock._logs.push({
        ts: new Date().toISOString().slice(0, 19).replace("T", " "),
        level: "OK", source: "TELEMETRY", msg: `collected ${kind}`,
      });
      return { ok: true, kind, queued: true };
    },
    health: async () => mock._health,
    checkHealth: async () => {
      await delay(700);
      const at = new Date().toTimeString().slice(0, 8);
      if (location.search.includes("dead=1")) {
        mock._health = { ok: false, host: mock._hostname, at };
        return mock._health;
      }
      mock._health = { ok: true, host: mock._hostname, at };
      mock._logs.push({
        ts: new Date().toISOString().slice(0, 19).replace("T", " "),
        level: "OK", source: "CONNECT", msg: `fabric probe ok (${mock._hostname})`,
      });
      return mock._health;
    },
    inventory: async () => { await delay(1000); return mock._inventory; },
    getHostname: async () => { await delay(700); return mock._hostname; },
    ifaceConfig: async () => { await delay(1100); return mock._ifaceConfig; },
    setHostname: async (name) => {
      await delay(900);
      mock._hostname = name;
      mock._logs.push({
        ts: new Date().toISOString().slice(0, 19).replace("T", " "),
        level: "OK", source: "HOSTNAME", msg: `hostname set to ${name}`,
      });
      return { ok: true, name };
    },
    setIfaceIp: async (iface, address, mask) => {
      await delay(900);
      mock._logs.push({
        ts: new Date().toISOString().slice(0, 19).replace("T", " "),
        level: "OK", source: "SET_IP", msg: `${iface} primary IPv4 ${address} ${mask}`,
      });
      return { ok: true, iface, address, mask };
    },
    setIfaceState: async (iface, up) => {
      await delay(700);
      const it = mock._ifaceConfig.find((x) => x.name === iface);
      if (it) it.enabled = up ? "up" : "down";
      mock._logs.push({
        ts: new Date().toISOString().slice(0, 19).replace("T", " "),
        level: "OK", source: "IFACE_STATE", msg: `${iface} -> ${up ? "up" : "down"}`,
      });
      return { ok: true, iface, up: !!up };
    },
    snapshot: async () => { await delay(1200); return { ok: true, saved_at: "2026-08-06 09:12", note: "baseline captured" }; },
    drift: async () => { await delay(1500); return {
      ok: true, status: "DRIFT", count: 3, baseline_exists: true,
      ts: "2026-08-06 09:14:00",
      diff: "interface GigabitEthernet0/0/0\n- description CORE-LINK\n+ description CORE-LINK-DEMO\n\nline vty 0 4\n+ exec-timeout 10 0\n\nip route 10.1.120.0 255.255.255.0 10.1.1.254\n- removed\n",
    }; },
    setBaseline: async () => { await delay(1200); return { ok: true, ts: "2026-08-06 09:15:00" }; },
    compliance: async () => { await delay(1500); return {
      score: 83, ts: "2026-08-13 09:41:02",
      counts: { pass: 5, fail: 1, warn: 0 },
      checks: [
        { name: "ntp", pass: true, status: "PASS", detail: "ntp server 172.16.2.10 — clock synchronized" },
        { name: "ssh", pass: true, status: "PASS", detail: "transport input ssh on vty 0-4" },
        { name: "snmp", pass: true, status: "PASS", detail: "ro community restricted to NOC subnet" },
        { name: "banner", pass: true, status: "PASS", detail: "MOTD legal banner present" },
        { name: "acl-inbound", pass: true, status: "PASS", detail: "inbound ACL applied on WAN interface" },
        { name: "logging", pass: false, status: "FAIL", detail: "no logging host configured — syslog lost" },
      ],
    }; },
    scanCompliance: async () => { await delay(400); return { ok: true, queued: true, collect: true }; },
    security: async () => {
      await delay(600);
      const counts = { pass: 0, fail: 0, warn: 0 };
      for (const c of mock._securityChecks) counts[c.status.toLowerCase()]++;
      const score = Math.round(100 * counts.pass / mock._securityChecks.length);
      return {
        ok: true,
        scan: { ts: "2026-08-07 09:41:02", filename: "cat8kv_running_config_20260807.txt" },
        score, counts, checks: mock._securityChecks,
        ledger: mock._securityLedger,
        verify: { ok: true, total: mock._securityLedger.length, broken_at: null, last_hash: mock._securityLedger[0].checksum },
      };
    },
    securityPosture: async (force) => {
      await delay(800);
      return { ...mock._posture, ts: new Date().toISOString().slice(0, 19).replace("T", " ") };
    },
    verifyAudit: async () => {
      await delay(400);
      return { ok: true, total: mock._securityLedger.length, broken_at: null, last_hash: mock._securityLedger[0].checksum };
    },
    remediate: async (checkId, ack, value) => {
      await delay(1200);
      if (!ack) return { ok: false, reason: "confirmation required" };
      const check = mock._securityChecks.find((c) => c.id === checkId);
      if (!check) return { ok: false, reason: `no remediation defined for ${checkId}` };
      check.status = "PASS";
      check.evidence = "remediated " + new Date().toISOString().slice(0, 19).replace("T", " ");
      mock._securityLedger.unshift({
        id: mock._securityLedger.length + 1, ts: new Date().toISOString().slice(0, 19).replace("T", " "),
        event_type: "REMEDIATION", actor: "demo", action: checkId,
        payload: JSON.stringify({ path: "mock://" + checkId, body: { note: "demo write — nothing reached the device", value } }),
        prev_hash: "…", checksum: "demo-ledger-entry",
      });
      mock._logs.push({
        ts: new Date().toISOString().slice(0, 19).replace("T", " "),
        level: "OK", source: "REMEDIATE", msg: `${checkId} applied (${check.check})`,
      });
      const counts = { pass: 0, fail: 0, warn: 0 };
      for (const c of mock._securityChecks) counts[c.status.toLowerCase()]++;
      const total = mock._securityChecks.length;
      return {
        ok: true, check_id: checkId,
        summary: `Applied ${check.check}`,
        diff: { path: "mock://" + checkId },
        scan: {
          score: Math.round(100 * counts.pass / total),
          ts: new Date().toISOString().slice(0, 19).replace("T", " "),
          counts,
          checks: mock._securityChecks.map((c) => ({ id: c.id, status: c.status })),
        },
      };
    },
    remediateAll: async (ack) => {
      await delay(1400);
      if (!ack) return { ok: false, reason: "confirmation required" };
      const valueReq = { "enable-secret": 1, syslog: 1, ntp: 1 };
      const results = [];
      for (const c of mock._securityChecks) {
        if (c.status === "FAIL" && valueReq[c.id]) {
          results.push({ id: c.id, ok: null, reason: "needs-operator-value" });
        } else if (c.status === "FAIL") {
          c.status = "PASS";
          c.evidence = "remediated (fix-all) " + new Date().toISOString().slice(0, 19).replace("T", " ");
          results.push({ id: c.id, ok: true });
        }
      }
      mock._logs.push({
        ts: new Date().toISOString().slice(0, 19).replace("T", " "),
        level: "OK", source: "REMEDIATE", msg: `fix-all: ${results.filter((r) => r.ok === true).length} applied`,
      });
      const counts = { pass: 0, fail: 0, warn: 0 };
      for (const c of mock._securityChecks) counts[c.status.toLowerCase()]++;
      return {
        ok: true, results,
        scan: {
          score: Math.round(100 * counts.pass / mock._securityChecks.length),
          ts: new Date().toISOString().slice(0, 19).replace("T", " "),
          counts, checks: mock._securityChecks.map((c) => ({ id: c.id, status: c.status })),
        },
      };
    },
    revert: async (checkId, ack) => {
      await delay(1200);
      if (!ack) return { ok: false, reason: "confirmation required" };
      const check = mock._securityChecks.find((c) => c.id === checkId);
      if (!check) return { ok: false, reason: `no revert defined for ${checkId}` };
      const defaultPhrase = "Authorized access only. All activity is monitored.";
      check.evidence = "default banner restored — " + new Date().toISOString().slice(0, 19).replace("T", " ");
      mock._securityLedger.unshift({
        id: mock._securityLedger.length + 1, ts: new Date().toISOString().slice(0, 19).replace("T", " "),
        event_type: "REMEDIATION", actor: "demo", action: `revert:${checkId}`,
        payload: JSON.stringify({ path: "mock://" + checkId, body: { default: defaultPhrase } }),
        prev_hash: "…", checksum: "demo-ledger-entry",
      });
      mock._logs.push({
        ts: new Date().toISOString().slice(0, 19).replace("T", " "),
        level: "OK", source: "REVERT", msg: `${checkId} reverted (${check.check})`,
      });
      return { ok: true, check_id: checkId, summary: "restored the default banner phrase", action: "revert", diff: { path: "mock://" + checkId } };
    },
    factory: async (checkId, ack) => {
      await delay(1200);
      if (!ack) return { ok: false, reason: "confirmation required" };
      const check = mock._securityChecks.find((c) => c.id === checkId);
      if (!check) return { ok: false, reason: `no factory spec for ${checkId}` };
      check.status = "FAIL";
      check.evidence = "No banner configured — factory default restored (demo)";
      mock._securityLedger.unshift({
        id: mock._securityLedger.length + 1, ts: new Date().toISOString().slice(0, 19).replace("T", " "),
        event_type: "REMEDIATION", actor: "demo", action: `factory:${checkId}`,
        payload: JSON.stringify({ path: "mock://" + checkId, delete: true }),
        prev_hash: "…", checksum: "demo-ledger-entry",
      });
      mock._logs.push({
        ts: new Date().toISOString().slice(0, 19).replace("T", " "),
        level: "OK", source: "FACTORY", msg: `${checkId} removed (${check.check})`,
      });
      const counts = { pass: 0, fail: 0, warn: 0 };
      for (const c of mock._securityChecks) counts[c.status.toLowerCase()]++;
      const total = mock._securityChecks.length;
      return {
        ok: true, check_id: checkId, summary: "removed the MOTD banner",
        action: "factory", diff: { path: "mock://" + checkId, delete: true },
        scan: {
          score: Math.round(100 * counts.pass / total),
          ts: new Date().toISOString().slice(0, 19).replace("T", " "),
          counts,
          checks: mock._securityChecks.map((c) => ({ id: c.id, status: c.status })),
        },
      };
    },
    stats: async () => { await delay(300); return mock._stats; },
    netconfModules: async () => {
      await delay(400);
      return {
        ok: true, count: 329,
        modules: [
          { name: "ietf-interfaces", revision: "2018-02-20" },
          { name: "ietf-ip", revision: "2018-02-22" },
          { name: "openconfig-interfaces", revision: "2022-01-13" },
          { name: "ietf-netconf-monitoring", revision: "2010-10-04" },
          { name: "ietf-ospf", revision: "2019-03-04" },
          { name: "ietf-netconf-acm", revision: "2018-02-14" },
          { name: "Cisco-IOS-XE-native", revision: "2025-01-01" },
          { name: "Cisco-IOS-XE-device-hardware-oper", revision: "2024-07-01" },
        ],
      };
    },
    netconfSchema: async (module) => {
      await delay(500);
      if (!module) return { ok: false, error: "no module given" };
      return {
        ok: true, module, len: 0, truncated: false,
        text: `module ${module} {\n  namespace "urn:demo:${module}";\n  prefix d;\n\n  /* demo schema — the live NETCONF server returns the real YANG source\n     via <get-schema>; this placeholder exists so the explorer renders\n     in ?demo without a device. */\n  container ${module.replace(/-/g, "")} {\n    leaf name { type string; }\n  }\n}\n`,
      };
    },
    netconfGet: async (filterXml) => {
      await delay(600);
      if (!filterXml || !filterXml.trim()) return { ok: false, error: "empty filter" };
      return {
        ok: true, len: 0,
        xml: `<data xmlns="urn:ietf:params:xml:ns:netconf:base:1.0">\n  <interfaces xmlns="urn:ietf:params:xml:ns:yang:ietf-interfaces">\n    <interface>\n      <name>GigabitEthernet1</name>\n      <enabled>true</enabled>\n    </interface>\n  </interfaces>\n</data>\n<!-- demo reply — live runs the subtree get on :830 -->`,
      };
    },
    netconfNamespace: async (module) => {
      await delay(200);
      return { ok: true, module, namespace: "urn:ietf:params:xml:ns:yang:ietf-interfaces" };
    },
    scanVlans: async () => {
      await delay(500);
      const used = {};
      (mock._topology.devices || []).forEach((d) => { if (d.vlan) used[d.vlan] = d.site || ""; });
      return {
        ok: true, via: "restconf-vlan-oper", count: Object.keys(used).length,
        used: Object.keys(used).map(Number).sort((a, b) => a - b),
        names: Object.fromEntries(Object.entries(used).map(([k, v]) => [k, v])),
        used_names: Object.entries(used).map(([vlan, site]) =>
          ({ name: String(site).toLowerCase(), vlan: Number(vlan) })),
        suggestion: (() => { let i = 100; while (used[i]) i++; return i; })(),
      };
    },
    provisionPlan: async () => {
      await delay(500);
      const branches = (mock._topology.devices || [])
        .filter((d) => d.role === "branch" && d.vlan)
        .map((d) => ({ vlan: d.vlan, site: d.site, subnet: d.subnet, gateway: d.ipv4 }));
      const ifaces = (mock._telemetry.interfaces.entries || []).map((i) => i.name);
      return { ok: true, via: "db-cached", branches, wan_ip: "172.16.2.1/24", ifaces };
    },
    cliRun: async (command) => {
      await delay(700);
      if (!command || !command.trim()) return { ok: false, error: "empty command" };
      const first = command.trim().split(/[\s/]+/)[0].toLowerCase();
      if (!["show", "dir", "more", "ping", "traceroute", "terminal"].includes(first)) {
        return { ok: false, error: `refused: '${first}' — only read-only verbs allowed (show / dir / more / ping / traceroute)` };
      }
      return {
        ok: true, command, len: 0,
        output: `Interface              IP-Address      OK? Method Status                Protocol\nGigabitEthernet1        172.16.1.1       YES NVRAM  up                    up\nGigabitEthernet2        unassigned      YES NVRAM  administratively down down\n\n<!-- demo reply for '${command}' — the live run goes over SSH :22 via netmiko -->`,
      };
    },
    cliArchiveDiff: async () => {
      await delay(800);
      return {
        ok: true, command: "show archive config diff", len: 0,
        output: "! LAST CONFIG CHANGE AT 2026-08-06 09:12\n--- show archive config diff\n+ interface GigabitEthernet1.911\n+  encapsulation dot1Q 911\n<!-- demo reply — live server runs the real diff over SSH :22 -->",
      };
    },
    configHistory: async () => {
      await delay(300);
      return {
        ok: true, count: 4, baseline: true,
        items: [
          { file: "devnetsandboxiosxec8k.cisco.com_running_config_20260806_091200.txt", ts: "20260806_091200", size: 23451 },
          { file: "devnetsandboxiosxec8k.cisco.com_running_config_20260805_140030.txt", ts: "20260805_140030", size: 23110 },
          { file: "devnetsandboxiosxec8k.cisco.com_running_config_20260804_081555.txt", ts: "20260804_081555", size: 23002 },
          { file: "devnetsandboxiosxec8k.cisco.com_running_config_20260803_173212.txt", ts: "20260803_173212", size: 22994 },
        ],
      };
    },
    configDiff: async (fileA, fileB) => {
      await delay(600);
      if (fileB === "baseline") {
        return {
          ok: true, a: fileA || "latest", b: "baseline", lines: 3,
          diff: "--- latest\n+++ baseline\n@@ banner motd @@\n- banner motd ^CAuthorized access only. All activity is monitored.^C\n+ no banner motd\n<!-- demo diff — the live server diffs saved snapshots with difflib -->",
        };
      }
      return { ok: true, a: fileA || "latest", b: fileB || "previous", lines: 0, diff: "", note: "snapshots are identical" };
    },
    watchdog: async () => {
      await delay(500);
      return {
        ok: true,
        summary: { critical: 1, warn: 2, info: 1 },
        note: "compared last two snapshots",
        window: ["09:12", "09:07"],
        alerts: [
          { severity: "critical", iface: "GigabitEthernet1", kind: "link-down", detail: "link dropped between snapshots", ts: "09:12" },
          { severity: "warn", iface: "GigabitEthernet2", kind: "port-flap", detail: "3 flap(s) since last snapshot", ts: "09:12" },
          { severity: "warn", iface: "GigabitEthernet3", kind: "error-burst", detail: "+142 input/output errors since last snapshot", ts: "09:12" },
          { severity: "info", iface: "GigabitEthernet4", kind: "port-flap", detail: "1 flap(s) since last snapshot", ts: "09:12" },
        ],
      };
    },
    dnsAdd: async (domain) => {
      await delay(600);
      if (!domain || !domain.trim()) return { ok: false, error: "domain required" };
      mock._logs.push({
        ts: new Date().toISOString().slice(0, 19).replace("T", " "),
        level: "OK", source: "DNS", msg: `domain ${domain} added (POST demo)`,
      });
      return { ok: true, domain, note: "demo write — nothing reached the device" };
    },
    ifaceIpDelete: async (iface) => {
      await delay(600);
      if (!iface || !iface.trim()) return { ok: false, error: "interface required" };
      mock._logs.push({
        ts: new Date().toISOString().slice(0, 19).replace("T", " "),
        level: "OK", source: "IFACE", msg: `primary IPv4 removed from ${iface} (DELETE demo)`,
      });
      return { ok: true, iface, note: "demo write — nothing reached the device" };
    },
    dashboard: async () => {
      await delay(300);
      return JSON.parse(JSON.stringify(mock._dashboard));
    },
    logs: async () => { await delay(300); return [...mock._logs].reverse(); },
    audit: async () => { await delay(300); return mock._audit; },
    series: async () => mock._series,
    trends: async () => mock._trends,
    analyticsDeep: async (span = 200) => {
      await delay(400);
      const a = mock._analytics;
      a.grow();                                        /* demo feed advances per poll */
      mock._stats.snapshots += 1;
      const n = Math.min(Math.max(Number(span) || 200, 10), a.cpu.vals.length);
      const take = (arr) => arr.slice(-n);
      return {
        span: n,
        cpu: { x: take(a.cpu.x), vals: take(a.cpu.vals) },
        mem: { x: take(a.mem.x), vals: take(a.mem.vals) },
        up: { x: take(a.up.x), vals: take(a.up.vals) },
        errors: { x: take(a.errors.x), vals: take(a.errors.vals) },
        avail: { x: take(a.avail.x), vals: take(a.avail.vals), up: take(a.avail.up), down: take(a.avail.down) },
        arp: { x: take(a.arp.x), vals: take(a.arp.vals) },
        thr: { x: take(a.thr.x), rx: take(a.thr.rx), tx: take(a.thr.tx) },
        errs: { x: take(a.errs.x), in_errors: take(a.errs.in_errors), out_errors: take(a.errs.out_errors), crc: take(a.errs.crc), flaps: take(a.errs.flaps) },
        talkers: a.talkers.map((t) => ({ ...t, vals: take(t.vals) })),
        problems: a.problems,
        speeds: a.speeds,
        audit: { ...a.audit },
        pkt: a.pkt,
        hourly: a.hourly,
      };
    },
    topology: async () => mock._topology,
    topologyRaw: async () => ({ raw: mock._telemetry.raw, ts: "2026-08-06 09:12" }),
    hosts: async () => mock._hosts,
    pickup: async () => mock._pickup,
    setPickup: async (k, v) => { mock._pickup[k] = v; return mock._pickup; },
    profile: async () => mock._state.profile,
    updateProfile: async (p) => { Object.assign(mock._state.profile, p); return mock._state.profile; },
    creds: async () => mock._state.creds,
    testCreds: async (c) => {
      await delay(900);
      if (!c || !c.host || !c.username || !c.password) {
        return { ok: false, error: "host, username and password are all required" };
      }
      if (String(c.host).toLowerCase().includes("fail")) {
        return { ok: false, error: "authentication failed — wrong username or password (mock 401)" };
      }
      return { ok: true, hostname: mock._hostname, user: c.username };
    },
    updateCreds: async (c) => { Object.assign(mock._state.creds, c); return mock._state.creds; },
    saveVpn: async (c) => {
      const pw = c.password ? "********" : mock._state.vpn.password;
      Object.assign(mock._state.vpn, c, { password: pw });
      return mock._state.vpn;
    },
    _vpnUp: false,
    vpnStatus: async () => {
      await delay(250);
      const b = { ...mock._state.backend, tunnel: mock._vpnUp };
      if (mock._vpnUp) {
        b.source = "reservation";
        b.host = mock._state.vpn.device_host || "10.10.20.48";
        b.identity = "cat8000v-reservation";
      }
      return {
        client: true, cli: mock._vpnUp ? "connected" : "disconnected",
        tunnel: mock._vpnUp,
        address: mock._state.vpn.address,
        backend: b,
      };
    },
    setBackend: async (mode) => {
      mock._state.backend = { ...mock._state.backend, mode };
      return { ok: true, backend: mock._state.backend };
    },
    saveRes: async (slug, rec) => {
      const cur = mock._state.res_creds[slug] || { slug };
      const pw = rec.password ? "********" : cur.password;
      mock._state.res_creds[slug] = { ...cur, ...rec, password: pw };
      return { ok: true, set: mock._state.res_creds[slug] };
    },
    vpnConnect: async () => {
      await delay(1600);
      if (!mock._state.vpn.address) return { ok: false, error: "vpn-credentials-missing" };
      mock._vpnUp = true;
      return { ok: true, connected: true };
    },
    vpnDisconnect: async () => {
      await delay(500);
      mock._vpnUp = false;
      return { ok: true };
    },
    state: async () => mock._state,
    setMode: async (m) => { mock._state.mode = m; return mock._state; },
    logout: async () => { mock._state.session = null; return { ok: true }; },
    login: async (u, p) => {
      await delay(500);
      if (u === "admin" && p === "admin") {
        mock._state.session = { username: u, role: "admin", at: new Date().toISOString() };
        return { ok: true, session: mock._state.session };
      }
      return { ok: false, error: "bad credentials" };
    },
  };

  return {
    get mode() { return hasBridge() ? "live" : (DEMO ? "mock" : "nocore"); },
    isLive: () => !!hasBridge(),
    isDemo: () => DEMO,
    call,
    getState: () => call("state", []),
    setMode: (m) => call("setMode", [m]),
    login: (u, p) => call("login", [u, p]),
    logout: () => call("logout", []),
    profile: () => call("profile", []),
    updateProfile: (p) => call("updateProfile", [p]),
    creds: () => call("creds", []),
    testCreds: (c) => call("testCreds", [c]),
    updateCreds: (c) => call("updateCreds", [c]),
    saveVpn: (c) => call("saveVpn", [c]),
    vpnStatus: () => call("vpnStatus", []),
    vpnConnect: () => call("vpnConnect", []),
    vpnDisconnect: () => call("vpnDisconnect", []),
    setBackend: (mode) => call("setBackend", [mode]),
    saveRes: (slug, rec) => call("saveRes", [slug, rec]),
    validate: (form) => call("validate", [form]),
    series: () => call("series", []),
    trends: () => call("trends", []),
    stats: () => call("stats", []),
    analyticsDeep: (span) => call("analyticsDeep", [span]),
    dashboard: () => call("dashboard", []),
    topology: () => call("topology", []),
    topologyRaw: () => call("topologyRaw", []),
    hosts: () => call("hosts", []),
    telemetry: (kind) => call("telemetry", [kind]),
    collectTelemetry: (kind) => call("collectTelemetry", [kind]),
    health: () => call("health", []),
    checkHealth: () => call("checkHealth", []),
    inventory: () => call("inventory", []),
    getHostname: () => call("getHostname", []),
    ifaceConfig: () => call("ifaceConfig", []),
    setHostname: (name) => call("setHostname", [name]),
    setIfaceIp: (iface, address, mask) => call("setIfaceIp", [iface, address, mask]),
    setIfaceState: (iface, up) => call("setIfaceState", [iface, up]),
    telemetryRaw: () => call("telemetryRaw", []),
    pickup: () => call("pickup", []),
    setPickup: (k, v) => call("setPickup", [k, v]),
    provision: (form) => call("provision", [form]),
    deleteSub: (form) => call("deleteSub", [form]),
    ping: (host) => call("ping", [host]),
    snapshot: () => call("snapshot", []),
    drift: () => call("drift", []),
    setBaseline: () => call("setBaseline", []),
    compliance: () => call("compliance", []),
    scanCompliance: (collect = true) => call("scanCompliance", [collect]),
    security: () => call("security", []),
    securityPosture: (force) => call("securityPosture", [force]),
    verifyAudit: () => call("verifyAudit", []),
    remediate: (checkId, ack, value) => call("remediate", [checkId, ack, value]),
    remediateAll: (ack) => call("remediateAll", [ack]),
    revert: (checkId, ack) => call("revert", [checkId, ack]),
    factory: (checkId, ack) => call("factory", [checkId, ack]),
    netconfModules: () => call("netconfModules", []),
    netconfSchema: (module) => call("netconfSchema", [module]),
    netconfGet: (filterXml) => call("netconfGet", [filterXml]),
    netconfNamespace: (module) => call("netconfNamespace", [module]),
    scanVlans: (fresh) => call("scanVlans", [fresh]),
    provisionPlan: (fresh) => call("provisionPlan", [fresh]),
    cliRun: (command) => call("cliRun", [command]),
    cliArchiveDiff: () => call("cliArchiveDiff", []),
    configHistory: () => call("configHistory", []),
    configDiff: (fileA, fileB) => call("configDiff", [fileA, fileB]),
    watchdog: () => call("watchdog", []),
    dnsAdd: (domain) => call("dnsAdd", [domain]),
    ifaceIpDelete: (iface) => call("ifaceIpDelete", [iface]),
    logs: () => call("logs", []),
    audit: () => call("audit", []),
    task: (id, payload) => call("task", [id, payload]),
  };
})();

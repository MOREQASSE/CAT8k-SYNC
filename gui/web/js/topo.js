/* topo.js — production-grade SVG mission map (namespace-aware).
   - Tiered smart layout from the backend {center, devices, links} model.
   - Device glyphs use the real network-device icons from gui/icons
     (router / switch / server / endpoint / cloud), tinted by state.
   - Packet-Tracer-style drag: grab any node and the links re-route live;
     release to keep the new location.
   Browsers only render elements created via createElementNS in the SVG
   namespace — plain createElement("g|line|circle|text") yields invisible
   HTML elements (the classic "pile of labels" symptom). */
"use strict";

const NS = "http://www.w3.org/2000/svg";

function svgEl(tag, attrs = {}, ...children) {
  const node = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.setAttribute("class", v);
    else if (k === "text") node.textContent = v;
    else if (k === "style") node.setAttribute("style", v);
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else if (v != null && v !== false) node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat(1)) {
    if (c == null) continue;
    if (c.nodeType) node.append(c);
    else node.append(document.createTextNode(String(c)));
  }
  return node;
}

const Topo = (() => {
  const W = 1200, H = 840, CX = W / 2, CY = 560;
  let data = null, onSelect = null;
  let pan = { x: 0, y: 0 }, k = 1;
  let dragging = false, sx = 0, sy = 0;
  let nodeDrag = null, dragGhostClick = false;
  let nodes = [], selected = null, svg = null, inner = null;
  let posById = {}, edgeRefs = [];

  /* gui/icons glyphs served via /cust-icons/ — exact filenames (typos included). */
  const CUSTOM = {
    router:  { up: "router-stacked-pile", warn: "router-warning-beside-it", down: "router-error-screen" },
    cloud:   { up: "cloud-server", warn: "cloud-server", down: "cloud-server" },
    network: { up: "network-switch-sucess-tick-beside", warn: "network-switch-with-warning-beside", down: "network-switch-with-warning-beside" },
    switch:  { up: "network-switch-sucess-tick-beside", warn: "network-switch-with-warning-beside", down: "network-switch-with-warning-beside" },
    server:  { up: "server-sucess-tick", warn: "server-error-cross", down: "server-error-cross" },
    endpoint:{ up: "cartoon-laptop-terminal", warn: "isometric-desktop-computer", down: "isometric-desktop-computer" },
  };
  const ICON_BOX = {
    router: [58, 44], cloud: [56, 42], network: [56, 40],
    switch: [56, 40], server: [64, 36], endpoint: [46, 44],
  };
  const NEEDED = [...new Set(Object.values(CUSTOM).flatMap((v) => Object.values(v)))];

  /* ---------- icon bank: inline gui/icons svgs into a hidden <symbol> bank ---------- */
  let iconBank = null;
  function load() {
    if (iconBank) return iconBank;
    iconBank = Promise.all(NEEDED.map(async (id) => {
      try {
        const r = await fetch("cust-icons/" + id + ".svg");
        if (!r.ok) return null;
        return { id, svg: await r.text() };
      } catch (e) { return null; }
    })).then((items) => {
      let bank = document.getElementById("cust-icon-bank");
      if (!bank) {
        bank = document.createElementNS(NS, "svg");
        bank.setAttribute("id", "cust-icon-bank");
        bank.setAttribute("style", "position:absolute;width:0;height:0;overflow:hidden");
        document.body.appendChild(bank);
      }
      for (const it of items) {
        if (!it) continue;
        const tmp = document.createElement("div");
        tmp.innerHTML = it.svg;
        const src = tmp.querySelector("svg");
        if (!src) continue;
        const sym = document.createElementNS(NS, "symbol");
        sym.setAttribute("id", "cust-" + it.id);
        const vb = src.getAttribute("viewBox");
        if (vb) sym.setAttribute("viewBox", vb);
        while (src.firstChild) sym.appendChild(src.firstChild);
        bank.appendChild(sym);
      }
      return true;
    });
    return iconBank;
  }

  function pickIcon(d) {
    const st = d.state || (d.up ? "up" : "down");
    const m = CUSTOM[d.kind] || CUSTOM.network;
    return "cust-" + (m[st] || m.up);
  }

  function tier(d) {
    if (d.role === "wan") return 0;
    if (d.role === "branch") return 1;
    return 2; // loop / port / misc
  }

  function place(d, i, n, t) {
    if (t === 0) return { x: CX, y: CY - 330 };                          // wan uplink, top
    if (t === 1) {                                                          // outer branch arc
      const rx = 320 + 12 * n, ry = 205;
      const a = Math.PI - Math.PI * (i + 0.5) / Math.max(n, 1);
      return { x: CX + Math.cos(a) * rx, y: CY + Math.sin(a) * ry };
    }
    const xs = [330, 870];                                                  // loop columns
    const ys = [];
    for (let j = 0; j < Math.ceil(n / 2); j++) ys.push(620 - j * 128);
    const col = i < Math.ceil(n / 2) ? 0 : 1;
    const row = i % Math.ceil(n / 2);
    return { x: xs[col], y: ys[row] };
  }

  function rad(d) { return d.role === "wan" ? 26 : d.role === "branch" ? 30 : 24; }

  function subLabel(d) {
    if (d.role === "wan") return "WAN UPLINK\n" + (d.cidr || d.iface || "ISP");
    if (d.role === "branch") return [d.cidr, d.site, d.vlan ? "VL" + d.vlan : ""].filter(Boolean).join(" · ");
    if (d.role === "loop") return "MGMT · " + (d.cidr || "ROUTER ID");
    return (d.state || "up").toUpperCase() + (d.cidr ? " · " + d.cidr : "");
  }

  function toSvg(clientX, clientY) {
    const r = svg ? svg.getBoundingClientRect() : { left: 0, top: 0, width: W, height: H };
    return { x: (clientX - r.left) / (r.width / W), y: (clientY - r.top) / (r.height / H) };
  }

  function roleTag(d, st) {
    if (d.role === "wan") return "INTERNET";
    if (d.role === "loop") return "LOOPBACK";
    if (d.role === "branch") return "BRANCH LAN";
    if (d.kind === "switch") return "SWITCH";
    if (d.kind === "endpoint") return "ENDPOINT";
    return st.toUpperCase();
  }

  function setSelected(id) {
    selected = id;
    if (!svg) return;
    svg.querySelectorAll(".topo-node").forEach((g) => {
      g.setAttribute("class", g.getAttribute("class").replace(/\s*selected/g, "").trim());
    });
    if (id) {
      const sel = svg.querySelector(`.topo-node[data-host="${id}"]`);
      if (sel) sel.setAttribute("class", sel.getAttribute("class") + " selected");
    }
    if (onSelect && id && data) {
      const t = data.topology || data;
      if (id === (t.center.id || "core")) onSelect(t.center);
      else onSelect((t.devices || []).find((d) => d.id === id));
    }
  }

  function redrawEdge(ed) {
    const p1 = posById[ed.from];
    const p2 = posById[ed.to];
    if (!p1 || !p2) return;
    const dx = p2.x - p1.x, dy = p2.y - p1.y, d = Math.hypot(dx, dy) || 1;
    const stop = ed.rad + 10;
    const x2 = p2.x - (dx / d) * stop, y2 = p2.y - (dy / d) * stop;
    ed.line.setAttribute("x1", p1.x); ed.line.setAttribute("y1", p1.y);
    ed.line.setAttribute("x2", x2);   ed.line.setAttribute("y2", y2);
    ed.lbl.setAttribute("x", (p1.x + x2) / 2 - 6);
    ed.lbl.setAttribute("y", (p1.y + y2) / 2 - 7);
  }

  function redrawAll() { edgeRefs.forEach(redrawEdge); }

  function apply() {
    if (inner) inner.setAttribute("transform", `translate(${pan.x},${pan.y}) scale(${k})`);
  }

  function bind(host, dataset, cb) {
    data = dataset;
    onSelect = cb;
    host.innerHTML = "";
    nodes = []; edgeRefs = []; selected = null; posById = {}; nodeDrag = null;

    const topo = dataset.topology || dataset;
    const center = topo.center || {};
    const devices = topo.devices || [];
    const edges = topo.links || [];

    svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, xmlns: NS, onclick: () => setSelected(null) });
    const g = svgEl("g", { transform: "translate(0,0) scale(1)" });
    svg.appendChild(g);
    inner = g;
    host.appendChild(svg);

    g.appendChild(svgEl("defs", {}, [svgEl("marker", {
      id: "topo-arrow", markerWidth: 8, markerHeight: 8, refX: 6.5, refY: 4, orient: "auto",
    }, [svgEl("path", { d: "M0,0 L8,4 L0,8", class: "topo-arrow-p" })])]));

    /* coordinates for every node */
    const spots = { 0: [], 1: [], 2: [] };
    devices.forEach((d) => spots[tier(d)].push(d));
    posById[center.id || "core"] = { x: CX, y: CY };
    for (const t of [0, 1, 2]) spots[t].forEach((d, i) => { posById[d.id] = place(d, i, spots[t].length, t); });

    /* ---- link lines (re-wired live while dragging) ---- */
    edges.forEach((e) => {
      const end = devices.find((d) => d.id === e.to);
      const line = svgEl("line", {
        class: "topo-link" + (e.state === "up" ? " live" : e.state === "warn" ? " warn" : ""),
        "marker-end": "url(#topo-arrow)",
      });
      const lbl = svgEl("text", { class: "topo-link-lbl", "text-anchor": "end",
        text: e.vlan ? "VL " + e.vlan : (e.iface || "") });
      g.insertBefore(line, g.firstChild);
      g.insertBefore(lbl, g.firstChild);
      edgeRefs.push({ from: "core", to: e.to, rad: end ? rad(end) : 22, line, lbl });
    });

    /* ---- center router ---- */
    const cid = center.id || "core";
    nodes.push(svgEl("g", {
      class: "topo-node core", "data-host": cid,
      transform: `translate(${CX},${CY})`,
      onclick: (e) => { e.stopPropagation(); if (dragGhostClick) { dragGhostClick = false; return; } setSelected(cid); },
      onpointerdown: (e) => { e.stopPropagation(); startDrag(e, cid); },
    },
      svgEl("circle", { class: "n-ring", cx: 0, cy: 0, r: 62 }),
      svgEl("circle", { class: "n-bg core", cx: 0, cy: 0, r: 50 }),
      svgEl("use", { class: "n-ic core", href: "#cust-router-stacked-pile", x: -36, y: -25, width: 72, height: 50 }),
      svgEl("text", { class: "n-txt", y: 94, "text-anchor": "middle", "font-size": "12px",
        text: (center.hostname || "CORE").split(".")[0].toUpperCase().slice(0, 16) }),
      svgEl("text", { class: "n-sub", y: 110, "text-anchor": "middle",
        text: "FABRIC CORE ROUTER" }),
    ));

    /* ---- device nodes ---- */
    devices.forEach((d) => {
      const p = posById[d.id];
      if (!p) return;
      const r = rad(d);
      const st = d.state || ((d.up || d.up === undefined) ? "up" : "down");
      const [iw, ih] = ICON_BOX[d.kind] || ICON_BOX.network;
      nodes.push(svgEl("g", {
        class: "topo-node" + (st === "down" ? " bad" : st === "warn" ? " warn" : " live"),
        "data-host": d.id,
        transform: `translate(${p.x},${p.y})`,
        onclick: (e) => { e.stopPropagation(); if (dragGhostClick) { dragGhostClick = false; return; } setSelected(d.id); },
        onpointerdown: (e) => { e.stopPropagation(); startDrag(e, d.id); },
      },
        svgEl("circle", { class: "n-ring", cx: 0, cy: 0, r: r + 9 }),
        svgEl("circle", { class: "n-bg", cx: 0, cy: 0, r: r }),
        svgEl("use", { class: "n-ic", href: "#" + pickIcon(d),
          x: -iw / 2, y: -ih / 2 - r + 16, width: iw, height: ih }),
        svgEl("text", { class: "n-txt", y: -r - 14, "text-anchor": "middle", text: d.hostname }),
        svgEl("text", { class: "n-sub", y: r + 22, "text-anchor": "middle", text: subLabel(d) }),
        svgEl("text", { class: "n-tag", y: r + 42, "text-anchor": "middle",
          text: roleTag(d, st) }),
      ));
    });
    nodes.forEach((n) => g.appendChild(n));

    redrawAll();

    if (!devices.length) {
      const empty = document.createElement("div");
      empty.setAttribute("class", "topo-empty");
      empty.textContent = "NO LIVE TOPOLOGY — RUN \u201CFETCH LIVE MAP\u201D TO PULL REAL DEVICES";
      host.appendChild(empty);
    }

    /* ---- drag a node: re-wire links live ---- */
    function startDrag(ev, id) {
      const cur = posById[id];
      const pt = toSvg(ev.clientX, ev.clientY);
      nodeDrag = { id, ox: cur.x, oy: cur.y, sx: pt.x, sy: pt.y };
      dragGhostClick = false;
    }
    window.addEventListener("pointermove", (e) => {
      if (!nodeDrag) return;
      const pt = toSvg(e.clientX, e.clientY);
      const nx = pt.x - nodeDrag.sx + nodeDrag.ox;
      const ny = pt.y - nodeDrag.sy + nodeDrag.oy;
      if (Math.abs(nx - nodeDrag.ox) + Math.abs(ny - nodeDrag.oy) > 3) {
        dragGhostClick = true;
        moveDragged(nodeDrag.id, nx, ny);
      }
    });
    window.addEventListener("pointerup", () => { nodeDrag = null; });

    /* ---- canvas pan / zoom ---- */
    host.addEventListener("mousedown", (e) => {
      if (e.target.closest(".topo-node")) return;
      dragging = true; sx = e.clientX; sy = e.clientY;
      svg.classList.add("dragging");
    });
    window.addEventListener("mousemove", (e) => {
      if (!dragging) return;
      pan.x += e.clientX - sx; pan.y += e.clientY - sy;
      sx = e.clientX; sy = e.clientY;
      apply();
    });
    window.addEventListener("mouseup", () => { dragging = false; svg.classList.remove("dragging"); });
    host.addEventListener("wheel", (e) => {
      e.preventDefault();
      const d = e.deltaY < 0 ? 1.1 : 0.9;
      k = Math.min(3.2, Math.max(0.3, k * d));
      apply();
    }, { passive: false });

    const zoomBox = document.createElement("div");
    zoomBox.setAttribute("class", "topo-zoom");
    zoomBox.innerHTML = "<button data-z=\"in\">+</button><button data-z=\"out\">-</button><button data-z=\"reset\" title=\"reset view\">⟳</button>";
    zoomBox.querySelector("[data-z=in]").onclick = () => { k = Math.min(3.2, k * 1.2); apply(); };
    zoomBox.querySelector("[data-z=out]").onclick = () => { k = Math.max(0.3, k / 1.2); apply(); };
    zoomBox.querySelector("[data-z=reset]").onclick = () => { pan = { x: 0, y: 0 }; k = 1; apply(); };
    host.appendChild(zoomBox);
    apply();
  }

  function moveDragged(id, x, y) {
    posById[id] = { x, y };
    const elg = svg.querySelector(`.topo-node[data-host="${id}"]`);
    if (elg) elg.setAttribute("transform", `translate(${x},${y})`);
    redrawAll();
  }

  return { bind, load };
})();
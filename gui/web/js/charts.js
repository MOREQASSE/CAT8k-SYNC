/* charts.js — hand-rolled SVG chart primitives for the CAT8k-SYNC dashboard.
   Zero dependencies, offline, dark-theme tuned. Every chart returns an
   HTML element; callers append it wherever they want.

   Design rule: SVG carries geometry only (gridlines, shapes, cursors) so
   container scaling never distorts text; axis labels are HTML overlays. */
"use strict";

const Charts = (() => {
  const NSV = "http://www.w3.org/2000/svg";
  const sv = (tag, attrs = {}, children = []) => {
    const n = document.createElementNS(NSV, tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      n.setAttribute(k, v === true ? "" : String(v));
    }
    for (const c of [].concat(children)) {
      if (c == null) continue;
      n.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
    }
    return n;
  };
  const fmt = (v) => (v == null ? "0" : Number.isInteger(v) ? String(v) : v.toFixed(1));
  const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

  /* shared hover tooltip inside a wrapper (wrapper must be position:relative) */
  function tipFor(wrap) {
    let box = wrap.querySelector(".chart-tip");
    if (!box) {
      box = document.createElement("div");
      box.className = "chart-tip";
      wrap.appendChild(box);
    }
    return box;
  }
  function tipShow(box, cx, cy, html) {
    box.innerHTML = html;
    box.classList.add("on");
    const r = box.parentElement.getBoundingClientRect();
    let x = clamp(cx + 14, 4, Math.max(4, r.width - box.offsetWidth - 8));
    let y = cy - box.offsetHeight - 10;
    if (y < 4) y = cy + 14;
    box.style.left = x + "px";
    box.style.top = y + "px";
  }
  function tipHide(box) { box.classList.remove("on"); }

  /* catmull-rom -> bezier smoothing for professional lines */
  function smoothPath(pts) {
    if (pts.length < 2) return "";
    let d = `M${pts[0].x.toFixed(1)},${pts[0].y.toFixed(1)}`;
    for (let i = 0; i < pts.length - 1; i++) {
      const p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2;
      const c1x = p1.x + (p2.x - p0.x) / 6, c1y = p1.y + (p2.y - p0.y) / 6;
      const c2x = p2.x - (p3.x - p1.x) / 6, c2y = p2.y - (p3.y - p1.y) / 6;
      d += ` C${c1x.toFixed(1)},${c1y.toFixed(1)} ${c2x.toFixed(1)},${c2y.toFixed(1)} ${p2.x.toFixed(1)},${p2.y.toFixed(1)}`;
    }
    return d;
  }

  function emptyChart(msg, sub) {
    return el("div", { class: "chart-empty" }, [
      el("div", { class: "chart-empty-ico" }, "∅"),
      el("div", { class: "chart-empty-t", text: msg || "NO HISTORY YET" }),
      el("div", { class: "chart-empty-s", text: sub || "snapshot the fabric to seed this chart" }),
    ]);
  }

  /* y gridlines (svg) + y labels (HTML overlay) for a chart body */
  function yAxis(P, iw, ih, min, span, unit, gt) {
    const lines = [], labels = [];
    for (let g = 0; g <= gt; g++) {
      const v = min + (span * g) / gt;
      const gy = P.t + ih - (g / gt) * ih;
      lines.push(sv("line", { x1: P.l, y1: gy, x2: P.l + iw, y2: gy, class: "ch-grid" }));
      labels.push(el("span", {
        style: `bottom:${(g / gt) * 100}%`,
        text: `${Math.round(v)}${unit || ""}`,
      }));
    }
    return { lines, labels };
  }

  /* x tick labels as an HTML row (absolutely positioned over the plot area).

     Overlap-proof by construction, then verified after layout:
     - step picks at most `maxTicks` labels AND the final point is only
       labelled when it lands a comfortable distance from the step grid
       (`(last % step) >= step/2`), so tick pairs never stack;
     - first / last labels justify to the plot edges (no half-clip);
     - a post-layout sweep hides any tick that still collides with the
       previous one (dense windows shrink gracefully instead of mushing). */
  function xTicks(x, n, step, maxTicks = 7) {
    const row = el("div", { class: "tx-xtick" });
    if (n <= 1) {
      row.append(el("span", { style: "left:50%", title: String(x[0] || ""), text: String(x[0] || "") }));
      return row;
    }
    if (!(step > 0)) step = Math.max(1, Math.ceil((n - 1) / Math.max(1, maxTicks)));
    const last = n - 1;
    const showLast = (last % step) >= step / 2;
    x.forEach((t, i) => {
      if (i % step !== 0 && !(showLast && i === last)) return;
      const style = i === 0 ? "left:0;transform:none"
        : i === last ? "left:100%;transform:translateX(-100%)"
        : `left:${(i / last) * 100}%`;
      row.append(el("span", { "data-x": i === 0 ? "e0" : i === last ? "e1" : String((i / last) * 100),
        style, title: String(t), text: String(t) }));
    });
    /* collapse pass: hide any tick that measurably collides with its
       neighbour. Uses layout boxes (clientWidth / offsetWidth) — immune to
       transforms and cssText normalization — and re-runs whenever the
       row's true size changes (entrance animations, resizes, font swaps). */
    const sweep = () => {
      const w = row.clientWidth;
      const spans = [...row.querySelectorAll("span")];
      if (!w) return;
      let prevR = -Infinity;
      spans.forEach((sp) => {
        sp.style.visibility = "";
        const ow = Math.max(sp.offsetWidth, 6.4 * sp.textContent.length + 6);
        if (!ow) return;
        const m = sp.getAttribute("data-x") || "50";
        let l, r;
        if (m === "e0") { l = 0; r = ow; }
        else if (m === "e1") { l = w - ow; r = w; }
        else {
          let c = (w * parseFloat(m)) / 100;
          const raw = c;
          c = Math.max(ow / 2, Math.min(c, w - ow / 2));
          if (c !== raw) sp.style.left = (c / w) * 100 + "%";
          l = c - ow / 2; r = c + ow / 2;
        }
        if (prevR <= l + 2) prevR = r;
        else sp.style.visibility = "hidden";
      });
    };
    requestAnimationFrame(() => requestAnimationFrame(sweep));
    for (let p = 1; p <= 7; p++) setTimeout(sweep, p * 350);
    if (typeof ResizeObserver !== "undefined") {
      const ro = new ResizeObserver(() => sweep());
      ro.observe(row);
      if (row._ro) row._ro.disconnect();
      row._ro = ro;
    }
    return row;
  }

  function legend(series) {
    return el("div", { class: "ch-legend" }, series.map((s) =>
      el("span", { class: "ch-key" }, [
        el("span", { class: "ch-key-dot", style: `background:${s.color}` }),
        el("span", { text: s.name }),
      ])));
  }

  /* ------------------------------------------------------------ area / line
     opts: { series: [{name, color, vals}], x: [labels], h, unit } */
  function area(opts = {}) {
    const x = opts.x || [];
    const series = (opts.series || []).map((s) => ({ ...s, vals: (s.vals || []).map(Number) }));
    const n = x.length;
    if (!n || !series.length || !series.some((s) => s.vals.some((v) => isFinite(v)))) {
      return emptyChart("NO TREND SERIES", "run a snapshot to start the CPU / memory history");
    }
    const W = 640, H = opts.h || 200;
    const P = { l: 44, r: 14, t: 12, b: 6 };
    const iw = W - P.l - P.r, ih = H - P.t - P.b;
    const all = series.flatMap((s) => s.vals).filter((v) => isFinite(v));
    const rawMax = Math.max(...all, 1);
    const rawMin = Math.min(...all, 0);
    const max = rawMax + (rawMax - rawMin) * 0.12 || 1;
    const min = Math.max(0, rawMin - (rawMax - rawMin) * 0.12);
    const span = max - min || 1;
    const X = (i) => (n === 1 ? P.l + iw / 2 : P.l + (i / (n - 1)) * iw);
    const Y = (v) => P.t + ih - ((v - min) / span) * ih;

    const wrap = el("div", { class: "chart-wrap area-wrap", style: `height:${H}px` });
    const box = tipFor(wrap);

    const { lines: grid, labels: yLbls } = yAxis(P, iw, ih, min, span, opts.unit, 3);
    const ylbls = el("div", { class: "ch-ylbls" }, yLbls);
    const xtick = xTicks(x, n);

    const layers = series.map((s, si) => {
      const id = "chg" + Math.floor(Math.random() * 1e9) + si;
      const pts = s.vals.map((v, i) => ({ x: X(i), y: Y(v) }));
      const line = sv("path", { d: smoothPath(pts), fill: "none", stroke: s.color,
        "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" });
      const fill = sv("path", {
        d: `${smoothPath(pts)} L${X(n - 1).toFixed(1)},${(H - P.b).toFixed(1)} L${X(0).toFixed(1)},${(H - P.b).toFixed(1)} Z`,
        fill: `url(#${id})`, stroke: "none", opacity: 0.9,
      });
      return { group: sv("g", {}, [fill, line]), pts, id, color: s.color, name: s.name };
    });

    /* hover crosshair */
    const overlay = sv("rect", { x: P.l, y: P.t, width: iw, height: ih, fill: "transparent",
      class: "ch-hover" });
    const cursor = sv("g", { class: "ch-cursor" }, [sv("line", { y1: P.t, y2: H - P.b, class: "ch-cross" })]);
    const dots = layers.map(() => sv("circle", { r: 3.2, class: "ch-dot" }));
    cursor.append(...dots);
    let active = -1;
    const setIdx = (i) => {
      if (i === active) return;
      active = i;
      const xx = X(i);
      cursor.querySelector("line").setAttribute("x1", xx);
      cursor.querySelector("line").setAttribute("x2", xx);
      layers.forEach((L, li) => {
        const d = dots[li], v = L.pts[i];
        if (v) { d.setAttribute("cx", v.x); d.setAttribute("cy", v.y);
          d.setAttribute("fill", L.color); d.setAttribute("opacity", 1); }
        else d.setAttribute("opacity", 0);
      });
      tipShow(box, xx, P.t, el("div", {}, [
        el("div", { class: "chart-tip-x", text: String(x[i] || "") }),
        ...layers.map((L) => el("div", { class: "chart-tip-row" }, [
          el("span", { class: "chart-tip-dot", style: `background:${L.color}` }),
          el("span", { class: "chart-tip-k", text: L.name }),
          el("span", { class: "chart-tip-v", text: fmt(L.vals[i]) + (opts.unit || "") }),
        ])),
      ]).outerHTML);
    };
    overlay.addEventListener("mousemove", (e) => {
      const r = overlay.getBoundingClientRect();
      const fx = ((e.clientX - r.left) / r.width) * iw;
      setIdx(clamp(Math.round((fx / iw) * (n - 1)), 0, n - 1));
    });
    overlay.addEventListener("mouseleave", () => {
      active = -1;
      cursor.querySelector("line").removeAttribute("x1");
      cursor.querySelector("line").removeAttribute("x2");
      dots.forEach((d) => d.setAttribute("opacity", 0));
      tipHide(box);
    });

    const svg = sv("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%", height: "100%", class: "area-svg" }, [
      sv("defs", {}, layers.map((L) => sv("linearGradient", { id: L.id, x1: 0, y1: 0, x2: 0, y2: 1 }, [
        sv("stop", { offset: 0, "stop-color": L.color, "stop-opacity": 0.32 }),
        sv("stop", { offset: 1, "stop-color": L.color, "stop-opacity": 0.01 }),
      ]))),
      ...grid, ...layers.map((L) => L.group), cursor, overlay,
    ]);
    wrap.append(svg, ylbls);
    if (series.length > 1) wrap.append(legend(series));
    wrap.append(xtick);
    return wrap;
  }

  /* ------------------------------------------------------------ donut
     opts: { slices: [{label, value, color}], center: str, centerSub: str, h,
             emptyMsg, emptySub, legendPct, hot: label-of-dominant-slice } */
  function donut(opts = {}) {
    const slices = (opts.slices || []).filter((s) => (s.value || 0) > 0);
    const total = slices.reduce((a, s) => a + s.value, 0);
    if (!slices.length || !total) {
      return emptyChart(opts.emptyMsg || "NO AUDIT DATA", opts.emptySub || "run a compliance scan to populate");
    }
    const R = 58, C = 2 * Math.PI * R;
    const H = opts.h || 196;
    const W = (R + 22) * 2;
    const cx = R + 22, cy = R + 22;
    let off = 0;
    const segs = slices.map((s) => {
      const len = (s.value / total) * C;
      const hot = opts.hot != null && s.label === opts.hot;
      const seg = sv("circle", { cx, cy, r: R, fill: "none", stroke: s.color,
        "stroke-width": hot ? 12 : 8, "stroke-linecap": "butt",
        "stroke-dasharray": `${Math.max(len - 1.5, 0.8)} ${C - Math.max(len - 1.5, 0.8) + 1.5}`,
        "stroke-dashoffset": -off, transform: `rotate(-90 ${cx} ${cy})`, class: hot ? "ch-seg ch-seg-hot" : "ch-seg" });
      off += len;
      return seg;
    });
    const wrap = el("div", { class: "chart-wrap donut-wrap" });
    const box = tipFor(wrap);
    const svg = sv("svg", { viewBox: `0 0 ${W} ${H}`, height: H, class: "donut-svg" }, [
      sv("circle", { cx, cy, r: R, fill: "none", stroke: "rgba(148,197,255,.08)", "stroke-width": 8 }),
      ...segs,
    ]);
    svg.addEventListener("mousemove", (e) => {
      const r = svg.getBoundingClientRect();
      const sx = r.width / W, sy = r.height / H;
      const px = (e.clientX - r.left) / sx - cx, py = (e.clientY - r.top) / sy - cy;
      const a = Math.atan2(py, px) * 180 / Math.PI + 90;
      const deg = ((a % 360) + 360) % 360;
      let acc = 0;
      for (const s of slices) {
        acc += (s.value / total) * 360;
        if (deg <= acc) {
          tipShow(box, e.clientX - r.left, e.clientY - r.top,
            `<div class="chart-tip-x">${s.label}</div><div class="chart-tip-v">${s.value} · ${Math.round((s.value / total) * 100)}%</div>`);
          return;
        }
      }
    });
    svg.addEventListener("mouseleave", () => tipHide(box));
    wrap.append(
      el("div", { class: "donut-box", style: `height:${H}px` }, [
        svg,
        el("div", { class: "donut-center" }, [
          el("div", { class: "donut-val", text: opts.center != null ? String(opts.center) : fmt(total) }),
          el("div", { class: "donut-sub", text: opts.centerSub || "TOTAL" }),
        ]),
      ]),
      el("div", { class: "ch-legend" }, slices.map((s) => {
        const pct = Math.round((s.value / total) * 100);
        const vtxt = s.value >= 1e9 ? (s.value / 1e9).toFixed(2) + "B"
          : s.value >= 1e6 ? (s.value / 1e6).toFixed(2) + "M"
          : s.value >= 1e3 ? (s.value / 1e3).toFixed(1) + "K"
          : String(s.value);
        return el("span", { class: "ch-key" }, [
          el("span", { class: "ch-key-dot", style: `background:${s.color}` }),
          el("span", { text: `${s.label} ${vtxt}${opts.legendPct ? ` · ${pct}%` : ""}` }),
        ]);
      })),
    );
    return wrap;
  }

  /* ------------------------------------------------------------ grouped bars
     opts: { labels, series: [{name, color, vals}], h, unit } */
  function bars(opts = {}) {
    const labels = opts.labels || [];
    const series = (opts.series || []).map((s) => ({ ...s, vals: (s.vals || []).map(Number) }));
    const n = labels.length;
    const hasData = series.some((s) => s.vals.some((v) => v > 0));
    if (!n || !series.length || !hasData) {
      return emptyChart("NO TRAFFIC DATA", "telemetry history will populate this chart");
    }
    const W = 640, H = opts.h || 200;
    const P = { l: 44, r: 14, t: 12, b: 6 };
    const iw = W - P.l - P.r, ih = H - P.t - P.b;
    const max = Math.max(...series.flatMap((s) => s.vals), 1) * 1.12;
    const G = series.length;
    const slot = iw / n, bw = Math.max(2, Math.min(20, (slot * 0.62) / G));

    const wrap = el("div", { class: "chart-wrap bars-wrap", style: `height:${H}px` });
    const box = tipFor(wrap);

    const { lines: grid, labels: yLbls } = yAxis(P, iw, ih, 0, max, opts.unit, 3);
    const ylbls = el("div", { class: "ch-ylbls" }, yLbls);
    const xtick = xTicks(labels, n);

    const groups = labels.map((lbl, i) => {
      const gx = P.l + slot * i + (slot - bw * G) / 2;
      return series.map((s, si) => {
        const v = s.vals[i] || 0;
        const bh = (v / max) * ih;
        const bar = sv("rect", { x: gx + si * bw, y: P.t + ih - bh, width: bw - 2,
          height: Math.max(bh, v > 0 ? 2 : 0), rx: 2, fill: s.color, opacity: 0.92, class: "ch-bar" });
        bar.addEventListener("mouseenter", () => {
          tipShow(box, gx + si * bw + bw, P.t + ih - bh,
            `<div class="chart-tip-x">${lbl}</div><div class="chart-tip-row"><span class="chart-tip-dot" style="background:${s.color}"></span><span class="chart-tip-k">${s.name}</span><span class="chart-tip-v">${fmt(v)}${opts.unit || ""}</span></div>`);
        });
        bar.addEventListener("mouseleave", () => tipHide(box));
        return bar;
      });
    });

    wrap.append(sv("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%", height: "100%", class: "bars-svg" },
      [...grid, ...groups.flat()]), ylbls);
    if (G > 1) wrap.append(legend(series));
    wrap.append(xtick);
    return wrap;
  }

  /* ------------------------------------------------------------ heatmap (24h)
     opts: { cells: [24 nums], h, label } */
  function heat(opts = {}) {
    const cells = (opts.cells || []).slice(0, 24);
    const max = Math.max(...cells, 1);
    const H = opts.h || 200;
    const W = 640, P = { l: 44, r: 14, t: 12, b: 6 };
    const iw = W - P.l - P.r, ih = H - P.t - P.b;
    const cw = iw / 24;
    const wrap = el("div", { class: "chart-wrap heat-wrap", style: `height:${H}px` });
    const box = tipFor(wrap);
    const cellOf = (v) => {
      const t = v / max;
      if (!v) return "rgba(148,197,255,.05)";
      if (t > 0.8) return "rgba(244,87,87,.9)";
      return `rgba(56,189,248,${(0.18 + t * 0.8).toFixed(2)})`;
    };
    const cellsSvg = cells.map((v, i) => {
      const c = sv("rect", { x: P.l + i * cw + 1.5, y: P.t + 2, width: cw - 3, height: ih - 4,
        rx: 3, fill: cellOf(v), class: "heat-cell" });
      c.addEventListener("mousemove", (e) => {
        const r = c.getBoundingClientRect();
        tipShow(box, e.clientX - r.left + (r.left - wrap.getBoundingClientRect().left),
          e.clientY - r.top, `<div class="chart-tip-x">${String(i).padStart(2, "0")}:00 — ${String(i).padStart(2, "0")}:59</div><div class="chart-tip-v">${v} event${v === 1 ? "" : "s"}</div>`);
      });
      c.addEventListener("mouseleave", () => tipHide(box));
      return c;
    });
    const ticks = [0, 6, 12, 18, 23].map((h) =>
      el("span", { text: `${String(h).padStart(2, "0")}h` }));
    const xtick = el("div", { class: "tx-xtick" });
    for (let h = 0; h < 24; h++) {
      if ([0, 6, 12, 18, 23].includes(h)) {
        const sp = ticks.shift();
        sp.style.left = (h / 23) * 100 + "%";
        if (h === 0) sp.style.transform = "none";
        else if (h === 23) sp.style.transform = "translateX(-100%)";
        xtick.append(sp);
      }
    }
    wrap.append(sv("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%", height: "100%", class: "heat-svg" }, cellsSvg));
    wrap.append(xtick);
    return wrap;
  }

  /* ------------------------------------------------------------ radial gauge
     opts: { value, max=100, color, label, sub, h, unit, r } */
  function gauge(opts = {}) {
    const val = Math.max(0, Math.min(opts.max || 100, Number(opts.value) || 0));
    const max = opts.max || 100;
    const R = opts.r || 52, W = R * 2 + 30, H = opts.h || 120;
    const cx = W / 2, cy = R + 10;
    const arc = Math.PI; /* semicircle */
    const len = arc * R;
    const frac = val / max;
    const dash = `${Math.max(frac * len - 2, 0.5)} ${len * 2}`;
    const wrap = el("div", { class: "chart-wrap gauge-wrap" });
    const svg = sv("svg", { viewBox: `0 0 ${W} ${H}`, width: "100%", height: "100%", class: "gauge-svg" }, [
      sv("path", { d: `M ${cx - R} ${cy} A ${R} ${R} 0 0 1 ${cx + R} ${cy}`, fill: "none",
        stroke: "rgba(148,197,255,.1)", "stroke-width": 11, "stroke-linecap": "round" }),
      sv("path", { d: `M ${cx - R} ${cy} A ${R} ${R} 0 0 1 ${cx + R} ${cy}`, fill: "none",
        stroke: opts.color || "var(--teal)", "stroke-width": 11, "stroke-linecap": "round",
        "stroke-dasharray": dash, "stroke-dashoffset": len, class: "ch-seg" }),
      ...(opts.max != null ? [0.25, 0.5, 0.75].map((t) => {
        const a = Math.PI * (1 - t);
        const x1 = cx + Math.cos(Math.PI - a) * (R + 7), y1 = cy - Math.sin(a) * (R + 7);
        const x2 = cx + Math.cos(Math.PI - a) * (R - 7), y2 = cy - Math.sin(a) * (R - 7);
        return sv("line", { x1, y1, x2, y2, class: "gauge-tick" });
      }) : []),
    ]);
    wrap.append(
      el("div", { class: "gauge-box", style: `height:${H}px` }, [
        svg,
        el("div", { class: "gauge-center" }, [
          el("div", { class: "gauge-val", text: fmt(val) + (opts.unit || "") }),
          el("div", { class: "gauge-sub", text: opts.label || "SCORE" }),
        ]),
      ]),
      opts.sub ? el("div", { class: "gauge-foot", text: opts.sub }) : null,
    );
    return wrap;
  }

  return { area, donut, bars, heat, gauge };
})();

/* views.js — every hosted view. Routes: auth, home, provision, telemetry,
   topology, audit, analytics, profile. Each renders into its host node. */
"use strict";

const Views = (() => {
  const { ic, toast, tag, statusTag, modal, Console, bars } = UI;

  /* positional wrapper over UI.field — also accepts the object form directly */
  const field = (a, ...rest) => {
    if (typeof a === "string") {
      const [label, options, value, type, placeholder, hint] = rest;
      return UI.field({ key: a, label, value, type, placeholder, hint, options });
    }
    return UI.field(a);
  };

  const delay = (ms) => new Promise((r) => setTimeout(r, ms));

  /* queue a live telemetry pull, then wait until the cached payload is newer */
  async function collectAndWait(kind) {
    const before = (await API.telemetry(kind).catch(() => ({})))?.ts;
    const r = await API.collectTelemetry(kind).catch(() => null);
    if (!r || !r.ok) return r;
    if (!before) { await delay(1100); return r; }
    for (let i = 0; i < 15; i++) {
      await delay(1000);
      const t = await API.telemetry(kind).catch(() => ({}));
      if (t && t.ts && t.ts !== before) break;
    }
    return r;
  }

  function spark(values, accent) { return bars(values || [0, 0, 0, 0, 0], accent); }

  const NSV = "http://www.w3.org/2000/svg";
  const sv = (tag, attrs = {}, children = []) => {
    const n = document.createElementNS(NSV, tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      n.setAttribute(k, v === true ? "" : String(v));
    }
    for (const c of [].concat(children)) { if (c != null) n.appendChild(c); }
    return n;
  };
  /* area chart: [{x, y}] → svg; y[] is normalized by the caller. */
  function trendChart(pts, opts = {}) {
    const W = opts.w || 560, Hgt = opts.h || 150, P = 8;
    const size = pts.length;
    const values = pts.map((p) => p.y);
    if (!size) return el("div", { class: "muted small", text: "no trend series yet" });
    const max = Math.max(...values, 1);
    const min = Math.min(...values, 0);
    const span = max - min || 1;
    const X = (i) => (size === 1 ? W / 2 : P + (i / (size - 1)) * (W - 2 * P));
    const Y = (v) => Hgt - P - ((v - min) / span) * (Hgt - 2 * P);
    const id = "tg" + Math.floor(Math.random() * 1e6);
    const line = pts.map((p, i) => `${X(i).toFixed(1)},${Y(p.y).toFixed(1)}`).join(" ");
    const area = sv("path", {
      d: `M${X(0).toFixed(1)},${Y(values[0]).toFixed(1)} L` + line.replace(/ /g, " L") +
        ` L${X(size - 1).toFixed(1)},${(Hgt - P).toFixed(0)} L${X(0).toFixed(1)},${(Hgt - P).toFixed(0)} Z`,
      fill: `url(#${id})`, stroke: "none",
    });
    const axisY = (v) => sv("text", { x: P, y: Y(v) - 3, class: "ax-lbl" });
    const s = sv("svg", { viewBox: `0 0 ${W} ${Hgt}`, width: "100%", height: Hgt, preserveAspectRatio: "none" }, [
      sv("defs", {}, [sv("linearGradient", { id, x1: 0, y1: 0, x2: 0, y2: 1 }, [
        sv("stop", { offset: 0, "stop-color": opts.color || "#2dd4bf", "stop-opacity": 0.35 }),
        sv("stop", { offset: 1, "stop-color": opts.color || "#2dd4bf", "stop-opacity": 0.02 }),
      ])]),
      sv("line", { x1: P, y1: Hgt - P, x2: W - P, y2: Hgt - P, class: "grid-line" }),
      sv("polyline", { points: line, fill: "none", stroke: opts.color || "var(--teal)", "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }),
    ]);
    const lbl = el("div", { class: "tx-xtick" });
    lbl.append(...pts.map((p, i) => (i % Math.ceil(size / 8) === 0 || i === size - 1)
      ? el("span", { text: p.x }) : null));
    return el("div", {}, [s, lbl]);
  }
  function heroLite(title, sub, iconName) {
    return el("div", { class: "hero" }, [
      el("div", { class: "glyph" }, ic(iconName || "settings-2", 32, "var(--teal)")),
      el("div", {}, [
        el("h2", { text: title }),
        el("p", { text: sub }),
      ]),
      el("span", { class: "spacer" }),
      statusTag("online"),
    ]);
  }

  /* ---- deploy launch sequence -----------------------------------------
     origin: the DEPLOY button the user clicked; the rocket icon inside it
     escapes the button, grows, lands on a launch pad and lifts off. The
     async run() promise drives the real provisioning; the overlay finishes
     with a mission-accomplished or launch-aborted card. */
  const ROCKET_SVG = () => sv("svg", { viewBox: "0 0 120 176", width: 150, height: 220, class: "launch-ship" }, [
    sv("defs", {}, [
      sv("linearGradient", { id: "lg-body", x1: 0, y1: 0, x2: 1, y2: 1 }, [
        sv("stop", { offset: 0, "stop-color": "#f8fafc" }),
        sv("stop", { offset: 1, "stop-color": "#94a3b8" }),
      ]),
      sv("linearGradient", { id: "lg-fin", x1: 0, y1: 0, x2: 0, y2: 1 }, [
        sv("stop", { offset: 0, "stop-color": "#22d3ee" }),
        sv("stop", { offset: 1, "stop-color": "#0e7490" }),
      ]),
      sv("linearGradient", { id: "lg-flame", x1: 0, y1: 0, x2: 0, y2: 1 }, [
        sv("stop", { offset: 0, "stop-color": "#fff7ed" }),
        sv("stop", { offset: 0.35, "stop-color": "#fbbf24" }),
        sv("stop", { offset: 1, "stop-color": "#ea580c" }),
      ]),
    ]),
    sv("path", { d: "M60 4 C82 4 98 22 98 62 L98 118 C98 132 84 138 60 138 C36 138 22 132 22 118 L22 62 C22 22 38 4 60 4 Z", fill: "url(#lg-body)" }),
    sv("path", { d: "M34 96 L6 142 L24 136 Z", fill: "url(#lg-fin)" }),
    sv("path", { d: "M86 96 L114 142 L96 136 Z", fill: "url(#lg-fin)" }),
    sv("ellipse", { cx: 60, cy: 22, rx: 20, ry: 9, fill: "#ffffff", opacity: 0.55 }),
    sv("circle", { cx: 60, cy: 56, r: 13, fill: "#0b1220" }),
    sv("circle", { cx: 60, cy: 56, r: 15, fill: "none", stroke: "#22d3ee", "stroke-width": 2.5 }),
    sv("path", { d: "M24 118 L96 118 L92 130 L28 130 Z", fill: "#475569" }),
    sv("path", { d: "M44 138 L76 138 L70 152 L50 152 Z", fill: "#334155" }),
    sv("g", { class: "flame-g" }, [
      sv("ellipse", { cx: 60, cy: 156, rx: 20, ry: 30, fill: "url(#lg-flame)", opacity: 0.9 }),
      sv("ellipse", { cx: 60, cy: 156, rx: 11, ry: 20, fill: "#fde68a" }),
      sv("ellipse", { cx: 60, cy: 156, rx: 5, ry: 10, fill: "#ffffff" }),
    ]),
  ]);

  async function launchSequence({ origin, site, meta = [], run, onSuccess, onAbort }) {
    const t0 = performance.now();
    const T = () => `T+${((performance.now() - t0) / 1000).toFixed(1)}s`;
    const telBox = el("div", { class: "launch-telemetry" });
    const tel = (m) => telBox.appendChild(el("div", { class: "tl", text: `${T()}  ${m}` }));
    const stg = el("div", { class: "launch-stage", text: "ARMED" });
    const setStage = (label) => {
      stg.textContent = label;
      stg.classList.remove("pop");
      void stg.offsetWidth;
      stg.classList.add("pop");
    };

    const scene = el("div", { class: "launch-scene" }, [
      el("div", { class: "launch-pad" }, el("span", { class: "launch-pad-tag", text: "PAD P-1 // CAT8k-SYNC" })),
      el("div", { class: "launch-puff", style: "left:calc(50% - 96px);animation-delay:0s" }),
      el("div", { class: "launch-puff", style: "left:calc(50% - 40px);animation-delay:.4s" }),
      el("div", { class: "launch-puff", style: "left:calc(50% + 24px);animation-delay:.8s" }),
      el("div", { class: "launch-rocket" }, [ROCKET_SVG()]),
      el("div", { class: "launch-speed" }),
    ]);
    const msg = el("div", { class: "launch-msg" });
    const ov = el("div", { class: "launch-ov" }, [
      el("div", { class: "launch-sky" }),
      el("div", { class: "launch-stars" }),
      telBox, stg, scene, msg,
    ]);
    document.body.appendChild(ov);

    const armed = origin;
    const btnLbl = armed.lastChild;
    const btnIco = armed.firstChild;
    const origLbl = btnLbl.textContent;
    armed.classList.add("arming");
    armed.disabled = true;
    btnLbl.textContent = "IGNITION";
    btnIco.classList.add("arm-ic");

    const rect = armed.getBoundingClientRect();
    const clone = el("div", {
      class: "launch-clone",
      style: `left:${rect.left + rect.width / 2}px;top:${rect.top + rect.height / 2}px`,
    }, [ic("rocket", 16, "var(--teal)")]);
    document.body.appendChild(clone);
    requestAnimationFrame(() => requestAnimationFrame(() => {
      ov.classList.add("on");
      clone.classList.add("go");
    }));

    const close = () => {
      ov.remove();
      clone.remove();
      armed.classList.remove("arming");
      armed.disabled = false;
      btnLbl.textContent = origLbl;
      btnIco.classList.remove("arm-ic");
    };

    const rocket = scene.querySelector(".launch-rocket");
    tel("payload sealed — RESTCONF session queued");
    await delay(560);
    rocket.classList.add("enter");
    tel("launch pad ready — hold-down released");
    await delay(480);
    setStage("IGNITION");
    tel("ignition sequence start");
    rocket.classList.remove("enter");
    rocket.classList.add("ignite");
    scene.classList.add("burn");
    await delay(1500);
    setStage("LIFTOFF");
    tel("liftoff — pushing config to fabric");
    rocket.classList.remove("ignite");
    rocket.classList.add("lift");
    scene.classList.add("fly");
    await delay(1750);
    rocket.classList.remove("lift");
    rocket.classList.add("orbit");
    scene.classList.remove("burn", "fly");
    setStage("ORBIT — COMMIT PENDING");
    tel("in orbit — awaiting commit acknowledgment");

    let retries = 0;
    const tick = setInterval(() => tel(`still pushing — retry ${++retries}`), 2000);
    const p = run().then((r) => ({ r }), (e) => ({ r: { ok: false, detail: String((e && e.message) || e) } }));
    const res = (await Promise.all([p, delay(4300)]))[0].r;
    clearInterval(tick);

    if (res && res.ok) {
      setStage("COMMIT ACK — CHAIN APPENDED");
      tel("commit acknowledgment received — ledger entry written");
      onSuccess();
      await delay(750);
      rocket.classList.remove("orbit");
      rocket.classList.add("flyoff");
      scene.classList.add("clear");
      await delay(900);
      const card = el("div", { class: "launch-card ok" }, [
        el("div", { class: "burst" }, [ic("check", 44, "var(--green)")]),
        el("div", { class: "lc-title", text: "MISSION ACCOMPLISHED" }),
        el("div", { class: "lc-sub", text: `${site} is live on the fabric` }),
        el("div", { class: "lc-chips" }, meta.map(([k, v]) =>
          el("span", { class: "chip" }, [el("b", { text: k }), el("i", { text: String(v) }) ]))),
        el("button", { class: "btn teal", onclick: close }, [ic("check-circle-2", 15), "BACK TO STUDIO"]),
      ]);
      for (let i = 0; i < 16; i++) {
        msg.appendChild(el("span", {
          class: "conf",
          style: `--dx:${(Math.random() * 260 - 130).toFixed(0)}px;--dy:${(Math.random() * 190 + 50).toFixed(0)}px;` +
            `--rot:${(Math.random() * 360).toFixed(0)}deg;--d:${(Math.random() * 0.5).toFixed(2)}s;` +
            `--c:${["#06b6d4", "#10b981", "#f59e0b", "#f8fafc"][i % 4]}`,
        }));
      }
      msg.appendChild(card);
      msg.classList.add("show");
    } else {
      const why = (res && res.detail) || "fabric rejected the provision";
      setStage("LAUNCH ABORTED");
      tel("thrust lost — abort sequence");
      onAbort();
      rocket.classList.remove("orbit");
      rocket.classList.add("abort");
      scene.classList.add("clear");
      await delay(950);
      const card = el("div", { class: "launch-card bad" }, [
        el("div", { class: "burst" }, [ic("octagon-alert", 44, "var(--red)")]),
        el("div", { class: "lc-title", text: "LAUNCH ABORTED" }),
        el("div", { class: "lc-sub", text: why }),
        el("button", { class: "btn ghost gray", onclick: close }, "BACK TO STUDIO"),
      ]);
      msg.appendChild(card);
      msg.classList.add("show");
    }
  }

  /* ============================================================ AUTH — setup / login */
  async function auth(host) {
    const st = await API.getState();
    const isSetup = (st.mode == null || st.mode === "" || !st.creds || !st.creds.host)
      || location.search.includes("setup");

    host.appendChild(el("div", { class: "auth-brand" }, [
      el("div", { class: "brand-glyph glyph" }, [el("img", { src: "icons/LOGO.png", alt: "CAT8k-SYNC" })]),
      el("h2", { text: "CAT8k-SYNC" }),
      el("div", { class: "sub", text: isSetup ? "FIRST-RUN // FIELD SETUP" : "SECURE CONSOLE" }),
    ]));

    if (isSetup) {
      setupWizard(host, st);
    } else {
      const errBox = el("div", { class: "auth-error" });
      host.append(
        el("div", { class: "field", style: "grid-template-columns:1fr;max-width:360px;margin:0 auto" }, [
          el("label", { text: "USERNAME" }), el("input", { id: "login-u", autocomplete: "username" }),
        ]),
        el("div", { class: "field", style: "grid-template-columns:1fr;max-width:360px;margin:14px auto 0" }, [
          el("label", { text: "PASSWORD" }), el("input", { id: "login-p", type: "password", autocomplete: "current-password" }),
        ]),
        errBox,
        el("div", { style: "text-align:center;margin-top:8px" }, [
          el("button", { class: "btn teal", style: "min-width:200px", onclick: async () => {
            const r = await API.login(document.getElementById("login-u").value, document.getElementById("login-p").value);
            if (r && r.ok) { toast("session open", "ok"); App.enter(); }
            else errBox.textContent = (r && r.error) || "access denied";
          } }, [ic("log-in", 16), "OPEN SESSION"]),
        ]),
      );
      document.getElementById("login-u").focus();
    }
  }

  /* multi-step first-run wizard: OPERATOR -> MODE -> FABRIC -> ENGAGE */
  function setupWizard(host, st) {
    const w = {
      full_name: st.profile?.full_name || "", role: st.profile?.role || "",
      site: st.profile?.site || "", mode: st.mode || "provision",
      host: st.creds?.host || "", username: st.creds?.username || "",
      password: st.creds?.password || "", secret: st.creds?.secret || "",
    };
    const META = [
      ["01", "OPERATOR", "identity"],
      ["02", "MODE", "domain"],
      ["03", "FABRIC", "vault"],
      ["04", "ENGAGE", "commit"],
    ];
    let step = 0;

    const errBox = el("div", { class: "auth-error" });
    const prog = el("div", { class: "wiz-progress" });
    const body = el("div", { class: "wiz-body" });
    const backBtn = el("button", { class: "btn ghost gray", onclick: () => setStep(step - 1) }, [ic("chevron-left", 15), "BACK"]);
    const nextBtn = el("button", { class: "btn teal", onclick: () => next() }, [ic("chevron-right", 15), "CONTINUE →"]);
    const foot = el("div", { class: "wiz-foot" }, [backBtn, nextBtn]);

    function renderMarks() {
      prog.innerHTML = "";
      META.forEach(([no, t, s], i) => {
        const cls = i < step ? "wiz-step done" : i === step ? "wiz-step on" : "wiz-step";
        prog.append(el("div", { class: cls }, [
          el("div", { class: "wiz-mark" }, i < step ? ic("check", 14, "var(--green)") : el("span", { text: no })),
          el("div", { class: "lbl", text: t }),
          el("div", { class: "sub", text: s }),
        ]));
      });
    }

    function renderBody() {
      body.innerHTML = "";
      const wrap = el("div", { class: "stagger" });

      if (step === 0) {
        wrap.append(
          el("div", { class: "section-title" }, [el("span", { class: "no", text: "01" }), el("span", { class: "t", text: "OPERATOR IDENTITY" }), el("span", { class: "s", text: "who owns this console" })]),
          field({ key: "full_name", label: "OPERATOR NAME", value: w.full_name }),
          field({ key: "role", label: "ROLE", value: w.role }),
          field({ key: "site", label: "NOC SITE", value: w.site }),
        );
      } else if (step === 1) {
        wrap.append(
          el("div", { class: "section-title" }, [el("span", { class: "no", text: "02" }), el("span", { class: "t", text: "DOMAIN // MODE" }), el("span", { class: "s", text: "scope of live authority" })]),
          field("mode", "OPERATION MODE", [
            { v: "provision", t: "PROVISION // FULL DEPLOY" },
            { v: "sniffer", t: "SNIFFER // READ-ONLY" },
            { v: "monitor", t: "MONITOR // LIGHT" },
          ], w.mode),
          el("div", { class: "wiz-hint" }, [
            tag("PROVISION"), " full branch deploy — vlan, subinterface, trunk, gateway, baseline sync. ",
            tag("SNIFFER", "yellow"), " read-only telemetry + audits. ",
            tag("MONITOR", "blue"), " light cadence, zero write ops.",
          ]),
        );
      } else if (step === 2) {
        wrap.append(
          el("div", { class: "section-title" }, [el("span", { class: "no", text: "03" }), el("span", { class: "t", text: "FABRIC CREDENTIALS" }), el("span", { class: "s", text: "fernert vault — never logged" })]),
          el("div", { class: "wiz-hint" }, [
            "the web console reaches the Catalyst over ",
            tag("RESTCONF"), " (HTTPS :443) using ",
            tag("HOST"), " + ", tag("USERNAME"), " + ", tag("PASSWORD"),
          ]),
          field("host", "HOST / IP", null, w.host),
          field("username", "USERNAME", null, w.username),
          field("password", "PASSWORD", null, w.password, "password"),
          field("secret", "ENABLE SECRET", null, w.secret, "password", "optional — SSH / legacy transport only"),
          el("div", { class: "wiz-note" }, [
            tag("OPTIONAL", "yellow"),
            " not used by the web console — only the legacy SSH path consumes it, and it falls back to the password when left blank.",
          ]),
        );
      } else {
        const rows = [
          ["operator", w.full_name || "—"], ["role", w.role || "—"], ["site", w.site || "—"],
          ["mode", (w.mode || "provision").toUpperCase()], ["host", w.host || "—"], ["username", w.username || "—"],
          ["password", w.password ? "********" : "unset"], ["secret", w.secret ? "********" : "unset"],
        ];
        wrap.append(
          el("div", { class: "section-title" }, [el("span", { class: "no", text: "04" }), el("span", { class: "t", text: "REVIEW // COMMIT" }), el("span", { class: "s", text: "seal vault + open mission" })]),
          el("div", { class: "card", style: "padding:4px 14px" }, rows.map(([k, v]) =>
            el("div", { class: "row", style: "justify-content:space-between;border-bottom:1px solid var(--line);padding:8px 0" }, [
              el("span", { class: "muted mono small", text: k }),
              el("span", { class: "mono", text: v }),
            ]))),
        );
      }

      body.appendChild(wrap);
      body.querySelectorAll("[data-key]").forEach((inp) => {
        const k = inp.dataset.key;
        inp.addEventListener(inp.tagName === "SELECT" ? "change" : "input", (e) => { w[k] = e.target.value; });
        inp.addEventListener("keydown", (e) => { if (e.key === "Enter" && step < 3) next(); });
      });
      const first = body.querySelector("input, select");
      if (first) first.focus();
      errBox.textContent = "";
    }

    function setStep(i) {
      step = Math.max(0, Math.min(3, i));
      backBtn.style.visibility = step === 0 ? "hidden" : "visible";
      const icon = step === 3 ? "zap" : "chevron-right";
      const label = step === 3 ? "ENGAGE MISSION" : "CONTINUE →";
      nextBtn.replaceChildren(
        el("span", { html: ic(icon, 15) }),
        el("span", { text: label }),
      );
      renderMarks();
      renderBody();
    }

    function next() {
      if (step === 0 && !w.full_name.trim()) { errBox.textContent = "operator name required"; return; }
      if (step === 2 && (!w.host.trim() || !w.username.trim())) { errBox.textContent = "host + username required"; return; }
      if (step < 3) { setStep(step + 1); return; }
      engage();
    }

    async function engage() {
      const creds = {
        host: w.host.trim(), username: w.username.trim(),
        password: w.password, secret: w.secret,
      };
      nextBtn.disabled = true;
      await API.setMode(w.mode);
      await API.updateProfile({ full_name: w.full_name, role: w.role, site: w.site });
      await API.updateCreds(creds);
      Console.write("vault sealed // mode committed", "sys");
      toast("mission armed", "sys");
      App.enter();
    }

    host.append(prog, body, errBox, foot);
    setStep(0);
  }

  /* ============================================================ HOME / HUB */
  async function home(host) {
    host.classList.add("no-actions");
    try {
      const [st, d] = await Promise.all([API.getState(), API.dashboard()]);
      const stats = d.stats || {};
      const s = d.series || {};
      const cpu = s.cpu?.vals || [], mem = s.mem?.vals || [], up = s.up?.vals || [];
      const errs = s.errors?.vals || [];
      const at = d.audit_trend || {};
      const last = (a) => (a && a.length ? a[a.length - 1] : null);
      const lastAudit = last(at.score) ?? (typeof stats.compliance === "number" ? stats.compliance : 0);
      const curCpu = last(cpu), curMem = last(mem), curUp = last(up);
      const isLive = API.isLive();
      const isDemo = API.isDemo();

      /* ---------- KPI tiles ---------- */
      const kpi = (label, val, unit, icon, accent, chartEl, tall) =>
        el("div", { class: "dash-kpi" + (tall ? " tall" : ""), style: `--accent:${accent}` }, [
          el("div", { class: "kpi-head" }, [
            el("span", { class: "icon-tile" }, [ic(icon, 14, accent)]),
            el("span", { class: "kpi-lbl", text: label }),
          ]),
          val != null ? el("div", { class: "kpi-row" }, [
            el("span", { class: "kpi-num", text: String(val) }),
            el("span", { class: "kpi-unit", text: unit }),
          ]) : null,
          el("div", { class: "kpi-chart" }, chartEl),
        ]);
      const kpis = el("div", { class: "dash-kpis" }, [
        kpi("COMPLIANCE", null, null, "shield-check", "var(--green)",
          Charts.gauge({ value: lastAudit, max: 100, label: "SCORE", h: 120, r: 52, unit: "%" }), true),
        kpi("IFACES UP", curUp ?? stats.iface_ups ?? "—", "count", "wifi", "var(--teal)", spark(up, "var(--teal)")),
        kpi("SNAPSHOTS", stats.snapshots ?? 0, "recorded", "database", "var(--blue)", spark(cpu, "var(--blue)")),
        kpi("CPU", curCpu ?? "—", "%", "cpu", "var(--yellow)", spark(cpu, "var(--yellow)")),
        kpi("MEMORY", curMem ?? "—", "%", "memory-stick", "var(--teal)", spark(mem, "var(--teal)")),
        kpi("EVENTS 24H", d.hourly.reduce((a, b) => a + b, 0), "logged", "activity", "var(--red)", spark(d.hourly, "var(--red)")),
      ]);

      /* ---------- chart cards ---------- */
      const chartCard = (icon, title, hint, body) =>
        el("div", { class: "card chart-card" }, [
          el("div", { class: "card-head" }, [
            el("span", { class: "icon-tile" }, [ic(icon, 14, "var(--teal)")]),
            el("span", { class: "t", text: title }),
            el("span", { class: "s", text: hint }),
          ]),
          el("div", { class: "card-body chart-body" }, body),
        ]);

      const areaCard = chartCard("cpu", "PLATFORM LOAD", "snapshot history · cpu / memory %",
        Charts.area({ series: [
          { name: "CPU", color: "#fbbf24", vals: cpu },
          { name: "MEM", color: "#2dd4bf", vals: mem },
        ], x: s.cpu?.x || [], h: 196, unit: "%" }));

      const traffic = d.traffic || [];
      const tCard = chartCard("bar-chart-3", "TOP INTERFACE TRAFFIC", "rx / tx kbps · latest snapshot",
        Charts.bars({
          labels: traffic.map((t) => t.name.replace(/^GigabitEthernet/, "Gi")),
          series: [
            { name: "RX", color: "var(--teal)", vals: traffic.map((t) => t.rx) },
            { name: "TX", color: "var(--blue)", vals: traffic.map((t) => t.tx) },
          ], h: 196, unit: "k",
        }));

      const eCard = chartCard("alert-triangle", "INTERFACE ERRORS", "in + out + crc + flaps · per snapshot",
        Charts.bars({ labels: s.errors?.x || [], series: [
          { name: "ERRORS", color: "var(--red)", vals: errs },
        ], h: 196 }));

      const hCard = chartCard("activity", "EVENT ACTIVITY", "events_log · 24h window",
        Charts.heat({ cells: d.hourly, h: 196, label: "HOUR OF DAY" }));

      /* ---------- live telemetry card ---------- */
      const teleBadge = el("span", { class: "live-badge hist", id: "tele-badge", text: "HISTORY" });
      const teleList = el("div", { class: "tele-list", id: "tele-list" });
      const teleChips = el("div", { class: "tele-chips", id: "tele-chips" });
      const teleEmpty = el("div", { class: "tele-empty", id: "tele-empty", hidden: true, text: "NO TELEMETRY RECORDED — history will appear after the first pull" });
      const teleBody = el("div", { class: "card-body chart-body" }, [teleEmpty, teleList, teleChips]);
      const teleCard = el("div", { class: "card chart-card" }, [
        el("div", { class: "card-head" }, [
          el("span", { class: "icon-tile" }, [ic("radio", 14, "var(--teal)")]),
          el("span", { class: "t", text: "FABRIC TELEMETRY" }),
          teleBadge,
          el("button", { class: "btn iconbtn tele-refresh", id: "tele-refresh", title: "pull live telemetry", onclick: () => loadTele(true) }, [ic("refresh-cw", 14)]),
        ]),
        teleBody,
      ]);
      const teleRow = (entry) => {
        const ok = entry.status === "up";
        return el("div", { class: "tele-row" }, [
          el("span", { class: `tdot ${ok ? "on" : "off"}` }),
          el("span", { class: "tname mono", text: entry.name }),
          el("span", { class: "tip", text: entry.ip || entry.speed || "—" }),
          el("span", { class: `tstate ${ok ? "ok" : "bad"}`, text: String(entry.status || "?").toUpperCase() }),
        ]);
      };
      const renderTele = (entries) => {
        teleList.innerHTML = "";
        if (entries && entries.length) {
          entries.forEach((e) => teleList.append(teleRow(e)));
          teleEmpty.hidden = true;
        } else {
          teleEmpty.hidden = false;
        }
      };
      const renderChips = (count, ospf, bgp) => {
        teleChips.innerHTML = "";
        teleChips.append(
          el("span", { class: "chip", text: `${count} IFACES` }),
          el("span", { class: "chip", text: ospf == null || ospf.state == null ? "OSPF —" : `OSPF ${String(ospf.state_label || ospf.state).replace("//", "·")} · ${ospf.count ?? "?"} PROC` }),
          el("span", { class: "chip", text: bgp == null || bgp.count == null ? "BGP —" : `BGP ${bgp.count ?? "?"} VRFS` }),
        );
      };
      async function loadTele(force) {
        const t = await API.telemetry("interfaces").catch(() => ({}));
        const entries = t.entries || [];
        renderTele(entries);
        teleBadge.textContent = "HISTORY";
        teleBadge.className = "live-badge hist";
        renderChips(t.count ?? entries.length, null, null);
        if (isLive) {
          /* background live attempt — swap in fresh data when it arrives */
          const r = await collectAndWait("interfaces").catch(() => null);
          const t2 = await API.telemetry("interfaces").catch(() => ({}));
          if (t2.entries && t2.entries.length) {
            renderTele(t2.entries);
            teleBadge.textContent = "LIVE";
            teleBadge.className = "live-badge live";
            const [o, b] = await Promise.all([
              API.telemetry("ospf").catch(() => ({})),
              API.telemetry("bgp").catch(() => ({})),
            ]);
            renderChips(t2.count ?? t2.entries.length, o.entries ? null : o, b.entries ? null : b);
            Console.write("live telemetry pulled — " + (t2.entries.length || 0) + " interfaces", "ok");
            if (force) toast("live telemetry pulled", "ok");
          } else if (force) {
            toast(r && r.ok ? "pull queued — showing history" : "live pull failed — showing history", r && r.ok ? "ok" : "bad");
          }
        } else if (force) {
          toast("demo feed refreshed", "ok");
        }
      }
      loadTele(false);

      /* ---------- event stream card ---------- */
      const evRow = (e) => {
        const lvl = String(e.level || "INFO").toUpperCase();
        const cls = (lvl === "OK" || lvl === "SYS") ? "ok" : (lvl === "WARN") ? "warn" : (lvl === "FAIL" || lvl === "ERR") ? "fail" : "info";
        return el("div", { class: "ev-row" }, [
          el("span", { class: `ev-dot ${cls}` }),
          el("span", { class: "ev-src mono", text: e.source || "?" }),
          el("span", { class: "ev-msg", text: e.msg || "" }),
          el("span", { class: "ev-ts mono", text: (e.ts || "").slice(11, 19) }),
        ]);
      };
      const evFeed = el("div", { class: "ev-feed", id: "ev-feed" }, (d.events || []).map(evRow));
      if (!(d.events || []).length) evFeed.append(el("div", { class: "chart-empty", text: "NO EVENTS YET — activity will stream here" }));
      const evCard = chartCard("notebook-text", "EVENT STREAM", "events_log · tail", evFeed);

      /* ---------- hero ---------- */
      const lastSnap = stats.last_snapshot ? stats.last_snapshot.slice(5, 16) : "—";
      const hostname = st.creds?.host || "no-host";
      const hero = el("div", { class: "hero" }, [
        el("div", { class: "glyph" }, [ic("activity", 34, "var(--teal)")]),
        el("div", {}, [
          el("h2", { text: `MISSION CONTROL // ${(st.profile?.full_name || "OPERATOR").toUpperCase()}` }),
          el("p", { text: `LIVE FABRIC // ${hostname} // ${API.mode.toUpperCase()} BRIDGE` }),
        ]),
        el("div", { class: "hero-chips" }, [
          tag(`UPTIME ${stats.uptime_days ?? 0}d`),
          tag(`LAST SNAPSHOT ${lastSnap}`),
          tag(isLive ? "LIVE SAMPLE" : (isDemo ? "DEMO FEED" : "OFFLINE HISTORY")),
        ]),
        el("span", { class: "spacer" }),
        statusTag("online"),
      ]);

      host.append(
        el("div", { class: "section-title" }, [
          el("span", { class: "no", text: "00" }), el("span", { class: "t", text: "DASHBOARD OVERVIEW" }),
          el("span", { class: "s", text: new Date().toLocaleTimeString() }),
        ]),
        hero,
        kpis,
        el("div", { class: "section-title", style: "margin-top:18px" }, [
          el("span", { class: "no", text: "00" }), el("span", { class: "t", text: "TELEMETRY GRAPHICS" }),
          el("span", { class: "s", text: "recorded sql history · live sample when reachable" }),
        ]),
        areaCard,
        el("div", { class: "dash-b" }, [tCard, eCard, hCard]),
        el("div", { class: "dash-c" }, [teleCard, evCard]),
        el("div", { class: "section-title", style: "margin-top:18px" }, [
          el("span", { class: "no", text: "01" }), el("span", { class: "t", text: "QUICK ACTIONS" }),
        ]),
        (() => {
          const driftBox = el("div");
          const runDrift = async () => {
            driftBox.innerHTML = "";
            driftBox.append(el("div", { class: "drift-wait", text: "DRIFT CHECK RUNNING — pulls a fresh running-config from the device and diffs it against the baseline · allow 10-20s …" }));
            const r = await API.drift().catch(() => null);
            driftBox.innerHTML = "";
            if (!r || r.ok === false) {
              driftBox.append(el("div", { class: "drift-err", style: "margin-top:10px", text: "drift check failed — " + ((r && r.error) || "fabric unreachable (see console)") }));
              Console.write("drift failed: " + ((r && r.error) || "no response"), "fail");
              toast("drift check failed", "bad");
              return;
            }
            driftBox.append(driftPanel(r));
            const clean = r.status === "CLEAN";
            Console.write(`drift: ${r.status} (${r.count} items)`, clean ? "ok" : "warn");
            toast(clean ? "no drift — clean" : `drift: ${r.count} item${r.count === 1 ? "" : "s"}`, clean ? "ok" : "warn");
          };
          const captureBaseline = async () => {
            Console.write("set_baseline() …", "info");
            const r = await API.setBaseline().catch(() => null);
            if (r && r.ok) { toast("baseline captured — current config is now the reference", "ok"); runDrift(); }
            else toast("baseline failed — " + ((r && r.error) || "fabric unreachable"), "bad");
          };
          return [actionRow({ runDrift, captureBaseline }), driftBox];
        })(),
        el("div", { class: "section-title", style: "margin-top:18px" }, [
          el("span", { class: "no", text: "02" }), el("span", { class: "t", text: "WORKFLOWS" }),
        ]),
        el("div", { class: "grid2" }, [
          wf("01", "store", "PROVISION BRANCH", "Full branch bring-up: department vlan, subinterface, trunk port, gateway.", "DEPLOY →", "var(--green)", () => App.nav("provision")),
          wf("02", "network", "TOPOLOGY RADAR", "Live fabric map — inspect branch health, link state, surface downtimes.", "MAP →", "var(--blue)", () => App.nav("topology")),
          wf("03", "shield-half", "COMPLIANCE SCAN", "Baseline-vs-running drift plus policy verification across the fabric.", "SCAN →", "var(--yellow)", () => App.nav("analytics")),
          wf("04", "notebook-text", "OPERATION AUDIT", "Every write op, auth event and state mutation, append-only immutable.", "AUDIT →", "var(--green)", () => App.nav("audit")),
        ]),
      );
    } catch (e) {
      host.append(el("div", { class: "auth-error", text: "home failed: " + e.message }));
    }
  }

  function actionRow(handlers = {}) {
    const B = (label, icon, color, run) => el("button", { class: `btn ${color}`, onclick: run }, [ic(icon, 15), label.toUpperCase()]);
    return el("div", { class: "action-bar" }, [
      B("RESYNC", "refresh-cw", "teal", async () => {
        Console.write("resync — collecting fresh fabric state…", "sys");
        const r = await collectAndWait("interfaces").catch(() => null);
        toast(r?.ok ? "fabric resynced — telemetry cache refreshed" : "resync failed — check fabric access", r?.ok ? "ok" : "bad");
      }),
      B("SNAPSHOT", "camera", "blue", async () => {
        Console.write("snapshot() …", "info");
        const r = await API.snapshot().catch(() => null);
        toast(r?.ok ? "snapshot queued — completes in the background" : "snapshot failed — fabric unreachable", r?.ok ? "ok" : "bad");
      }),
      B("DRIFT CHECK", "diff", "yellow", handlers.runDrift || (async () => toast("drift unavailable", "warn"))),
      B("BASELINE", "bookmark", "green", handlers.captureBaseline || (async () => toast("baseline unavailable", "warn"))),
      B("COMPLIANCE", "scan-line", "teal", async () => {
        Console.write("compliance() …", "info");
        const r = await API.compliance().catch(() => null);
        Console.write(r ? `compliance ${r.score}%` : "scan failed", r && r.score >= 90 ? "ok" : r ? "warn" : "fail");
        toast(r ? `last audit score ${r.score}%` : "no audit report yet", r ? "ok" : "bad");
      }),
    ]);
  }

  function driftPanel(r) {
    const clean = r.status === "CLEAN";
    return el("div", { class: "drift-panel" + (clean ? " clean" : " dirty"), style: "margin-top:10px" }, [
      el("div", { class: "drift-head" }, [
        el("span", { class: "drift-status", text: clean
          ? "NO DRIFT — LIVE CONFIG MATCHES BASELINE"
          : `DRIFT DETECTED — ${r.count} ITEM${r.count === 1 ? "" : "S"}` }),
        el("span", { class: "spacer" }),
        el("span", { class: "drift-ts", text: String(r.ts || "").slice(5, 16) }),
      ]),
      clean
        ? el("div", { class: "drift-msg", text: "the device running-config is identical to the stored baseline — nothing to do." })
        : (r.baseline_exists === false
          ? el("div", { class: "drift-msg", text: "no baseline exists yet — press CAPTURE BASELINE (or the BASELINE button), then re-run DRIFT CHECK to see changes." })
          : el("pre", { class: "drift-diff", text: r.diff || "—" })),
    ]);
  }

  function wf(no, icon, title, desc, cta, accent, fn) {
    return el("div", { class: "card workflow", style: `--accent:${accent}`, onclick: fn }, [
      el("div", { class: "wf-top" }, [
        el("span", { class: "wf-no", text: no }),
        el("span", { class: "wf-glyph" }, [ic(icon, 22, accent)]),
      ]),
      el("h3", { text: title }),
      el("p", { text: desc }),
      el("div", { class: "wf-cta", text: cta }),
    ]);
  }

  /* ============================================================ PROVISION */
  async function provision(host) {
    const form = {
      action: "add_branch",
      site_name: "", department_vlan: "", vlan_id: "", vlan_name: "",
      department_subnet: "", gateway: "", router_wan_ip: "", router_trunk_port: "",
      port: "", pc_ip: "",
    };
    try { Object.assign(form, await API.pickup()); } catch (e) { /* mock may lack */ }

    let vlanScan = null;      /* {used:[], names:{}, used_names:[{name,vlan}], suggestion, via, count} */
    let plan = null;          /* {branches:[{vlan,site,subnet,gateway}], wan_ip, ifaces} */
    let vlanWarn = false;     /* live: typed vlan is already taken on the fabric */
    let vlanNameWarn = false; /* live: typed vlan name is already used on the fabric */
    let vlanNameAuto = true;  /* vlan_name follows site_name until the operator edits it */
    let planSel = "auto";     /* ip-plan selector: auto | br:<i> | custom */
    let delIdx = -1;          /* delete-mode: index of the branch picked for teardown */
    let mode = null;          /* null = action landing | add_branch | delete_branch | add_pc */
    let hostReg = null;       /* {hosts:[{label,vlan_id,ip,port,gateway,subnet,...}]} registry */
    let ifaces = null;        /* telemetry interfaces (for access-port suggestion) */
    let pcSeg = "auto";       /* add_pc segment selector: auto | br:<i> */
    let pcDraft = null;       /* last auto-draft {label,vlan,subnet,gateway,ip,port} */
    let pcType = "pc";        /* add_pc node type: pc | laptop | server | printer | phone */

    const HOST_TYPES = [
      { v: "pc", label: "PC", icon: "pc-case" },
      { v: "laptop", label: "LAPTOP", icon: "laptop" },
      { v: "server", label: "SERVER", icon: "server" },
      { v: "printer", label: "PRINTER", icon: "printer" },
      { v: "phone", label: "PHONE", icon: "smartphone" },
    ];
    const HOST_TYPE_ICONS = Object.fromEntries(HOST_TYPES.map((t) => [t.v, t.icon]));

    const stepsMeta = [
      ["01", "BLUEPRINT", "deployment archetype + site identity"],
      ["02", "NETWORK SEGMENT", "department vlan + ip plan"],
      ["03", "SERVICE PLAN", "router / trunk / host targets"],
    ];
    const PC_STEPS = [
      ["01", "SEGMENT CONTEXT", "vlan + ip plan the host joins"],
      ["02", "HOST NODE", "ip lease + access port"],
    ];
    let step = 0;

    const stepsBox = el("div", { class: "row", style: "gap:12px;margin-bottom:14px" });
    const modeBar = el("div", { class: "row", style: "gap:10px;margin-bottom:14px", hidden: true }, [
      el("button", { class: "btn ghost gray", onclick: () => enterMode(null) }, [ic("arrow-left", 14), "ACTIONS"]),
      el("span", { class: "muted mono small", id: "mode-label", text: "" }),
      el("span", { class: "spacer" }),
    ]);
    const body = el("div", { class: "card", style: "padding:0" });

    function setStep(i) {
      const max = mode === "add_pc" ? 1 : 2;
      step = Math.max(0, Math.min(max, i));
      render();
    }

    /* ---- fabric-scan driven smarts -------------------------------- */
    function vlanState() {
      const v = String(form.vlan_id || "").trim();
      if (!vlanScan || form.action === "delete_branch") return "";
      const n = Number(v);
      if (!v || !Number.isInteger(n) || n < 2 || n > 4094) return "";
      if (vlanScan.used.includes(n)) {
        const owner = vlanScan.names[String(n)] || "";
        return `VLAN ${n} already in use${owner ? " — " + owner : ""}; pick a free ID`;
      }
      return "";
    }
    function vlanHint() {
      if (!vlanScan) return "scanning fabric…”";
      const w = vlanState();
      if (w) return w;
      return `SCAN // ${vlanScan.count} taken · next free ${vlanScan.suggestion}`;
    }
    function vlanNameState() {
      const v = String(form.vlan_name || "").trim().toLowerCase();
      if (!vlanScan || form.action === "delete_branch" || !v) return "";
      const hit = (vlanScan.used_names || []).find((n) =>
        String(n.name || "").toLowerCase() === v);
      if (hit) {
        return `VLAN name "${form.vlan_name}" already in use — ${hit.name} (VLAN ${hit.vlan}); pick another`;
      }
      return "";
    }
    function vlanNameHint() {
      if (!vlanScan) return "scanning fabric…”";
      const w = vlanNameState();
      if (w) return w;
      return `NAME CHECK // ${vlanScan.used_names.length} used names on fabric`;
    }
    function deriveVlanName(site) {
      return String(site || "").toLowerCase()
        .replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 32);
    }
    function hostsOf(subnet) {
      const m = /^\d{1,3}(\.\d{1,3}){3}\/(\d{1,2})$/.exec(String(subnet || "").trim());
      if (!m) return "—";
      const p = Number(m[2]);
      if (p >= 32) return "1";
      if (p === 31) return "2";
      return 2 ** (32 - p) - 2;
    }
    function planCell(cap, val, cls = "") {
      const v = String(val == null ? "" : val);
      return el("div", { class: "plan-cell" }, [
        el("div", { class: "cap", text: cap }),
        el("div", { class: "val" + (cls ? " " + cls : ""), title: v, text: v || "—" }),
      ]);
    }
    const kv = (k, v) => el("div", { class: "row", style: "justify-content:space-between;border-bottom:1px solid var(--line);padding:6px 0" }, [
      el("span", { class: "muted mono small", text: k }), el("span", { class: "mono", text: String(v) }),
    ]);
    function syncStrip() {
      if (!body.isConnected) return;
      const strip = body.querySelector("#plan-strip");
      if (!strip) return;
      const cell = (cap) => [...strip.querySelectorAll(".plan-cell")]
        .find((c) => c.querySelector(".cap").textContent === cap);
      const set = (cap, val, cls = "") => {
        const c = cell(cap);
        if (!c) return;
        const v = c.querySelector(".val");
        const s = String(val == null ? "" : val);
        v.textContent = s || "—";
        v.className = "val" + (cls ? " " + cls : "");
        v.title = s;
      };
      set("VLAN", form.vlan_id, vlanWarn ? "bad" : (form.vlan_id ? "ok" : ""));
      set("SUBNET", form.department_subnet);
      set("GATEWAY", form.gateway);
      set("HOSTS", hostsOf(form.department_subnet));
    }
    function autoPlan() {
      const used = new Set();
      (plan ? plan.branches : []).forEach((b) => {
        const m = /^10\.1\.(\d+)\.0\/24$/.exec(b.subnet || "");
        if (m) used.add(Number(m[1]));
      });
      let oct = 150;
      while (used.has(oct)) oct++;
      return { subnet: `10.1.${oct}.0/24`, gateway: `10.1.${oct}.1` };
    }
    function loadScans() {
      Promise.all([
        API.scanVlans().catch(() => null),
        API.provisionPlan().catch(() => null),
        API.hostRegistry().catch(() => null),
        API.telemetry("interfaces").catch(() => null),
      ]).then(([vs, pl, hr, tlf]) => {
        if (vs && vs.ok) {
          vlanScan = vs;
          if (!form.vlan_id) form.vlan_id = String(vs.suggestion);
          if (!form.vlan_name && form.site_name) {
            const d = deriveVlanName(form.site_name);
            if (d) form.vlan_name = d;
          }
        }
        if (pl && pl.ok) {
          plan = pl;
          if (!form.department_subnet) {
            const a = autoPlan();
            form.department_subnet = a.subnet;
            form.gateway = a.gateway;
          }
          if (!form.router_wan_ip && pl.wan_ip) form.router_wan_ip = pl.wan_ip.split("/")[0];
        }
        if (hr && hr.ok) hostReg = hr;
        if (tlf) ifaces = tlf;
        if (!form.pc_ip && form.gateway) form.pc_ip = nextIp(form.gateway);
        if (mode === "add_pc") {
          applyPcDraft();
          render();
          return;
        }
        syncLive();
        if (mode === null) renderActions();
      });
    }
    /* pull live telemetry, bust the plan/scan caches and re-render —
       called after a successful deploy/teardown so the branch menu and
       vlan hints reflect the change without an app restart */
    async function refreshFabric() {
      try { await collectAndWait("interfaces"); } catch (e) { /* best effort */ }
      const [pl, vs, hr] = await Promise.all([
        API.provisionPlan(true).catch(() => null),
        API.scanVlans(true).catch(() => null),
        API.hostRegistry().catch(() => null),
      ]);
      let changed = false;
      if (pl && pl.ok) { plan = pl; changed = true; }
      if (vs && vs.ok) { vlanScan = vs; changed = true; }
      if (hr && hr.ok) { hostReg = hr; changed = true; }
      if (!changed) return;
      if (form.action === "delete_branch") {
        delIdx = -1;
        render();
      } else if (mode === "add_pc") {
        applyPcDraft();
        render();
      } else {
        if (!form.vlan_id && vlanScan && vlanScan.suggestion) form.vlan_id = String(vlanScan.suggestion);
        syncLive();
      }
    }
    function nextIp(ip) {
      const p = String(ip || "").trim().split(".");
      if (p.length !== 4) return ip;
      return `${p[0]}.${p[1]}.${p[2]}.${Number(p[3]) + 1}`;
    }
    /* ---- add_pc smart auto-fill (registry + fabric driven) ------------ */
    function currentPcSegment() {
      if (pcSeg.startsWith("br:")) {
        const b = (plan ? plan.branches : [])[Number(pcSeg.slice(3))];
        if (b) return { vlan: String(b.vlan), subnet: b.subnet, gateway: b.gateway };
        pcSeg = "auto";
      }
      const a = autoPlan();
      return {
        vlan: vlanScan && vlanScan.suggestion ? String(vlanScan.suggestion) : "",
        subnet: a.subnet, gateway: a.gateway,
      };
    }
    function nextFreeHostIp(subnet, gateway, taken) {
      const m = /^(\d{1,3}(?:\.\d{1,3}){3})\/(\d{1,2})$/.exec(String(subnet || "").trim());
      if (!m || !gateway) return "";
      const oct = m[1].split(".").map(Number);
      const bits = Number(m[2]);
      const total = 2 ** (32 - bits);
      if (total <= 4) return "";
      const takenSet = new Set((taken || []).map(String));
      for (let last = Number(gateway.split(".")[3]) + 1; last < total - 1; last++) {
        const ip = `${oct[0]}.${oct[1]}.${oct[2]}.${last}`;
        if (!takenSet.has(ip)) return ip;
      }
      return "";
    }
    function suggestedPort() {
      const list = (ifaces && ifaces.entries) || [];
      const hit = list.find((e) => String(e.name || "").includes("GigabitEthernet")
        && !String(e.name || "").includes(".")
        && String(e.status || "").toLowerCase() !== "up");
      return hit ? hit.name : (list.find((e) => String(e.name || "").includes("GigabitEthernet") && !String(e.name || "").includes(".")) || {}).name || "Gi0/0/9";
    }
    function pcAutoDraft() {
      const seg = currentPcSegment();
      if (!seg || !seg.subnet || !seg.gateway) return null;
      const hosts = (hostReg && hostReg.hosts) || [];
      const ip = nextFreeHostIp(seg.subnet, seg.gateway, hosts.map((h) => h.ip));
      return {
        label: "PC-" + seg.vlan,
        vlan: seg.vlan, subnet: seg.subnet, gateway: seg.gateway,
        ip, port: suggestedPort(),
      };
    }
    function applyPcDraft() {
      const d = pcAutoDraft();
      if (!d) return;
      pcDraft = d;
      Object.assign(form, {
        site_name: d.label, vlan_id: d.vlan,
        department_subnet: d.subnet, gateway: d.gateway,
        pc_ip: d.ip, port: d.port,
      });
      const vn = deriveVlanName(d.label);
      if (vn) form.vlan_name = vn;
    }
    function pcIpHint() {
      const ip = String(form.pc_ip || "");
      if (!ip) return "AUTO-DRAFT suggests the next free IP from the registry";
      const hosts = (hostReg && hostReg.hosts) || [];
      const clash = hosts.find((h) => String(h.ip) === ip);
      if (clash) return `IP TAKEN — ${clash.label}; pick another or AUTO-DRAFT`;
      if (pcDraft && ip === pcDraft.ip) {
        return `NEXT FREE // ${ip} · ${hosts.length} host${hosts.length === 1 ? "" : "s"} reserved in ${pcDraft.subnet}`;
      }
      return "MANUAL // outside the auto range — AUTO-DRAFT restores the next free IP";
    }
    function pcPortHint() {
      const port = String(form.port || "");
      if (!port) return "AUTO-PICKED from live interface telemetry";
      const hosts = (hostReg && hostReg.hosts) || [];
      const clash = hosts.find((h) => String(h.port) === port && String(h.port) !== "—");
      if (clash) return `IN USE — ${clash.label}; pick another port`;
      if (pcDraft && port === pcDraft.port) return `PORT ${port} // FREE (auto-picked from telemetry)`;
      return "MANUAL PORT // outside the auto pick";
    }
    function syncPc() {
      if (!body.isConnected) return;
      body.querySelectorAll("[data-key]").forEach((inp) => {
        if (inp.value !== form[inp.dataset.key]) inp.value = form[inp.dataset.key];
      });
      const ih = body.querySelector("#pc-ip-hint");
      if (ih) {
        const clash = (hostReg && hostReg.hosts || []).some((h) => String(h.ip) === String(form.pc_ip));
        ih.textContent = pcIpHint();
        ih.className = clash ? "hint err" : "hint neutral";
      }
      const ph = body.querySelector("#pc-port-hint");
      if (ph) {
        const clash = (hostReg && hostReg.hosts || []).some((h) => String(h.port) === String(form.port) && String(h.port) !== "—");
        ph.textContent = pcPortHint();
        ph.className = clash ? "hint err" : "hint neutral";
      }
      pcType = HOST_TYPE_ICONS[String(form.node_type || "pc")] ? String(form.node_type) : "pc";
      const tr = body.querySelector("#pc-type-row");
      if (tr) tr.querySelectorAll(".chip-sel").forEach((c) => {
        const on = c.dataset.type === pcType;
        c.classList.toggle("on", on);
        const sw = c.querySelector("svg use");
        if (sw) sw.setAttribute("href", `#${HOST_TYPE_ICONS[pcType] || "pc-case"}`);
      });
      const dep = foot.querySelector("#dep-go");
      if (dep && mode === "add_pc") dep.disabled = !(form.site_name && form.pc_ip && form.vlan_id && form.gateway);
    }
    function syncLive() {
      if (!body.isConnected) return;
      const vlanIn = body.querySelector('[data-key="vlan_id"]');
      if (vlanIn && vlanIn.value !== form.vlan_id) vlanIn.value = form.vlan_id;
      const hint = body.querySelector("#vlan-hint");
      if (hint) {
        const w = vlanState();
        vlanWarn = !!w;
        hint.textContent = vlanHint();
        hint.className = w ? "hint err" : "hint neutral";
      }
      const nameIn = body.querySelector('[data-key="vlan_name"]');
      if (nameIn && nameIn.value !== form.vlan_name) nameIn.value = form.vlan_name;
      const nameHint = body.querySelector("#vlan-name-hint");
      if (nameHint) {
        const w = vlanNameState();
        vlanNameWarn = !!w;
        nameHint.textContent = vlanNameHint();
        nameHint.className = w ? "hint err" : "hint neutral";
      }
      syncStrip();
    }

    function renderSteps() {
      stepsBox.innerHTML = "";
      (mode === "add_pc" ? PC_STEPS : stepsMeta).forEach(([no, t, s], i) => {
        const on = i === step, done = i < step;
        stepsBox.append(el("div", {
          class: "card", style: `flex:1;cursor:pointer;--accent:${on ? "var(--teal)" : "var(--line2)"}`, onclick: () => setStep(i),
        }, [
          el("div", { class: "card-head" }, [
            el("span", { class: "icon-tile", style: on ? "" : "background:var(--panel)", html: done ? ic("check", 15, "var(--green)") : ic("milestone", 15, on ? "var(--teal)" : "var(--muted)") }),
            el("div", { class: "grow" }, [
              el("div", { class: "row", style: "gap:8px" }, [
                el("span", { class: "muted mono", text: `${no}` }),
                el("span", { class: "t", style: "font-family:var(--font-disp);font-weight:600;letter-spacing:.1em;font-size:12px", text: t }),
                on ? tag("LIVE") : (done ? tag("DONE", "green") : null),
              ]),
              el("div", { class: "muted small", text: s }),
            ]),
          ]),
        ]));
      });
    }

    function f(key, label, opts) {
      const isAction = Array.isArray(opts);
      return UI.field({
        key, label, value: form[key],
        options: isAction ? opts : null,
        placeholder: isAction ? "" : (opts && opts.placeholder) || "",
      });
    }

    function enterMode(m) {
      mode = m;
      form.action = m || "add_branch";
      ["site_name", "department_vlan", "vlan_id", "vlan_name",
       "department_subnet", "gateway", "router_wan_ip", "router_trunk_port",
       "port", "pc_ip"].forEach((k) => { form[k] = ""; });
      form.node_type = "pc";
      delIdx = -1;
      vlanNameAuto = true;
      pcSeg = "auto";
      pcDraft = null;
      pcType = "pc";
      step = 0;
      loadScans();
      render();
    }

    function renderActions() {
      body.innerHTML = "";
      const actions = [
        { m: "add_branch", icon: "git-merge", color: "var(--teal)", t: "ADD BRANCH", d: "bring a new branch online — vlan, subinterface, gateway and host in one blueprint", cta: "OPEN BLUEPRINT" },
        { m: "delete_branch", icon: "trash-2", color: "var(--red)", t: "DELETE BRANCH", d: "tear down an existing branch — subinterface and vlan removed from the fabric", cta: "OPEN TEARDOWN" },
        { m: "add_pc", icon: "square-user", color: "var(--green)", t: "ADD PC — HOST NODE", d: "register a host node on the fabric — ip lease and access port", cta: "OPEN HOST REGISTRY" },
      ];
      body.appendChild(el("div", {}, [
        el("div", { class: "section-title" }, [
          el("span", { class: "no", text: "P" }), el("span", { class: "t", text: "PROVISION ACTIONS" }),
          el("span", { class: "s", text: "choose the operation — the studio adapts to it" }),
        ]),
        el("div", { class: "act-grid" }, actions.map((a) =>
          el("div", { class: "card act-card", style: `--accent:${a.color}`, onclick: () => enterMode(a.m) }, [
            el("div", { class: "act-ic" }, [ic(a.icon, 24, a.color)]),
            el("div", { class: "act-t", text: a.t }),
            el("div", { class: "act-d", text: a.d }),
            el("div", { class: "act-cta" }, [el("span", { text: a.cta }), ic("arrow-right", 14)]),
          ]))),
        plan || vlanScan ? el("div", { class: "row", style: "gap:10px;margin-top:18px;flex-wrap:wrap" }, [
          plan ? el("span", { class: "chip", text: `${plan.branches.length} BRANCH SEGMENTS` }) : null,
          plan && plan.wan_ip ? el("span", { class: "chip", text: `WAN ${plan.wan_ip}` }) : null,
          vlanScan ? el("span", { class: "chip", text: `${vlanScan.count} VLANS TAKEN` }) : null,
          vlanScan ? el("span", { class: "chip", text: `NEXT FREE ${vlanScan.suggestion}` }) : null,
        ]) : null,
      ]));
    }

    function renderBody() {
      body.innerHTML = "";
      const wrap = el("div", { class: "stagger" });

      /* ACTION LANDING — pick what to operate */
      if (mode === null) { renderActions(); return; }

      /* DELETE MODE — branch picker only, no wizard */
      if (mode === "delete_branch") {
        const branches = (plan ? plan.branches : []).filter((b) => b.subnet && b.site);
        if (delIdx >= branches.length) delIdx = -1;
        const sel = el("select", {
          id: "del-branch", class: "sel", style: "max-width:none;border-color:rgba(239,68,68,.4)",
          disabled: !branches.length,
        }, [
          el("option", { value: "", text: branches.length ? "SELECT BRANCH TO TEARDOWN …" : "NO BRANCHES ON FABRIC" }),
          ...branches.map((b, i) => el("option", {
            value: String(i),
            text: `VLAN ${b.vlan} // ${b.site} · ${b.subnet} · gw ${b.gateway}`,
          })),
        ]);
        if (delIdx >= 0) sel.value = String(delIdx);
        const detail = el("div", { class: "card", style: "padding:6px 0" });
        const renderDetail = (b) => {
          detail.innerHTML = "";
          if (!b) {
            detail.append(
              el("div", { class: "card-head" }, [
                el("span", { class: "icon-tile" }, [ic("building", 16, "var(--teal)")]),
                el("span", { class: "t", text: "BRANCH PROFILE" }),
                el("span", { class: "spacer" }),
                el("span", { class: "muted mono small", text: "READ-ONLY" }),
              ]),
              el("div", { class: "card-body", style: "display:grid;gap:6px" }, [
                kv("SEGMENTS ON FABRIC", String((plan ? plan.branches : []).length)),
                kv("WAN UPLINK", plan && plan.wan_ip ? plan.wan_ip : "—"),
                kv("INTERFACES", String(plan && plan.ifaces ? plan.ifaces.length : 0)),
                el("div", { class: "hint neutral", style: "margin-top:8px", text: "pick a branch on the left — its full profile is reviewed here before teardown" }),
              ]),
            );
            return;
          }
          detail.append(
            el("div", { class: "card-head" }, [
              el("span", { class: "icon-tile", style: "background:rgba(239,68,68,.12)" }, [ic("trash-2", 16, "var(--red)")]),
              el("span", { class: "t", text: "TEARDOWN TARGET" }),
              el("span", { class: "spacer" }),
              tag("IRREVERSIBLE", "red"),
            ]),
            el("div", { class: "card-body", style: "display:grid;gap:6px" }, [
              kv("SITE", b.site),
              kv("VLAN ID", String(b.vlan)),
              kv("VLAN NAME", deriveVlanName(b.site)),
              kv("SUBNET", b.subnet),
              kv("GATEWAY", b.gateway),
              el("div", { class: "hint err", style: "margin-top:8px", text: `Teardown removes the branch gateway subinterface and VLAN ${b.vlan} from the fabric. This cannot be undone.` }),
            ]),
          );
        };
        renderDetail(delIdx >= 0 ? branches[delIdx] : null);
        sel.addEventListener("change", () => {
          delIdx = Number(sel.value);
          const b = branches[delIdx];
          if (!b) { delIdx = -1; return; }
          form.site_name = b.site;
          form.vlan_id = String(b.vlan);
          form.vlan_name = deriveVlanName(b.site);
          form.department_subnet = b.subnet;
          form.gateway = b.gateway;
          renderDetail(b);
          render();
        });
        body.appendChild(el("div", {}, [
          el("div", { class: "section-title", style: "margin-bottom:12px" }, [
            el("span", { class: "no", text: "S1" }), el("span", { class: "t", text: "TEARDOWN SELECTOR" }),
            el("span", { class: "s", text: "pick an existing branch — its gateway + vlan are removed from the fabric" }),
          ]),
          el("div", { class: "grid2" }, [
            el("div", { class: "card", style: "padding:6px 0" }, [
              el("div", { class: "card-head" }, [
                el("span", { class: "icon-tile", style: "background:rgba(239,68,68,.12)" }, [ic("list-x", 16, "var(--red)")]),
                el("span", { class: "t", text: "BRANCHES ON FABRIC" }),
                el("span", { class: "spacer" }),
                plan ? el("span", { class: "muted mono small", text: `${branches.length} SEGMENTS` }) : null,
              ]),
              el("div", { class: "card-body" }, [sel]),
            ]),
            detail,
          ]),
          el("div", { class: "row", style: "gap:10px;margin-top:14px" }, [
            el("button", { class: "btn ghost gray", onclick: () => enterMode(null) }, [ic("arrow-left", 15), "BACK TO ACTIONS"]),
          ]),
        ]));
        return;
      }

      /* ADD PC — HOST NODE REGISTRY (2-step guided flow with smart auto-fill) */
      if (mode === "add_pc") {
        const hosts = (hostReg && hostReg.hosts) || [];
        const branches = (plan ? plan.branches : []).filter((b) => b.subnet && b.gateway);
        const draft = pcDraft;
        const seg = currentPcSegment();

        /* step 0 — segment context: pick the segment + review the registry */
        const pcStep0 = el("div", {}, [
          el("div", { class: "section-title" }, [
            el("span", { class: "no", text: "S1" }),
            el("span", { class: "t", text: "SEGMENT CONTEXT" }),
            el("span", { class: "s", text: "the segment drives vlan, gateway and the next-free ip" }),
          ]),
          el("div", { class: "grid2" }, [
            el("div", { class: "card", style: "padding:6px 0" }, [
              el("div", { class: "card-head" }, [
                el("span", { class: "icon-tile" }, [ic("network", 16, "var(--teal)")]),
                el("span", { class: "t", text: "SEGMENT" }),
                el("span", { class: "spacer" }),
                vlanScan ? el("span", { class: "muted mono small", text: `SCAN // ${vlanScan.count} taken · next free ${vlanScan.suggestion}` }) : null,
              ]),
              el("div", { class: "card-body" }, [
                el("div", { class: "field stack" }, [
                  el("label", { text: "HOST SEGMENT" }),
                  el("select", { id: "pc-seg", class: "sel" }, (() => {
                    const opts = branches.map((b, i) => ({
                      v: "br:" + i,
                      t: `VLAN ${b.vlan} // ${b.site} · ${b.subnet} · gw ${b.gateway}`,
                    }));
                    opts.push({
                      v: "auto",
                      t: `AUTO · NEXT FREE /24 · ${seg.subnet} · gw ${seg.gateway}`,
                    });
                    return opts.map((o) => el("option", { value: o.v, text: o.t }));
                  })()),
                  el("div", { class: "hint neutral", id: "pc-seg-hint",
                    text: pcSeg === "auto"
                      ? "AUTO SEGMENT // the fabric's next free /24 — or pick an existing branch to host the PC"
                      : "EXISTING SEGMENT // host joins a live branch network" }),
                ]),
                el("div", { class: "row", style: "gap:8px;flex-wrap:wrap;margin-top:12px" }, [
                  el("span", { class: "chip", text: `VLAN ${seg.vlan || "—"}` }),
                  el("span", { class: "chip", text: seg.subnet || "—" }),
                  el("span", { class: "chip", text: `GW ${seg.gateway || "—"}` }),
                  el("span", { class: "chip", text: `${branches.length} BRANCH SEGMENTS` }),
                ]),
              ]),
            ]),
            el("div", { class: "card", style: "padding:6px 0" }, [
              el("div", { class: "card-head" }, [
                el("span", { class: "icon-tile" }, [ic("database", 16, "var(--green)")]),
                el("span", { class: "t", text: "REGISTERED HOSTS" }),
                el("span", { class: "spacer" }),
                el("span", { class: "muted mono small", text: `${hosts.length} RECORDS` }),
              ]),
              el("div", { class: "card-body" }, hosts.length
                ? el("table", { class: "tbl" }, [
                    el("thead", {}, [el("tr", {}, ["NODE", "LABEL", "VLAN", "IP", "PORT"].map((h) => el("th", { text: h })))]),
                    el("tbody", {}, hosts.slice(0, 8).map((h) => {
                      const nt = String(h.node_type || "pc").toLowerCase();
                      return el("tr", {}, [
                        el("td", { class: "row", style: "gap:6px;padding:4px 10px" }, [
                          el("span", { class: "ic-sm", html: ic(HOST_TYPE_ICONS[nt] || "pc-case", 14, "var(--teal)") }),
                          el("span", { class: "mono small", text: String(h.node_type || "pc").toUpperCase() }),
                        ]),
                        el("td", { text: h.label }),
                        el("td", { text: String(h.vlan_id) }),
                        el("td", { class: "mono", text: h.ip }),
                        el("td", { class: "mono", text: h.port || "—" }),
                      ]);
                    })),
                  ])
                : el("div", { class: "hint neutral", style: "margin-top:8px",
                    text: "registry empty — deploying a host here writes the first record" })),
            ]),
          ]),
        ]);

        /* step 1 — host node: auto-drafted, every value editable */
        const clashIp = hosts.some((h) => String(h.ip) === String(form.pc_ip));
        const clashPort = hosts.some((h) => String(h.port) === String(form.port) && String(h.port) !== "—");
        const pcStep1 = el("div", {}, [
          el("div", { class: "section-title" }, [
            el("span", { class: "no", text: "S2" }),
            el("span", { class: "t", text: "HOST NODE" }),
            el("span", { class: "s", text: "auto-drafted from the registry — adjust anything, or AUTO-DRAFT again" }),
          ]),
          el("div", { class: "grid2" }, [
            el("div", { class: "card", style: "padding:6px 0" }, [
              el("div", { class: "card-head" }, [
                el("span", { class: "icon-tile" }, [ic("square-user", 16, "var(--green)")]),
                el("span", { class: "t", text: "HOST NODE" }),
                el("span", { class: "spacer" }),
                el("button", { id: "pc-draft", class: "btn ghost green", onclick: () => { applyPcDraft(); syncPc(); } },
                  [ic("wand-2", 14), "AUTO-DRAFT"]),
              ]),
              el("div", { class: "card-body" }, [
                el("div", { class: "field" }, [
                  el("label", { text: "NODE TYPE" }),
                  el("div", { class: "row", style: "gap:8px;flex-wrap:wrap", id: "pc-type-row" },
                    HOST_TYPES.map((t) => {
                      const on = pcType === t.v;
                      return el("button", {
                        class: "chip chip-sel" + (on ? " on" : ""), "data-type": t.v,
                        onclick: () => { pcType = t.v; form.node_type = t.v; syncPc(); },
                      }, [el("span", { html: ic(t.icon, 13, on ? "var(--teal)" : "var(--muted)") }), " " + t.label]);
                    })),
                  el("div", { class: "hint neutral", id: "pc-type-hint",
                    text: "the node type drives the topology icon and the registry record" }),
                ]),
                el("div", { class: "field" }, [
                  el("label", { text: "SITE / LABEL" }),
                  el("input", { type: "text", value: form.site_name, placeholder: "e.g. PC-150", "data-key": "site_name" }),
                  el("div", { class: "hint neutral", id: "pc-label-hint",
                    text: draft ? `DRAFTED // ${draft.label} — derived from the segment` : "label the host node — e.g. PC-150" }),
                ]),
                el("div", { class: "field" }, [
                  el("label", { text: "PC IP" }),
                  el("input", { type: "text", value: form.pc_ip, placeholder: "10.1.150.10", "data-key": "pc_ip", class: clashIp ? "err" : "" }),
                  el("div", { class: clashIp ? "hint err" : "hint neutral", id: "pc-ip-hint", text: pcIpHint() }),
                ]),
                el("div", { class: "field" }, [
                  el("label", { text: "ACCESS PORT" }),
                  el("input", { type: "text", value: form.port, placeholder: "Gi0/0/9", "data-key": "port", class: clashPort ? "err" : "" }),
                  el("div", { class: clashPort ? "hint err" : "hint neutral", id: "pc-port-hint", text: pcPortHint() }),
                ]),
              ]),
            ]),
            el("div", { class: "card", style: "padding:6px 0" }, [
              el("div", { class: "card-head" }, [
                el("span", { class: "icon-tile" }, [ic("route", 16, "var(--teal)")]),
                el("span", { class: "t", text: "SEGMENT CONTEXT" }),
                el("span", { class: "spacer" }),
                el("span", { class: "muted mono small", text: "EDITABLE" }),
              ]),
              el("div", { class: "card-body" }, [
                el("div", { class: "field" }, [
                  el("label", { text: "VLAN ID" }),
                  el("input", { type: "text", value: form.vlan_id, placeholder: "2-4094", "data-key": "vlan_id" }),
                ]),
                el("div", { class: "ip-grid" }, [
                  el("div", { class: "field stack" }, [
                    el("label", { text: "SUBNET // CIDR" }),
                    el("input", { type: "text", value: form.department_subnet, placeholder: "10.1.150.0/24", "data-key": "department_subnet" }),
                  ]),
                  el("div", { class: "field stack" }, [
                    el("label", { text: "GATEWAY" }),
                    el("input", { type: "text", value: form.gateway, placeholder: "10.1.150.1", "data-key": "gateway" }),
                  ]),
                ]),
                el("div", { class: "hint neutral", style: "margin-top:10px",
                  text: "deploy registers the host in the registry AND pushes the ip-lease reservation to the router" }),
              ]),
            ]),
          ]),
        ]);

        body.appendChild(el("div", {}, [pcStep0, pcStep1][step]));
        wireInputs();
        const segEl = body.querySelector("#pc-seg");
        if (segEl) {
          segEl.value = pcSeg === "auto" ? "auto" : pcSeg;
          segEl.addEventListener("change", () => {
            pcSeg = segEl.value;
            applyPcDraft();
            syncPc();
          });
        }
        return;
      }

      /* shared input wiring — every [data-key] field writes form, with
         per-mode live hints (wizard: vlan/name checks; add_pc: ip/port checks) */
      function wireInputs() {
        body.querySelectorAll("[data-key]").forEach((inp) => {
          const k = inp.dataset.key;
          inp.addEventListener(inp.tagName === "SELECT" ? "change" : "input", (e) => {
            form[k] = e.target.value;
            if (k === "action") { render(); return; }
            if (mode === "add_pc") {
              if (k === "pc_ip" || k === "port" || k === "site_name" || k === "vlan_id" || k === "gateway") syncPc();
              return;
            }
            if (k === "site_name") {
              const dep = foot.querySelector("#dep-go");
              if (dep && form.action !== "delete_branch") dep.disabled = !e.target.value.trim();
            }
            if (k === "site_name" && (vlanNameAuto || !form.vlan_name)) {
              const d = deriveVlanName(e.target.value);
              if (d) {
                form.vlan_name = d;
                const nameIn = body.querySelector('[data-key="vlan_name"]');
                if (nameIn) nameIn.value = d;
                const nh = body.querySelector("#vlan-name-hint");
                if (nh) {
                  const w = vlanNameState();
                  nh.textContent = w || vlanNameHint();
                  nh.className = w ? "hint err" : "hint neutral";
                }
              }
            }
            if (k === "vlan_id") {
              const hint = body.querySelector("#vlan-hint");
              const w = vlanState();
              vlanWarn = !!w;
              inp.classList.toggle("err", !!w);
              if (hint) {
                hint.textContent = w || vlanHint();
                hint.className = w ? "hint err" : "hint neutral";
              }
              syncStrip();
            }
            if (k === "vlan_name") {
              vlanNameAuto = false;
              const hint = body.querySelector("#vlan-name-hint");
              const w = vlanNameState();
              vlanNameWarn = !!w;
              inp.classList.toggle("err", !!w);
              if (hint) {
                hint.textContent = w || vlanNameHint();
                hint.className = w ? "hint err" : "hint neutral";
              }
            }
            if (k === "gateway" && !form.pc_ip && step === 1) form.pc_ip = nextIp(e.target.value);
            if (k === "department_subnet" || k === "gateway") syncStrip();
          });
        });
      }

      /* STEP 0 — blueprint */
      const step0 = el("div", {}, [
        el("div", { class: "section-title" }, [el("span", { class: "no", text: "S1" }), el("span", { class: "t", text: "ARCHETYPE + IDENTITY" })]),
        el("div", { class: "grid2" }, [
          el("div", { class: "card", style: "padding:6px 0" }, [
            el("div", { class: "card-head" }, [el("span", { class: "icon-tile" }, [ic("building", 16, "var(--teal)")]), el("span", { class: "t", text: "SITE IDENTITY" })]),
            el("div", { class: "card-body" }, [
              f("site_name", "SITE NAME", { placeholder: "e.g. BR-ALGER" }),
            ]),
          ]),
          el("div", { class: "card", style: "padding:6px 0" }, [
            el("div", { class: "card-head" }, [el("span", { class: "icon-tile" }, [ic("building", 16, "var(--teal)")]), el("span", { class: "t", text: "DEPARTMENT" })]),
            el("div", { class: "card-body" }, [
              f("department_vlan", "DEPARTMENT SEGMENT", { placeholder: "e.g. finance" }),
            ]),
          ]),
        ]),
      ]);

      /* STEP 1 — network segment */
      const step1 = el("div", {}, [
        el("div", { class: "section-title" }, [el("span", { class: "no", text: "S2" }), el("span", { class: "t", text: "VLAN + IP PLAN" })]),
        el("div", { class: "grid2" }, [
          el("div", { class: "card", style: "padding:6px 0" }, [
            el("div", { class: "card-head" }, [
              el("span", { class: "icon-tile" }, [ic("layers-3", 16, "var(--teal)")]),
              el("span", { class: "t", text: "VLAN REALM" }),
              el("span", { class: "spacer" }),
              vlanScan ? el("span", { class: "muted mono small", text: `SCAN // ${vlanScan.count} taken` }) : null,
            ]),
            el("div", { class: "card-body" }, [
              el("div", { class: "field" }, [
                el("label", { text: form.action === "delete_branch" ? "VLAN ID (TARGET)" : "VLAN ID — AUTO SUGGESTED" }),
                el("input", {
                  type: "text", value: form.vlan_id, placeholder: "2-4094",
                  "data-key": "vlan_id", class: vlanWarn ? "err" : "",
                }),
                el("div", { class: "hint neutral", id: "vlan-hint", text: vlanHint() }),
              ]),
              el("div", { class: "field" }, [
                el("label", { text: "VLAN NAME — AUTO FROM SITE" }),
                el("input", {
                  type: "text", value: form.vlan_name, placeholder: "e.g. finance",
                  "data-key": "vlan_name", class: vlanNameWarn ? "err" : "",
                }),
                el("div", { class: "hint neutral", id: "vlan-name-hint", text: vlanNameHint() }),
              ]),
            ]),
          ]),
          el("div", { class: "card", style: "padding:6px 0" }, [
            el("div", { class: "card-head" }, [
              el("span", { class: "icon-tile" }, [ic("route", 16, "var(--green)")]),
              el("span", { class: "t", text: "IP PLAN" }),
              el("span", { class: "spacer" }),
              plan ? el("span", { class: "muted mono small", text: `FABRIC // ${plan.branches.length} segments` }) : null,
            ]),
            el("div", { class: "card-body" }, [
              el("div", { class: "field stack" }, [
                el("label", { text: "IP PLAN SOURCE" }),
                el("select", { id: "plan-sel" }, (() => {
                  const opts = [];
                  const branches = (plan ? plan.branches : []).filter((b) => b.subnet);
                  branches.forEach((b, i) => opts.push({
                    v: "br:" + i, t: `VLAN ${b.vlan} // ${b.site} · ${b.subnet} · gw ${b.gateway}`,
                  }));
                  const a = autoPlan();
                  opts.push({ v: "auto", t: `AUTO · NEXT FREE /24 · ${a.subnet} · gw ${a.gateway}` });
                  opts.push({ v: "custom", t: "CUSTOM …" });
                  return opts.map((o) => el("option", { value: o.v, text: o.t }));
                })()),
              ]),
              el("div", { class: "plan-strip", id: "plan-strip" }, [
                planCell("VLAN", form.vlan_id, vlanWarn ? "bad" : (form.vlan_id ? "ok" : "")),
                planCell("SUBNET", form.department_subnet),
                planCell("GATEWAY", form.gateway),
                planCell("HOSTS", hostsOf(form.department_subnet)),
              ]),
              el("div", { class: "ip-grid" }, [
                el("div", { class: "field stack" }, [
                  el("label", { text: "SUBNET // CIDR" }),
                  el("input", { type: "text", value: form.department_subnet, placeholder: "10.1.150.0/24", "data-key": "department_subnet" }),
                ]),
                el("div", { class: "field stack" }, [
                  el("label", { text: "GATEWAY" }),
                  el("input", { type: "text", value: form.gateway, placeholder: "10.1.150.1", "data-key": "gateway" }),
                ]),
              ]),
            ]),
          ]),
        ]),
      ]);

      /* STEP 2 — service plan */
      const step2 = el("div", {}, [
        el("div", { class: "section-title" }, [el("span", { class: "no", text: "S3" }), el("span", { class: "t", text: "SERVICE TARGETS" })]),
        el("div", { class: "grid2" }, [
          el("div", { class: "card", style: "padding:6px 0" }, [
            el("div", { class: "card-head" }, [el("span", { class: "icon-tile" }, [ic("router", 16, "var(--teal)")]), el("span", { class: "t", text: "ROUTER END" })]),
            el("div", { class: "card-body" }, [
              f("router_wan_ip", "WAN IP", { placeholder: "172.16.2.1" }),
              f("router_trunk_port", "TRUNK PORT", { placeholder: "Gi0/0/0" }),
            ]),
          ]),
          el("div", { class: "card", style: "padding:6px 0" }, [
            el("div", { class: "card-head" }, [el("span", { class: "icon-tile" }, [ic("square-user", 16, "var(--teal)")]), el("span", { class: "t", text: "HOST NODE" })]),
            el("div", { class: "card-body" }, [
              f("port", "ACCESS PORT", { placeholder: "Gi0/0/1" }),
              f("pc_ip", "PC IP", { placeholder: "10.1.100.10" }),
            ]),
          ]),
        ]),
      ]);

      wrap.append([step0, step1, step2][step]);
      body.appendChild(wrap);
      wireInputs();
      const planSelEl = body.querySelector("#plan-sel");
      if (planSelEl) {
        planSelEl.value = planSel === "auto" ? "auto" : planSel;
        planSelEl.addEventListener("change", () => {
          planSel = planSelEl.value;
          const a = autoPlan();
          if (planSel === "auto") {
            form.department_subnet = a.subnet;
            form.gateway = a.gateway;
          } else if (planSel.startsWith("br:")) {
            const b = (plan ? plan.branches : [])[Number(planSel.slice(3))];
            if (b) { form.department_subnet = b.subnet; form.gateway = b.gateway; }
          } else {
            form.department_subnet = form.department_subnet || a.subnet;
            form.gateway = form.gateway || a.gateway;
          }
          if (!form.pc_ip && form.gateway) form.pc_ip = nextIp(form.gateway);
          body.querySelectorAll('[data-key^="department_subnet"],[data-key="gateway"]').forEach((i) => {
            if (i.dataset.key === "department_subnet") i.value = form.department_subnet;
            if (i.dataset.key === "gateway") i.value = form.gateway;
          });
          syncStrip();
        });
      }
    }

    function confirmTeardown() {
      const busy = (btn, spinning) => btn.replaceChildren(
        el("span", { html: ic(spinning ? "loader-circle" : "trash-2", 15) }),
        el("span", { text: spinning ? " TEARDOWNING…" : " TEARDOWN" }));
      const doTeardown = async (btn) => {
        busy(btn, true);
        Console.write(`TEARDOWN] ${form.site_name} :: vlan ${form.vlan_id}`, "sys");
        const res = await API.deleteSub({ ...form }).catch(() => null);
        if (res && res.ok) {
          toast("branch teardown applied — " + (res.detail || "subinterface removed"), "sys");
          Console.write("OK] teardown committed — " + (res.detail || ""), "ok");
          m.close();
          refreshFabric();
        } else {
          const why = (res && res.detail) || "fabric rejected the delete";
          toast("teardown failed — " + why, "bad");
          Console.write("FAIL] " + why, "fail");
          busy(btn, false);
          btn.disabled = false;
        }
      };
      const goBtn = el("button", { id: "del-go", class: "btn red", disabled: true, onclick: () => doTeardown(goBtn) }, [ic("trash-2", 15), "TEARDOWN"]);
      const m = modal({
        title: "TEARDOWN // IRREVERSIBLE",
        sub: `${form.site_name || "unnamed site"} · VLAN ${form.vlan_id}`,
        body: [
          el("div", { class: "del-warn" }, [
            el("div", { class: "del-warn-ic" }, [ic("triangle-alert", 30, "var(--red)")]),
            el("div", { class: "del-warn-t", text: "THIS ACTION CANNOT BE UNDONE" }),
            el("div", { class: "del-warn-s", text: `The branch ${form.site_name} will be permanently removed — subinterface, gateway ${form.gateway || "—"} and VLAN ${form.vlan_id} are deleted from the fabric.` }),
          ]),
          el("div", { class: "grid2", style: "margin-top:12px" }, Object.entries(form).filter(([, v]) => v && v !== "action").map(([k, v]) => kv(k, v))),
          el("div", { class: "field", style: "margin-top:14px" }, [
            el("label", { text: `TYPE "DELETE" TO CONFIRM` }),
            el("input", { id: "del-confirm", type: "text", placeholder: "DELETE", oninput: (e) => { goBtn.disabled = e.target.value.trim().toUpperCase() !== "DELETE"; } }),
          ]),
        ],
        actions: el("div", { style: "text-align:right;display:flex;gap:10px;justify-content:flex-end" }, [
          el("button", { class: "btn ghost gray", onclick: () => m.close() }, "CANCEL"),
          goBtn,
        ]),
      });
    }

    function deploy(btn) {
      if (form.action === "delete_branch") return confirmTeardown();
      const pc = form.action === "add_pc";
      const meta = pc
        ? [
            ["ACTION", form.action], ["SITE", form.site_name], ["PC IP", form.pc_ip],
            ["TYPE", String(form.node_type || "pc").toUpperCase()],
            ["VLAN", form.vlan_id], ["PORT", form.port], ["GATEWAY", form.gateway],
          ]
        : [
            ["ACTION", form.action], ["SITE", form.site_name], ["VLAN", form.vlan_id],
            ["SUBNET", form.department_subnet], ["GATEWAY", form.gateway],
            ["ROUTER WAN", form.router_wan_ip], ["TRUNK", form.router_trunk_port],
          ];
      launchSequence({
        origin: btn,
        site: form.site_name || "unnamed site",
        meta,
        run: async () => {
          Console.write(`APPLY] ${form.action} :: ${form.site_name} :: vlan ${form.vlan_id}`, "sys");
          const errs = await API.validate(form).catch(() => ({}));
          if (Object.keys(errs).length) return { ok: false, detail: "validation: " + Object.values(errs)[0] };
          const res = await API.provision(form).catch(() => null);
          if (res && res.ok) {
            Console.write("OK] provision committed", "ok");
            return { ok: true };
          }
          return { ok: false, detail: (res && res.detail) || "provision rejected by fabric" };
        },
        onSuccess: () => {
          toast(pc ? "host registered — ip lease reserved + registry updated" : "change applied to fabric — refreshing plan", "sys");
          refreshFabric();
        },
        onAbort: () => {
          toast("provision rejected by fabric", "bad");
          Console.write("FAIL] provision rejected", "fail");
        },
      });
    }

    function preview() {
      const lines = Object.entries(form).filter(([, v]) => v !== "").map(([k, v]) => `${k}=${v}`);
      Console.write("PREVIEW] " + lines.join(" | "), "info");
      toast("preview staged", "ok");
    }

    function render() {
      renderSteps(); renderBody();
      const landing = mode === null;
      modeBar.hidden = landing;
      const label = mode === "add_branch" ? "ADD BRANCH // BLUEPRINT"
        : mode === "delete_branch" ? "DELETE BRANCH // TEARDOWN"
        : "ADD PC — HOST NODE // REGISTER";
      const ml = modeBar.querySelector("#mode-label");
      if (ml) ml.textContent = label;
      if (landing) { stepsBox.style.display = "none"; foot.style.display = "none"; return; }
      foot.style.display = "";
      const dep = foot.querySelector("#dep-go");
      if (!dep) return;
      const del = mode === "delete_branch";
      const wizard = mode === "add_branch";
      const pc = mode === "add_pc";
      stepsBox.style.display = wizard || pc ? "" : "none";
      foot.querySelector("#back-go").style.display = wizard || pc ? "" : "none";
      foot.querySelector("#prev-go").style.display = wizard ? "" : "none";
      dep.replaceWith(el("button", {
        id: "dep-go", class: del ? "btn red" : "btn teal",
        disabled: del ? !form.vlan_id : (pc ? !(form.site_name && form.pc_ip && form.vlan_id && form.gateway) : !form.site_name),
        onclick: (e) => deploy(e.currentTarget),
      }, del ? [ic("trash-2", 15), "TEARDOWN SELECTED"] : [ic("rocket", 15), "DEPLOY →"]));
    }

    const foot = el("div", { class: "row", style: "margin-top:16px;gap:10px" }, [
      el("button", { id: "back-go", class: "btn ghost gray", onclick: () => setStep(step - 1) }, [ic("chevron-left", 15), "BACK"]),
      el("button", { id: "prev-go", class: "btn ghost gray", onclick: preview }, [ic("eye", 15), "PREVIEW"]),
      el("button", { id: "dep-go", class: "btn teal", onclick: (e) => deploy(e.currentTarget) }, [ic("rocket", 15), "DEPLOY →"]),
    ]);

    host.append(
      el("div", { class: "stagger" }, [
        el("div", { class: "section-title" }, [
          el("span", { class: "no", text: "P" }), el("span", { class: "t", text: "PROVISION STUDIO" }),
          el("span", { class: "s", text: "blueprint → apply → apply pipeline for branch offices" }),
        ]),
        modeBar, stepsBox, body, foot,
      ]),
    );
    loadScans();
    setStep(0);
  }

  /* ============================================================ TELEMETRY */
  async function telemetry(host) {
    const KINDS = ["interfaces", "arp", "ospf", "bgp", "pkt-dist"];
    let kind = "interfaces";

    const cell = (cap, val, accent) => el("div", { class: "chart-cell", style: `--accent:${accent}` }, [
      el("div", { class: "cap", text: cap }), el("div", { class: "val", text: val }),
    ]);
    const lastSync = el("span", { class: "muted mono small", text: "LAST SYNC // —" });
    const sel = el("select", {
      class: "sel", style: "max-width:230px",
      onchange: (e) => { kind = e.target.value; load(); },
    }, KINDS.map((k) => el("option", { value: k, text: k.toUpperCase() })));
    const btn = el("button", { class: "btn teal", onclick: collect }, [ic("refresh-cw", 15), "COLLECT NOW"]);
    const bar = el("div", { class: "action-bar", style: "margin-bottom:14px" }, [
      sel, btn, el("span", { class: "spacer" }), lastSync,
    ]);
    const body = el("div");

    /* ---- pkt-dist state + helpers ---- */
    let pktSel = -1; /* -1 = ALL INTERFACES */
    const PKT_COLORS = ["#06b6d4", "#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#a855f7", "#64748b"];
    const MIX_COLORS = ["#06b6d4", "#10b981", "#f59e0b", "#ef4444"];
    const pktFmt = (n) => n >= 1e12 ? (n / 1e12).toFixed(1) + "T"
      : n >= 1e9 ? (n / 1e9).toFixed(1) + "G"
      : n >= 1e6 ? (n / 1e6).toFixed(1) + "M"
      : n >= 1e3 ? (n / 1e3).toFixed(1) + "K"
      : String(n);
    const slicesOf = (arr, labels, colors) => labels.map((l, i) => ({ label: l, value: arr[i] || 0, color: colors[i] }));
    const vlanOf = (name) => {
      const tag = String(name || "").split(".").pop();
      return /^\d{1,4}$/.test(tag) ? tag : "—";
    };

    function render(ifaces, arp, tops) {
      const entries = Array.isArray(ifaces) ? ifaces : ((ifaces && ifaces.entries) || []);
      const up = entries.filter((i) => i.status === "up").length;
      const isIf = kind === "interfaces";
      const isPkt = kind === "pkt-dist";
      const tbl = isIf
        ? el("table", { class: "tbl" }, [
            el("thead", {}, [el("tr", {}, ["interface", "vlan", "status", "ip", "speed", "duplex"].map((h) => el("th", { text: h })))]),
            el("tbody", {}, entries.map((i) => el("tr", {}, [
              el("td", { class: "st", text: i.name }),
              el("td", { class: "vlan", text: vlanOf(i.name) }),
              el("td", {}, [statusTag(i.status === "up" ? "up" : "down")]),
              el("td", { text: i.ip || "—" }),
              el("td", { text: i.speed || "—" }),
              el("td", { text: i.duplex || "—" }),
            ]))),
          ])
        : (() => {
            const cols = entries.length ? Object.keys(entries[0]).slice(0, 6) : [];
            return el("table", { class: "tbl" }, [
              el("thead", {}, [el("tr", {}, cols.map((h) => el("th", { text: h })))]),
              el("tbody", {}, entries.slice(0, 16).map((e) => el("tr", {}, cols.map((k) =>
                el("td", { text: e[k] == null ? "—" : String(e[k]) }))))),
            ]);
          })();

      const rawPre = el("pre", { class: "json-view", text: (ifaces && ifaces.raw) ? String(ifaces.raw) : JSON.stringify(ifaces, null, 2) });

      if (isPkt) {
        const mode = (ifaces && ifaces.mode) || "buckets";
        const labels = (ifaces && ifaces.labels) || (mode === "mix" ? ["unicast", "multicast", "broadcast", "unknown"] : []);
        const delta = (ifaces && ifaces.delta) || null;
        const colors = mode === "mix" ? MIX_COLORS : PKT_COLORS;
        const distBox = el("div");
        const deltaBody = el("div", { class: "pkt-delta" });

        /* scope: -1 = all interfaces (sum of buckets) */
        const scopeRows = () => {
          if (pktSel === -1) return entries;
          return entries.filter((e) => e.name === entries[pktSel].name);
        };
        const sumArr = (rows, k) => rows.reduce((acc, e) => acc.map((v, i) => v + (e[k][i] || 0)),
          new Array(labels.length).fill(0));
        const scopeDelta = () => {
          if (!delta) return null;
          const rows = (pktSel === -1 ? Object.values(delta) : [delta[entries[pktSel].name]])
            .filter(Boolean);
          if (!rows.length) return null;
          const rx = sumArr(rows, "rx"), tx = sumArr(rows, "tx");
          const max = Math.max(...rx, ...tx, 1);
          return { rx, tx, max };
        };

        const tRxAll = entries.reduce((a, e) => a + (e.total_rx || 0), 0);
        const tTxAll = entries.reduce((a, e) => a + (e.total_tx || 0), 0);

        /* sample interval between the two stored payloads (seconds) */
        const intervalSec = (() => {
          if (!ifaces || !ifaces.ts || !ifaces.prev_ts) return null;
          const t0 = Date.parse(String(ifaces.prev_ts).replace("T", " "));
          const t1 = Date.parse(String(ifaces.ts).replace("T", " "));
          if (!t0 || !t1 || t1 <= t0) return null;
          return Math.round((t1 - t0) / 1000);
        })();
        const pktRate = (v, sec) => (sec ? pktFmt(Math.round(v / sec)) + "/s" : pktFmt(v));

        /* interpret a bucket distribution -> profile + actionable flags */
        const analyze = (arr, d) => {
          const total = arr.reduce((a, b) => a + b, 0);
          if (!total) return null;
          const small = ((arr[0] || 0) + (arr[1] || 0)) / total;
          const domIdx = arr.indexOf(Math.max(...arr));
          const domLabel = labels[domIdx] || "—";
          const flags = [];
          let profile = "BALANCED MIX", pColor = "var(--teal)",
            advice = "balanced sizes — typical fabric traffic profile.";
          if (mode === "buckets") {
            if (small > 0.5) {
              profile = "SMALL-PACKET HEAVY"; pColor = "var(--red)";
              advice = "≤127B packets dominate — classic DDoS / port-scan signature. Inspect ingress ACL + rate-limit on the peer.";
            } else if (domIdx >= 5) {
              profile = "BULK / LARGE FRAME"; pColor = "var(--blue)";
              advice = "large frames dominate — normal for backup/transfer. Verify MTU is consistent end-to-end (1500 vs jumbo).";
            } else if (small > 0.25) {
              profile = "SMALL-PKT ELEVATED"; pColor = "var(--yellow)";
              advice = "elevated small-packet share — monitor; typical of control-plane or VOIP bursts.";
            } else if (domIdx >= 3) {
              profile = "BULK DATA"; pColor = "var(--green)";
              advice = "mid-to-large frames dominate — healthy bulk traffic profile.";
            } else {
              profile = "MIXED / CONTROL"; pColor = "var(--teal)";
              advice = "balanced sizes — typical management / control-plane mix.";
            }
            if (small > 0.5) flags.push({ sev: "crit", label: "FLOOD RISK", text: `${Math.round(small * 100)}% ≤127B — ACL + rate-limit on peer port` });
            else if (small > 0.25) flags.push({ sev: "warn", label: "SMALL-PKT ELEVATED", text: `${Math.round(small * 100)}% ≤127B — watch control-plane / VOIP bursts` });
            if (domIdx === 6 && arr[6] / total > 0.3) flags.push({ sev: "info", label: "JUMBO / MTU-HEAVY", text: `${Math.round((arr[6] / total) * 100)}% at 1519+ — confirm jumbo MTU matches peers` });
          } else {
            const ucast = (arr[0] || 0) / total, mcast = (arr[1] || 0) / total,
              bcast = (arr[2] || 0) / total, unk = (arr[3] || 0) / total;
            if (bcast > 0.05) {
              profile = "BROADCAST STORM"; pColor = "var(--red)";
              advice = "broadcast share elevated — check STP loops / ARP flood sources on this segment.";
            } else if (unk > 0.05) {
              profile = "UNKNOWN-PROTO ELEVATED"; pColor = "var(--yellow)";
              advice = "unclassified ingress — inspect ACL logging / unencapsulated traffic.";
            } else if (ucast > 0.9) {
              profile = "UNICAST-CENTRIC"; pColor = "var(--green)";
              advice = "healthy unicast fabric traffic — no broadcast or unknown-proto anomalies.";
            } else if (mcast > 0.2) {
              profile = "MULTICAST-HEAVY"; pColor = "var(--yellow)";
              advice = "high multicast share — typical for streaming / routing protocols; verify IGMP/MLD snooping.";
            } else {
              profile = "MIXED FABRIC"; pColor = "var(--teal)";
              advice = "mixed packet classes — normal steady-state fabric.";
            }
            if (bcast > 0.05) flags.push({ sev: "crit", label: "BROADCAST STORM", text: `${Math.round(bcast * 100)}% broadcast — trace STP loop / ARP flood` });
            if (unk > 0.05) flags.push({ sev: "warn", label: "UNKNOWN-PROTO", text: `${Math.round(unk * 100)}% unclassified — check ACL logging` });
          }
          if (d) {
            const dTotal = d.reduce((a, b) => a + b, 0);
            if (dTotal) {
              const dIdx = d.indexOf(Math.max(...d));
              const dShare = d[dIdx] / dTotal;
              if (dShare > 0.6 && mode === "buckets" && small <= 0.5)
                flags.push({ sev: "warn", label: "GROWTH SPIKE", text: `${labels[dIdx]} = ${Math.round(dShare * 100)}% of new traffic${intervalSec ? ` · ${pktRate(d[dIdx], intervalSec)}` : ""}` });
              else if (dShare > 0.7 && mode === "buckets" && dIdx >= 5)
                flags.push({ sev: "info", label: "BULK SURGE", text: `${labels[dIdx]} fastest growing — new transfer started` });
            }
          }
          return { total, domIdx, domLabel, profile, pColor, advice, flags };
        };

        const rxAllArr = sumArr(entries, "rx");
        const rxAnAll = analyze(rxAllArr, null);
        const avgRxAll = entries.reduce((a, e) => a + (e.total_rx || 0) * (e.avg_rx || 0), 0)
          / Math.max(1, tRxAll);

        const renderPkt = () => {
          const rows = scopeRows();
          const rx = sumArr(rows, "rx"), tx = sumArr(rows, "tx");
          const tRx = rx.reduce((a, b) => a + b, 0), tTx = tx.reduce((a, b) => a + b, 0);
          const an = analyze(rx, null);
          const avgRx = rows.length && tRx
            ? Math.round(rows.reduce((a, e) => a + (e.total_rx || 0) * (e.avg_rx || 0), 0) / Math.max(1, tRx))
            : 0;
          const cap = (label, d, center, centerSub) => el("div", { class: "pkt-donut" }, [
            el("div", { class: "pkt-cap", text: label }),
            Charts.donut({
              slices: slicesOf(d, labels, colors), center, centerSub,
              hot: an ? an.domLabel : null, legendPct: true,
              emptyMsg: "NO TRAFFIC YET", emptySub: "collect again after traffic flows",
            }),
          ]);
          distBox.innerHTML = "";
          distBox.append(
            el("div", { class: "pkt-profile", style: `--pc:${an ? an.pColor : "var(--teal)"}` }, [
              el("span", { class: "pkt-profile-ic" }, [ic("activity", 16, "var(--pc)")]),
              el("span", { class: "pkt-profile-t", text: "PROFILE // " + (an ? an.profile : "—") }),
              an ? el("span", { class: "pkt-profile-d", text: `${an.domLabel} dominant · ${Math.round((rx[an.domIdx] / Math.max(1, tRx)) * 100)}%` }) : null,
              el("span", { class: "spacer" }),
              an && an.flags.length ? el("div", { class: "pkt-chips" }, an.flags.map((f) =>
                el("span", { class: `pkt-chip ${f.sev}`, title: f.text, text: f.label }))) : null,
              an ? el("div", { class: "pkt-advice", text: an.advice }) : null,
            ]),
            el("div", { class: "grid2" }, [
              cap("INGRESS // RX", rx, mode === "mix" && avgRx ? pktFmt(avgRx) + "B" : pktFmt(tRx), mode === "mix" && avgRx ? "AVG PKT SIZE" : "TOTAL RX"),
              cap("EGRESS // TX", tx, pktFmt(tTx), "TOTAL TX"),
            ]),
          );
          if (pktSel === -1 && entries.length > 1) {
            const tRows = [...entries].sort((a, b) => (b.total_rx || 0) - (a.total_rx || 0)).slice(0, 5);
            distBox.append(el("div", { class: "pkt-top" }, [
              el("div", { class: "pkt-top-h", text: "TOP INTERFACES // RX — click a row to drill in" }),
              ...tRows.map((e) => el("div", { class: "pkt-top-row", onclick: () => {
                pktSel = entries.indexOf(e);
                if (selPkt) selPkt.value = String(pktSel);
                renderPkt();
              } }, [
                el("span", { class: "pkt-top-name", text: e.name }),
                el("div", { class: "pkt-top-bar" }, [el("span", { style: `width:${Math.max(2, Math.round((e.total_rx / Math.max(1, tRxAll)) * 100))}%` })]),
                el("span", { class: "pkt-top-val", text: pktFmt(e.total_rx || 0) }),
                el("span", { class: "pkt-top-pct", text: Math.round((e.total_rx / Math.max(1, tRxAll)) * 100) + "%" }),
              ])),
            ]));
          }

          /* delta panel */
          deltaBody.innerHTML = "";
          const d = scopeDelta();
          const grow = (() => {
            if (!d) return null;
            const t = d.rx.reduce((a, b) => a + b, 0);
            if (!t) return null;
            const i = d.rx.indexOf(Math.max(...d.rx));
            return { i, share: d.rx[i] / t, val: d.rx[i] };
          })();
          if (!d) {
            deltaBody.append(el("div", { class: "muted small", text: "collect twice to see growth per bucket" }));
            return;
          }
          const tDRx = d.rx.reduce((a, b) => a + b, 0), tDTx = d.tx.reduce((a, b) => a + b, 0);
          const smallShare = tDRx ? (d.rx[0] + d.rx[1]) / tDRx : 0;
          if (mode === "buckets" && smallShare > 0.6) {
            deltaBody.append(el("div", { class: "pkt-flood" }, [
              el("div", { class: "pkt-flood-t", text: "SMALL-PACKET FLOOD SIGNATURE" }),
              el("div", { class: "pkt-flood-s", text: `64-127B = ${Math.round(smallShare * 100)}% of new ingress${intervalSec ? ` · ${pktRate(d.rx[0] + d.rx[1], intervalSec)}` : ""} — possible DDoS / misconfiguration` }),
            ]));
          }
          deltaBody.append(
            el("div", { class: "pkt-dhead" }, [
              el("span", { text: `RX +${pktFmt(tDRx)}` }),
              el("span", { class: "pkt-dhead-mid", text: grow
                ? `FASTEST GROWING ${labels[grow.i]} · ${Math.round(grow.share * 100)}%${intervalSec ? " · " + pktRate(grow.val, intervalSec) : ""}`
                : "no new ingress" }),
              el("span", { text: `TX +${pktFmt(tDTx)}` }),
            ]),
            ...labels.map((l, i) => el("div", {
              class: "pkt-drow" + (grow && i === grow.i ? " hot" : ""),
              style: `--dot:${colors[i]}`,
              title: intervalSec ? `≈ ${pktRate(d.rx[i], intervalSec)} ingress since last collect` : null,
            }, [
              el("span", { class: "pkt-dlbl", text: l }),
              el("div", { class: "pkt-dbar" }, [el("span", { class: "pkt-dbar-fill", style: `width:${Math.max(2, Math.round((d.rx[i] / d.max) * 100))}%` })]),
              el("span", { class: "pkt-dval", text: pktFmt(d.rx[i]) }),
              el("div", { class: "pkt-dbar" }, [el("span", { class: "pkt-dbar-fill", style: `width:${Math.max(2, Math.round((d.tx[i] / d.max) * 100))}%` })]),
              el("span", { class: "pkt-dval", text: pktFmt(d.tx[i]) }),
            ])),
          );
        };

        const selPkt = el("select", {
          class: "sel pkt-sel", style: "max-width:280px",
          onchange: (e) => { pktSel = e.target.value === "__all" ? -1 : Number(e.target.value); renderPkt(); },
        }, [
          el("option", { value: "__all", text: "ALL INTERFACES" }),
          ...entries.map((e, i) => el("option", { value: String(i), text: e.name })),
        ]);
        if (pktSel !== -1 && entries[pktSel]) selPkt.value = String(pktSel);

        body.innerHTML = "";
        if (!entries.length) {
          body.append(el("div", { class: "card" }, [
            el("div", { class: "card-head" }, [el("span", { class: "icon-tile" }, [ic("donut", 16, "var(--teal)")]), el("span", { class: "t", text: "PACKET SIZE DISTRIBUTION" })]),
            el("div", { class: "card-body" }, [
              el("div", { class: "muted", text: "no packet data — collect now, or the device does not serve controllers-oper / interface counters" }),
            ]),
          ]));
          body.append(rawPre);
          return;
        }

        body.append(
          el("div", { class: "grid2", style: "margin-bottom:14px" }, [
            cell("INTERFACES", String(entries.length), "var(--teal)"),
            cell("TOTAL RX", pktFmt(tRxAll), "var(--green)"),
            cell("TOTAL TX", pktFmt(tTxAll), "var(--teal)"),
            cell(mode === "mix" ? "AVG RX SIZE" : "DOMINANT BUCKET",
              mode === "mix" ? pktFmt(avgRxAll) + "B" : (rxAnAll ? rxAnAll.domLabel : "—"), "var(--yellow)"),
          ]),
          ifaces.fallback ? el("div", { class: "pkt-note" }, [
            "controllers-oper not served on this device — showing aggregate interface counters (packet mix)",
          ]) : null,
          el("div", { class: "grid-3-2" }, [
            el("div", { class: "card" }, [
              el("div", { class: "card-head" }, [
                el("span", { class: "icon-tile" }, [ic("donut", 16, "var(--teal)")]),
                el("span", { class: "t", text: "PACKET SIZE DISTRIBUTION" }),
                el("span", { class: "pkt-badge" + (mode === "mix" ? " warn" : ""), text: mode === "mix" ? "PACKET-MIX // FALLBACK" : "7-BUCKET // NATIVE" }),
                el("span", { class: "spacer" }),
                selPkt,
              ]),
              el("div", { class: "card-body" }, [distBox]),
            ]),
            el("div", { class: "col" }, [
              el("div", { class: "card" }, [
                el("div", { class: "card-head" }, [
                  el("span", { class: "icon-tile" }, [ic("trending-up", 16, "var(--amber)")]),
                  el("span", { class: "t", text: "CHANGE SINCE LAST COLLECT" }),
                  el("span", { class: "spacer" }),
                  el("span", { class: "pkt-interval", text: intervalSec ? `SAMPLE ${intervalSec}s` : "SINGLE SAMPLE" }),
                ]),
                el("div", { class: "card-body" }, [deltaBody]),
              ]),
              el("div", { class: "card" }, [
                el("div", { class: "card-head" }, [el("span", { class: "icon-tile" }, [ic("barcode", 16, "var(--teal)")]), el("span", { class: "t", text: "RAW RESTCONF PAYLOAD" })]),
                el("div", { class: "card-body" }, [rawPre]),
              ]),
            ]),
          ]),
        );
        renderPkt();
        return;
      }

      body.innerHTML = "";
      body.append(
        el("div", { class: "grid2", style: "margin-bottom:14px" }, [
          cell(kind.toUpperCase(), String(entries.length), "var(--teal)"),
          cell("UP", isIf ? String(up) : "—", "var(--green)"),
          cell("DOWN", isIf ? String(entries.length - up) : "—", "var(--red)"),
          cell("ARP ENTRIES", String(Array.isArray(arp) ? arp.length : 0), "var(--teal)"),
        ]),
        el("div", { class: "grid-3-2" }, [
            el("div", { class: "card" }, [
              el("div", { class: "card-head" }, [el("span", { class: "icon-tile" }, [ic("rows-3", 16, "var(--teal)")]), el("span", { class: "t", text: kind.toUpperCase() + " TABLE" })]),
              el("div", { class: "card-body" }, [
                (!isIf && ifaces.summary) ? el("div", { class: "tbl-note" }, ifaces.state_hint
                  ? [
                    el("div", { class: "tbl-note-t", text: String(ifaces.state_label || ifaces.summary) }),
                    el("div", { class: "tbl-note-s", text: String(ifaces.state_hint) }),
                  ]
                  : [el("div", { class: "tbl-note-t", text: String(ifaces.summary) })]) : null,
                tbl,
              ]),
            ]),
          el("div", { class: "col" }, [
            el("div", { class: "card" }, [
              el("div", { class: "card-head" }, [el("span", { class: "icon-tile" }, [ic("barcode", 16, "var(--teal)")]), el("span", { class: "t", text: "RAW RESTCONF PAYLOAD" })]),
              el("div", { class: "card-body" }, [rawPre]),
          ]),
        ]),
      ]),
    );
    }

    async function load() {
      const [ifaces, arp, tops] = await Promise.all([
        API.telemetry(kind), API.telemetry("arp"), API.topology(),
      ]);
      const ts = (ifaces && ifaces.ts) ? String(ifaces.ts).slice(0, 19).replace("T", " ") : "—";
      lastSync.textContent = "LAST SYNC // " + ts;
      render(ifaces, arp, tops);
    }

    async function collect() {
      btn.disabled = true;
      btn.replaceChildren(el("span", { html: ic("refresh-cw", 15) }), el("span", { text: " FETCHING…" }));
      const r = await collectAndWait(kind);
      if (!r || !r.ok) toast("collect failed — check fabric access", "bad");
      await load();
      btn.replaceChildren(el("span", { html: ic("refresh-cw", 15) }), el("span", { text: " COLLECT NOW" }));
      btn.disabled = false;
    }

    host.append(
      el("div", { class: "section-title" }, [
        el("span", { class: "no", text: "T" }), el("span", { class: "t", text: "TELEMETRY // LIVE FABRIC" }),
        el("span", { class: "s", text: "RESTCONF pull — pick a kind, then collect fresh data" }),
      ]),
      bar, body,
    );
    load();
  }

  /* ============================================================ MODELS (netconf) */
  async function models(host) {
    const pre = (t) => el("pre", { class: "json-view", style: "max-height:340px;overflow:auto;margin-top:8px" }, [el("code", { text: t || "—" })]);
    const status = el("div", { class: "muted small" });
    const list = el("div", { class: "nc-list", style: "max-height:340px;overflow:auto" });
    const modCount = el("span", { class: "muted mono small" });
    const selName = el("span", { class: "nc-mod", style: "font-family:var(--font-mono);font-size:11px;color:var(--teal)" });
    const selMeta = el("span", { class: "muted mono small" });
    const schemaHost = el("div");
    const filter = el("input", {
      type: "text", class: "in", style: "font-family:var(--font-mono);font-size:9.5px",
      placeholder: "<interfaces xmlns='urn:ietf:params:xml:ns:yang:ietf-interfaces'/>",
    });
    const runGet = el("button", { class: "btn teal", onclick: () => runFilter() }, [ic("play", 13), "RUN <get>"]);
    const runSearch = el("button", { class: "btn ghost teal small", onclick: () => load() }, [ic("refresh-cw", 13), "RUN"]);
    const getOut = el("div");
    let schemaMode = "PROFILE";
    let lastSchema = null;
    let getMode = "TREE";
    let lastGet = null;

    const renderSchema = () => {
      schemaHost.innerHTML = "";
      if (!lastSchema) {
        schemaHost.append(emptyBox("NO SCHEMA", "pick a module card — PROFILE shows essentials, TREE the full YANG hierarchy, RAW the source text"));
        return;
      }
      if (lastSchema.note) schemaHost.append(el("div", { class: "muted mono small", style: "margin-bottom:6px", text: lastSchema.note }));
      if (schemaMode === "RAW") {
        schemaHost.append(el("div", { class: "muted mono small", style: "margin-bottom:6px", text: `${lastSchema.len.toLocaleString()} chars` + (lastSchema.truncated ? " — truncated to 200 KB" : "") }), pre(lastSchema.text));
        return;
      }
      if (schemaMode === "PROFILE") {
        schemaHost.append(Models.yangCards(lastSchema.text).node);
        return;
      }
      const t = Models.yangTree(lastSchema.text);
      schemaHost.append(t.meta, t.node);
    };
    const schemaSeg = Models.seg(["PROFILE", "TREE", "RAW"], "PROFILE", (v) => { schemaMode = v; renderSchema(); });
    const getSeg = Models.seg(["TREE", "RAW"], "TREE", (v) => { getMode = v; renderGet(); });

    const renderGet = () => {
      getOut.innerHTML = "";
      if (!lastGet) return;
      if (getMode === "RAW") {
        getOut.append(el("div", { class: "muted mono small", style: "margin-bottom:6px", text: `reply ${lastGet.len.toLocaleString()} chars` }), pre(lastGet.xml));
        return;
      }
      const t = Models.xmlTree(lastGet.xml);
      getOut.append(t.meta, t.node);
    };

    const loadSchema = async (module) => {
      selName.textContent = module;
      selMeta.textContent = "fetching schema…";
      schemaHost.innerHTML = "";
      schemaHost.append(Models.schemaSkeleton("cycling NETCONF :830 → RESTCONF yang-library"));
      const r = await API.netconfSchema(module).catch(() => null);
      schemaHost.innerHTML = "";
      if (!r || !r.ok) {
        schemaHost.append(el("div", { class: "drift-err", text: "schema fetch failed — " + ((r && r.error) || "backend unreachable") }));
        return;
      }
      selMeta.textContent = `${r.len.toLocaleString()} chars` + (r.truncated ? " — truncated to 200 KB" : "");
      lastSchema = r;
      renderSchema();
    };

    const runFilter = async () => {
      const f = filter.value.trim();
      getOut.innerHTML = "";
      if (!f) { getOut.append(el("div", { class: "drift-err", text: "enter a subtree filter — e.g. the placeholder example" })); return; }
      runGet.disabled = true;
      runGet.replaceChildren(el("span", { class: "spinner" }), el("span", { text: " RUNNING" }));
      const r = await API.netconfGet(f).catch(() => null);
      runGet.replaceChildren(el("span", { html: ic("play", 13) }), el("span", { text: " RUN <get>" }));
      runGet.disabled = false;
      if (!r || !r.ok) {
        getOut.append(el("div", { class: "drift-err", text: "get failed — " + ((r && r.error) || "backend unreachable") }));
        return;
      }
      lastGet = r;
      getOut.append((r.note ? el("div", { class: "muted mono small", style: "margin-bottom:6px", text: r.note }) : null));
      renderGet();
    };

    const fillNs = async () => {
      const mod = selName.textContent.trim();
      if (!mod) { toast("select a module first", "warn"); return; }
      const r = await API.netconfNamespace(mod).catch(() => null);
      if (!r || !r.ok || !r.namespace) {
        toast("namespace unknown — type the full element with xmlns manually", "warn");
        return;
      }
      filter.value = `<${mod.split("-").pop()} xmlns='${r.namespace}'/>`;
      toast(`namespace filled for ${mod}`, "ok");
    };

    const load = async () => {
      runSearch.disabled = true;
      runSearch.replaceChildren(el("span", { class: "spinner" }), el("span", { text: " SCANNING" }));
      status.replaceChildren(el("span", { text: "NETCONF :830 — hello…" }));
      const r = await API.netconfModules().catch(() => null);
      runSearch.disabled = false;
      runSearch.replaceChildren(el("span", { html: ic("refresh-cw", 13) }), el("span", { text: " RUN" }));
      if (!r || !r.ok) {
        status.replaceChildren(el("span", { class: "drift-err", text: "module list failed — " + ((r && r.error) || "backend unreachable") }));
        list.innerHTML = "";
        return;
      }
      modCount.textContent = `${r.count} YANG MODULES ADVERTISED`;
      status.replaceChildren(el("span", { text: (r.note ? r.note + " — " : "") + "read-only explorer; nothing writes to the device" }));
      list.innerHTML = "";
      for (const m of r.modules) {
        list.appendChild(el("button", {
          class: "nc-mod-row",
          title: `${m.name} @ ${m.revision}`,
          onclick: () => loadSchema(m.name),
        }, [
          el("span", { class: "nc-mod-name mono", text: m.name }),
          el("span", { class: "spacer" }),
          el("span", { class: "muted mono small", text: String(m.revision || "").slice(0, 10) }),
        ]));
      }
    };

    host.append(
      el("div", { class: "section-title" }, [
        el("span", { class: "no", text: "M" }), el("span", { class: "t", text: "MODEL EXPLORER // NETCONF" }),
        el("span", { class: "s", text: "yang module browser — 830 · read-only · same vault creds" }),
      ]),
      el("div", { class: "grid2" }, [
        el("div", { class: "card" }, [
          el("div", { class: "card-head" }, [
            el("span", { class: "icon-tile" }, [ic("binary", 16, "var(--blue)")]),
            el("span", { class: "t", text: "MODULES" }), el("span", { class: "spacer" }),
            modCount, runSearch,
          ]),
          el("div", { class: "card-body" }, [status, list]),
        ]),
        el("div", { class: "card" }, [
          el("div", { class: "card-head" }, [
            el("span", { class: "icon-tile" }, [ic("file-code-2", 16, "var(--teal)")]),
            el("span", { class: "t", text: "SCHEMA" }), el("span", { class: "spacer" }),
            schemaSeg, el("span", { class: "muted mono small", style: "margin-left:10px" }), selMeta,
          ]),
          el("div", { class: "card-body" }, [selName, el("div", { style: "margin-top:8px" }), schemaHost]),
        ]),
      ]),
      el("div", { class: "section-title", style: "margin-top:18px" }, [
        el("span", { class: "no", text: "02" }), el("span", { class: "t", text: "SUBTREE <get>" }),
        el("span", { class: "s", text: "run any read-only filter against the operational datastore" }),
      ]),
      el("div", { class: "card" }, [
        el("div", { class: "card-body" }, [
          el("div", { class: "row", style: "gap:8px;flex-wrap:wrap" }, [
            filter,
            runGet,
            el("button", { class: "btn ghost teal small", onclick: fillNs }, [ic("wand-2", 13), "FILL NS"]),
            el("button", { class: "btn ghost gray small", onclick: () => { filter.value = "<interfaces xmlns='urn:ietf:params:xml:ns:yang:ietf-interfaces'/>"; runFilter(); } }, [ic("zap", 13), "PRESET IETF-IF"]),
            el("button", { class: "btn ghost gray small", onclick: () => { filter.value = "<interfaces xmlns='http://openconfig.net/yang/interfaces'/>"; runFilter(); } }, [ic("zap", 13), "PRESET OC-IF"]),
            el("button", { class: "btn ghost gray small", onclick: () => { filter.value = "<netconf-state xmlns='urn:ietf:params:xml:ns:yang:ietf-netconf-monitoring'/>"; runFilter(); } }, [ic("zap", 13), "PRESET NC-STAT"]),
            el("span", { class: "spacer" }),
            getSeg,
          ]),
          getOut,
        ]),
      ]),
    );
    load();
  }

  /* ============================================================ TOPOLOGY */
  async function topology(host) {
    const wrap = el("div", { class: "topo-wrap" });
    const canvasHost = el("div", { class: "topo-canvas-host" });
    const insp = el("div", { class: "card" }, [
      el("div", { class: "card-head" }, [
        el("span", { class: "icon-tile" }, [ic("square-terminal", 16, "var(--teal)")]),
        el("span", { class: "t", text: "NODE INSPECT" }),
      ]),
      el("div", { class: "card-body", id: "topo-inspect" }, [
        el("div", { class: "muted", text: "select a node on the map to inspect live attributes" }),
      ]),
    ]);
    wrap.append(canvasHost, el("div", { class: "col" }, [insp]));

    const lastSync = el("span", { class: "muted mono small", text: "LAST REFRESH // —" });
    const refreshBtn = el("button", { class: "btn ghost gray", onclick: refresh }, [ic("refresh-cw", 15), "REFRESH"]);
    const liveBtn = el("button", { class: "btn teal", onclick: liveFetch }, [ic("radio-tower", 15), "FETCH LIVE MAP"]);
    const rawBtn = el("button", { class: "btn ghost gray", onclick: rawFetch }, [ic("braces", 15), "RAW JSON"]);
    const bar = el("div", { class: "action-bar", style: "margin-bottom:14px" }, [
      refreshBtn, liveBtn, rawBtn, el("span", { class: "spacer" }), lastSync,
    ]);

    function inspect(n) {
      const box = document.getElementById("topo-inspect");
      box.innerHTML = "";
      const rows = el("div", { class: "stagger" });
      const meta = n.meta || {};
      const items = [
        ["host", n.hostname],
        ["role", (n.role || "core").toUpperCase()],
        ["state", n.state || (n.up ? "UP" : "DOWN")],
        ["iface", n.iface],
        ["site", n.site || (n.role === "core" ? "CORE" : "—")],
        ["ipv4", n.cidr || n.ipv4 || "—"],
        ["subnet", n.subnet || "—"],
        ["vlan", n.vlan],
        ["speed", meta.speed || "—"],
        ["duplex", meta.duplex || "—"],
        ["mtu", meta.mtu || "—"],
        ["desc", meta.desc || "—"],
      ];
      items.forEach(([k, v]) => {
        if (v == null || v === "" || v === undefined) return;
        rows.append(el("div", { class: "row", style: "justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--line)" }, [
          el("span", { class: "muted mono", text: k }),
          el("span", { class: "mono", style: (n.state === "down" ? "color:var(--red)" : n.state === "warn" ? "color:var(--yellow)" : ""),
            text: String(v) }),
        ]));
      });
      box.appendChild(rows);
    }

    async function draw() {
      await Topo.load().catch(() => {});
      const tops = await API.topology();
      canvasHost.innerHTML = "";
      Topo.bind(canvasHost, { topology: tops }, inspect);
      lastSync.textContent = "LAST REFRESH // " + new Date().toLocaleTimeString();
      renderReading(tops);
    }

    function renderReading(tops) {
      const ds = tops.devices || [];
      const kinds = {};
      ds.forEach((d) => { kinds[d.role] = (kinds[d.role] || 0) + 1; });
      const up = ds.filter((d) => (d.state || "up") === "up").length;
      const down = ds.length - up;
      const links = (tops.links || []).length;
      const wan = ds.find((d) => d.role === "wan");
      const vlanN = ds.filter((d) => d.vlan).length;
      const parts = [
        ds.length + " DEVICE" + (ds.length === 1 ? "" : "S"),
        up + " ONLINE",
        down ? down + " DOWN" : null,
        links + " FABRIC LINK" + (links === 1 ? "" : "S"),
        vlanN ? vlanN + " VLAN" + (vlanN === 1 ? "" : "S") + " NETWORK" + (vlanN === 1 ? "" : "S") : null,
        wan && wan.cidr ? "WAN → " + wan.cidr : null,
      ].filter(Boolean);
      const readingHost = document.getElementById("topo-reading");
      if (readingHost) readingHost.textContent = "TOPOLOGY READING // " + parts.join(" · ");
    }

    async function refresh() {
      refreshBtn.disabled = true;
      await draw();
      toast("map refreshed from vault cache", "ok");
      refreshBtn.disabled = false;
    }

async function liveFetch() {
      liveBtn.disabled = true;
      liveBtn.replaceChildren(el("span", { html: ic("radio-tower", 15) }), el("span", { text: " FETCHING…" }));
      const r = await collectAndWait("interfaces");
      if (!r || !r.ok) toast("telemetry collect failed — check fabric access", "bad");
      await draw();
      toast("fabric map updated", "sys");
      liveBtn.disabled = false;
      liveBtn.replaceChildren(el("span", { html: ic("radio-tower", 15) }), el("span", { text: "FETCH LIVE MAP" }));
    }

    async function rawFetch() {
      rawBtn.disabled = true;
      rawBtn.replaceChildren(el("span", { html: ic("braces", 15) }), el("span", { text: " FETCHING…" }));
      const r = await API.topologyRaw().catch(() => null);
      rawBtn.disabled = false;
      rawBtn.replaceChildren(el("span", { html: ic("braces", 15) }), el("span", { text: "RAW JSON" }));
      if (!r || !r.raw) {
        toast("no raw payload cached — run FETCH LIVE MAP first", "bad");
        return;
      }
      modal({
        title: "TOPOLOGY // RAW PAYLOAD",
        sub: (r.ts ? "captured " + r.ts : "") + " · " + r.raw.length + " chars",
        wide: true,
        body: [el("pre", { class: "json-view", text: r.raw })],
      });
    }

    host.append(
      el("div", { class: "section-title" }, [
        el("span", { class: "no", text: "∓" }), el("span", { class: "t", text: "TOPOLOGY // FABRIC RADAR" }),
        el("span", { class: "s", text: "refresh reads the cache — fetch live pulls fresh telemetry first" }),
      ]),
      el("div", { class: "topo-reading mono", id: "topo-reading", text: "TOPOLOGY READING // —" }),
      el("div", { class: "topo-legend" }, [
        el("span", { class: "lg" }, [el("i", { class: "dot up" }), "UP · operational"]),
        el("span", { class: "lg" }, [el("i", { class: "dot down" }), "DOWN · link fault"]),
        el("span", { class: "lg" }, [el("i", { class: "dot warn" }), "WARN · degraded"]),
        el("span", { class: "lg mute" }, [ic("grab", 14), "drag a device anywhere — wires re-route live"]),
      ]),
      bar, wrap,
    );
    await draw();
  }

  /* ============================================================ OPS (toolbox) */

  const opsCb = {};            // engine task id -> render(data) (live push target)
  let healthCb = null;         // ops view health renderer (registered per visit)

  /* called from app.js when the engine pushes a completed task's data payload */
  function opsResult(r) {
    if (!r || !r.id) return;
    const fn = opsCb[r.id];
    if (typeof fn === "function") { delete opsCb[r.id]; fn(r.data); }
  }

  function opsHealth(h) {
    if (typeof healthCb === "function") healthCb(h);
  }

  async function opsRun(id, fn, render) {
    let r = null;
    try { r = await fn(); }
    catch (e) {
      render(errBox("LIVE BRIDGE OFFLINE", "the desktop engine is not reachable — real data only appears inside the CAT8k-SYNC app"));
      toast("live bridge offline", "bad");
      return;
    }
    if (r && r.queued) {
      opsCb[id] = render;
      toast(`task ${id} queued — live result arriving`, "sys");
      return;
    }
    if (r && r.ok === false) {
      render(errBox("REJECTED", r.error || "the backend refused this operation"));
      return;
    }
    render(r);
  }

  function opsTable(heads, items, mk, emptyTitle, emptyMsg) {
    if (!items || !items.length) return emptyBox(emptyTitle, emptyMsg);
    return el("table", { class: "tbl" }, [
      el("thead", {}, [el("tr", {}, heads.map((h) => el("th", { text: h })))]),
      el("tbody", {}, items.map((x) => el("tr", {}, mk(x)))),
    ]);
  }

  function emptyBox(title, msg) {
    return el("div", { class: "ops-empty" }, [
      el("div", { class: "t", text: (title || "NO DATA") }),
      el("div", { class: "muted small", text: (msg || "the device returned nothing for this query") }),
    ]);
  }

  function errBox(title, msg) {
    return el("div", { class: "ops-err" }, [
      el("div", { class: "t", text: (title || "ERROR") }),
      el("div", { class: "muted small", text: (msg || "") }),
    ]);
  }

  function ackRow(title, extra) {
    return el("div", { class: "ops-ack" }, [
      el("span", {}, [statusTag("ok")]),
      el("span", { style: "font-weight:600", text: title }),
      extra ? el("span", { class: "mono muted", style: "margin-left:auto", text: extra }) : null,
    ]);
  }

  function setRes(box, node) { box.replaceChildren(node || null); }

  async function ops(host) {
    const healthDot = el("span", { class: "dot" });
    const healthTxt = el("span");
    const pill = el("span", { class: "status-pill" }, [healthDot, healthTxt]);
    const probeBtn = el("button", { class: "btn ghost teal", onclick: probe }, [ic("radio-tower", 14), "PROBE FABRIC"]);
    const healthHost = el("div", { class: "action-bar", style: "margin:14px 0;align-items:center" }, [
      pill, probeBtn,
      el("span", { class: "muted small", text: "live RESTCONF reachability — drives the fabric pill in the topbar too" }),
    ]);

    function renderHealth(h) {
      const ok = h ? h.ok : null;
      healthDot.className = "dot " + (ok === true ? "online" : ok === false ? "offline" : "");
      healthTxt.textContent = ok === true
        ? ` FABRIC // LIVE :: ${h.host || "?"} @ ${h.at || ""}`
        : ok === false ? " FABRIC // UNREACHABLE" : " FABRIC // UNKNOWN";
    }
    healthCb = renderHealth;

    async function probe() {
      probeBtn.disabled = true;
      probeBtn.replaceChildren(el("span", { html: ic("radio-tower", 14) }), el("span", { text: " PROBING…" }));
      let r = null;
      try { r = await API.checkHealth(); }
      catch (e) { r = null; }
      if (r && r.queued) {
        /* live mode: the result arrives via window.Company.onHealth */
      } else if (r && "ok" in r) {
        renderHealth(r);
        toast("fabric probe run", "sys");
      } else {
        renderHealth({ ok: false, host: "", at: null });
        toast("fabric probe failed", "bad");
      }
      probeBtn.replaceChildren(el("span", { html: ic("radio-tower", 14) }), el("span", { text: " PROBE FABRIC" }));
      probeBtn.disabled = false;
    }

    function card(iconName, title, desc, body, verb) {
      return el("div", { class: "card ops-card" }, [
        el("div", { class: "card-head" }, [
          el("span", { class: "icon-tile" }, [ic(iconName, 16, "var(--teal)")]),
          el("span", { class: "t", text: title }),
          verb ? el("span", { class: "ops-verb", text: verb }) : null,
        ]),
        el("div", { class: "card-body" }, [desc, body]),
      ]);
    }
    function busy(btn, label) {
      btn.disabled = true;
      btn.replaceChildren(el("span", { html: ic("loader-circle", 15) }), el("span", { text: label }));
    }
    function idle(btn, label, iconName) {
      btn.disabled = false;
      btn.replaceChildren(el("span", { html: ic(iconName, 15) }), el("span", { text: label }));
    }

    const cards = [];

    /* --- tool 1: hardware inventory --- */
    const invRes = el("div", { class: "ops-result" });
    invRes.appendChild(emptyBox("NO INVENTORY DATA", "PULL HARDWARE queries field-replaceable units over RESTCONF"));
    const invBtn = el("button", { class: "btn teal", onclick: async () => {
      busy(invBtn, "PULLING…");
      await opsRun("INVENTORY", () => API.inventory(), (d) => {
        setRes(invRes, opsTable(["PN", "SERIAL", "DESCRIPTION"], d,
          (x) => [el("td", { class: "st", text: x.pn }), el("td", { class: "mono", text: x.sn }), el("td", { class: "muted", text: x.desc || "—" })],
          "EMPTY INVENTORY", "the device returned zero field-replaceable units"));
      });
      idle(invBtn, "PULL HARDWARE", "package");
    } }, [ic("package", 15), "PULL HARDWARE"]);
    cards.push(card("package", "HARDWARE INVENTORY",
      el("div", { class: "muted small", text: "part numbers + serials for every field-replaceable unit on the Catalyst" }),
      el("div", {}, [invBtn, invRes]), "GET"));

    /* --- tool 2: hostname (read + write) --- */
    const hostRes = el("div", { class: "ops-result" });
    hostRes.appendChild(emptyBox("NO HOSTNAME DATA", "READ pulls the live hostname; WRITE pushes a new one"));
    const hostIn = field("hostname", "NEW HOSTNAME", null, "");
    const getH = el("button", { class: "btn ghost teal", onclick: async () => {
      busy(getH, "…");
      await opsRun("HOSTNAME", () => API.getHostname(), (n) => {
        const name = (n && n.name) || n || "";
        setRes(hostRes, el("div", { class: "ops-host" }, [
          el("span", {}, [statusTag(name ? "ok" : "offline")]),
          el("span", { class: "mono", text: name || "unreachable" }),
        ]));
      });
      idle(getH, "READ", "terminal");
    } }, [ic("terminal", 15), "READ"]);
    const setH = el("button", { class: "btn teal", onclick: async () => {
      const v = (host.querySelector(`[data-key="hostname"]`) || {}).value || "";
      if (!v.trim()) { toast("hostname required", "warn"); return; }
      busy(setH, "WRITING…");
      await opsRun("SET_HOSTNAME", () => API.setHostname(v.trim()), (r) => {
        setRes(hostRes, ackRow("hostname applied", (r && r.name) || r || v.trim()));
      });
      idle(setH, "WRITE", "save");
    } }, [ic("save", 15), "WRITE"]);
    cards.push(card("server", "HOSTNAME", "read the box hostname or write a new one (PUT Cisco-IOS-XE-native:native/hostname)",
      el("div", {}, [el("div", { class: "ops-form" }, [hostIn]), el("div", { class: "action-bar" }, [getH, setH]), hostRes]), "GET · PUT"));

    /* --- tool 3: bring interfaces up (one-click) --- */
    const ifRes = el("div", { class: "ops-result" });
    ifRes.appendChild(emptyBox("SCANNING FABRIC…", "loading the down-interface menu — one click starts a port"));
    const ifBtn = el("button", { class: "btn teal", onclick: refreshDown }, [ic("refresh-cw", 15), "REFRESH DOWN LIST"]);
    async function refreshDown() {
      ifBtn.disabled = true;
      ifBtn.replaceChildren(el("span", { html: ic("loader-circle", 15) }), el("span", { text: " SCANNING…" }));
      await opsRun("IFACE_CONFIG", () => API.ifaceConfig(), (d) => {
        const down = (Array.isArray(d) ? d : []).filter((x) => x.enabled !== "up");
        setRes(ifRes, down.length
          ? el("div", { class: "col", style: "gap:8px" }, [
              el("div", { class: "down-head" }, [
                el("span", { class: "mono small", text: down.length + (down.length > 1 ? " INTERFACES DOWN" : " INTERFACE DOWN") }),
                el("span", { class: "muted small", text: "— one click starts a port, no CLI needed" }),
              ]),
              el("div", { class: "col", style: "gap:6px" }, down.map((x) => {
                if (x.admin === "up") {
                  return el("div", { class: "iface-down-row stuck" }, [
                    el("span", { class: "mono", text: x.name }),
                    el("span", { class: "muted small", style: "overflow:hidden;text-overflow:ellipsis;white-space:nowrap", text: [x.description, x.ip && x.ip !== "0.0.0.0" ? x.ip : null].filter(Boolean).join(" · ") || "no address" }),
                    el("span", { class: "spacer" }),
                    el("span", { class: "stuck-note" }, [
                      ic("lightbulb", 13),
                      el("span", { text: x.state === "lower-layer-down"
                        ? "no L2 members on this VLAN — autostate keeps the line down; START cannot help"
                        : "line down — no peer or cable connected; START cannot help" }),
                    ]),
                    el("button", { class: "btn gray small", disabled: true }, [ic("ban", 13), "CANNOT START"]),
                  ]);
                }
                const startBtn = el("button", { class: "btn teal small", onclick: async (ev) => {
                  const btn = ev.currentTarget;
                  btn.disabled = true;
                  btn.replaceChildren(el("span", { html: ic("loader-circle", 13) }), el("span", { text: " STARTING…" }));
                  await opsRun("IFACE_STATE", () => API.setIfaceState(x.name, true), (r) => {
                    const name = (r && r.iface) || x.name;
                    if (!r || !r.ok) {
                      const why = (r && r.detail) || "line down — no peer/cable";
                      toast(name + ": " + why, "warn");
                      const row = btn.closest(".iface-down-row");
                      if (row) {
                        const hint = row.querySelector(".muted.small");
                        if (hint) hint.textContent = why;
                      }
                      return;
                    }
                    const row = btn.closest(".iface-down-row");
                    if (!row) { refreshDown(); return; }
                    toast(name + " is up", "ok");
                    const head = ifRes.querySelector(".down-head .mono");
                    if (head) {
                      const m = head.textContent.match(/(\d+)/);
                      if (m) head.textContent = head.textContent.replace(m[1], String(Math.max(0, Number(m[1]) - 1)));
                    }
                    btn.replaceChildren(el("span", { html: ic("check", 13) }), el("span", { text: " UP" }));
                    btn.classList.add("done");
                    row.insertBefore(el("span", { class: "up-badge" }, [ic("circle-check", 14), "LINK UP"]), btn);
                    row.classList.add("going-up");
                    setTimeout(() => {
                      row.classList.add("leaving");
                      setTimeout(() => { row.remove(); refreshDown(); }, 450);
                    }, 1300);
                  });
                  if (!startBtn.closest(".iface-down-row") || !startBtn.closest(".iface-down-row").classList.contains("going-up")) {
                    btn.replaceChildren(el("span", { html: ic("zap", 13) }), el("span", { text: " START" }));
                    btn.disabled = false;
                  }
                } }, [ic("zap", 13), "START"]);
                return el("div", { class: "iface-down-row" }, [
                  el("span", { class: "mono", text: x.name }),
                  el("span", { class: "muted small", style: "overflow:hidden;text-overflow:ellipsis;white-space:nowrap", text: [x.description, x.ip && x.ip !== "0.0.0.0" ? x.ip : null, (x.admin === "up" && x.state !== "ready") ? "line down — no peer/cable" : null].filter(Boolean).join(" · ") || "no address" }),
                  el("span", { class: "spacer" }),
                  startBtn,
                ]);
              })),
            ])
          : ackRow("all interfaces up", "no down ports on the fabric"));
      });
      ifBtn.replaceChildren(el("span", { html: ic("refresh-cw", 15) }), el("span", { text: " REFRESH DOWN LIST" }));
      ifBtn.disabled = false;
    }
    const ifModel = el("button", { class: "btn ghost gray small", onclick: async () => {
      await opsRun("IFACE_CONFIG", () => API.ifaceConfig(), (d) => {
        setRes(ifRes, opsTable(["interface", "type", "state", "ip", "description"], d,
          (x) => [el("td", { class: "st", text: x.name }), el("td", { class: "muted", text: x.type }), el("td", {}, [statusTag(x.enabled === "up" ? "up" : "down")]), el("td", { class: "mono", text: x.ip || "—" }), el("td", { class: "muted", text: x.description || "—" })],
          "EMPTY", "device returned no interface entries"));
      });
    } }, [ic("rows-3", 13), "FULL MODEL"]);
    cards.push(card("plug-zap", "BRING INTERFACES UP", "every down port on the fabric, listed — one click and it is up",
      el("div", {}, [el("div", { class: "action-bar" }, [ifBtn, ifModel]), ifRes]), "GET · PATCH"));
    refreshDown();

    /* --- tool 4: set interface IP --- */
    const ipRes = el("div", { class: "ops-result" });
    ipRes.appendChild(emptyBox("NO IP CHANGE", "assign a primary IPv4 to a port via PATCH"));
    const ipForm = el("div", { class: "ops-form grid2" }, [
      field("iface", "PORT", null, "0/0/0"),
      field("addr", "ADDRESS", null, "10.0.0.1"),
      field("mask", "MASK", null, "255.255.255.0"),
    ]);
    const ipBtn = el("button", { class: "btn teal", onclick: async () => {
      const g = (k) => (host.querySelector(`[data-key="${k}"]`) || {}).value || "";
      busy(ipBtn, "WRITING…");
      await opsRun("SET_IP", () => API.setIfaceIp(g("iface"), g("addr"), g("mask")), (d) => {
        const iface = (d && d.iface) || g("iface");
        setRes(ipRes, ackRow(`primary IPv4 written to Gi${iface}`, `${(d && d.address) || g("addr")} / ${(d && d.mask) || g("mask")}`));
      });
      idle(ipBtn, "APPLY IP", "pen");
    } }, [ic("pen", 15), "APPLY IP"]);
    cards.push(card("settings", "SET INTERFACE IP", "PATCH the primary IPv4 — Cisco-approved change operation",
      el("div", {}, [ipForm, ipBtn, ipRes]), "PATCH"));

    /* --- tool 5: cli show runner (netmiko ssh) --- */
    const cliRes = el("div", { class: "ops-result" });
    cliRes.appendChild(emptyBox("NO CLI OUTPUT", "run a read-only show command over SSH :22 — netmiko cisco_xe"));
    const cliIn = el("input", {
      type: "text", class: "in",
      placeholder: "show ip interface brief  (read-only verbs: show / dir / more / ping / traceroute)",
      spellcheck: "false", autocomplete: "off",
    });
    const cliShell = el("div", { class: "ops-shell" }, [
      el("span", { class: "ops-shell-p", text: "$" }), cliIn,
    ]);
    const runCli = el("button", { class: "btn teal", onclick: async () => {
      const cmd = cliIn.value.trim();
      if (!cmd) { toast("type a show command first", "warn"); return; }
      busy(runCli, "SSH RUN…");
      const r = await API.cliRun(cmd).catch(() => null);
      idle(runCli, "RUN", "terminal");
      if (!r || !r.ok) {
        setRes(cliRes, el("div", { class: "drift-err", text: "cli run failed — " + ((r && r.error) || "backend unreachable") }));
        return;
      }
      setRes(cliRes, el("pre", { class: "json-view", style: "max-height:340px;overflow:auto;margin-top:8px" },
        [el("code", { text: r.output || "(empty output)" })]));
    } }, [ic("terminal", 15), "RUN"]);
    const diffCli = el("button", { class: "btn ghost yellow", onclick: async () => {
      busy(diffCli, "DIFFING…");
      const r = await API.cliArchiveDiff().catch(() => null);
      idle(diffCli, "ARCHIVE DIFF", "git-compare-arrows");
      if (!r || !r.ok) {
        setRes(cliRes, el("div", { class: "drift-err", text: "archive diff failed — " + ((r && r.error) || "backend unreachable") }));
        return;
      }
      setRes(cliRes, el("div", {}, [
        el("div", { class: "muted mono small", style: "margin-bottom:6px", text: "show archive config diff — last committed change vs running config" }),
        el("pre", { class: "json-view", style: "max-height:340px;overflow:auto" },
          [el("code", { text: r.output || "(no diff — running config equals the last commit)" })]),
      ]));
    } }, [ic("git-compare-arrows", 15), "ARCHIVE DIFF"]);
    cards.push(card("square-terminal", "CLI SHOW RUNNER",
      el("div", { class: "muted small", text: "read-only SSH exec — show/dir/more/ping/traceroute only; write verbs are refused by the backend" }),
      el("div", {}, [el("div", { class: "ops-form row" }, [cliShell]), el("div", { class: "action-bar" }, [runCli, diffCli]), cliRes]), "SSH :22"));

    /* --- tool 6: config timeline / diff --- */
    const tlRes = el("div", { class: "ops-result" });
    tlRes.appendChild(emptyBox("NO TIMELINE", "PULL SNAPSHOTS lists every collected running-config"));
    const tlList = el("div", { class: "nc-list", style: "max-height:180px;overflow:auto" });
    const tlDiffBtn = el("button", { class: "btn teal", onclick: async () => {
      const a = tlList.querySelector("button.on");
      if (!a) { toast("pick a snapshot in the list first", "warn"); return; }
      busy(tlDiffBtn, "DIFFING…");
      const r = await API.configDiff(a.dataset.file, "baseline").catch(() => null);
      idle(tlDiffBtn, "DIFF VS BASELINE", "git-compare-arrows");
      if (!r || !r.ok) {
        setRes(tlRes, el("div", { class: "drift-err", text: "diff failed — " + ((r && r.error) || "backend unreachable") }));
        return;
      }
      setRes(tlRes, el("div", {}, [
        el("div", { class: "muted mono small", style: "margin-bottom:6px", text: `${r.a} vs ${r.b} · ${r.lines} diff lines` + (r.note ? " — " + r.note : "") }),
        el("pre", { class: "json-view", style: "max-height:300px;overflow:auto" }, [el("code", { text: r.diff || "(no differences)" })]),
      ]));
    } }, [ic("git-compare-arrows", 15), "DIFF VS BASELINE"]);
    const tlPull = el("button", { class: "btn ghost teal", onclick: async () => {
      busy(tlPull, "…");
      const r = await API.configHistory().catch(() => null);
      idle(tlPull, "PULL SNAPSHOTS", "history");
      if (!r || !r.ok) {
        setRes(tlRes, el("div", { class: "drift-err", text: "timeline failed — " + ((r && r.error) || "backend unreachable") }));
        return;
      }
      tlList.innerHTML = "";
      for (const it of r.items) {
        tlList.appendChild(el("button", {
          class: "nc-mod-row",
          "data-file": it.file,
          onclick: (ev) => {
            tlList.querySelectorAll("button.on").forEach((b) => b.classList.remove("on"));
            ev.currentTarget.classList.add("on");
          },
        }, [
          el("span", { class: "mono small", text: String(it.ts).slice(0, 15) }),
          el("span", { class: "spacer" }),
          el("span", { class: "muted small", text: (it.size / 1024).toFixed(1) + " KB" }),
        ]));
      }
      setRes(tlRes, el("div", {}, [r.count
        ? el("div", { class: "muted small", text: `${r.count} snapshots — pick one, then DIFF VS BASELINE` + (r.baseline ? "" : " (no baseline captured yet — use the home BASELINE button)") })
        : el("div", { class: "muted small", text: "no snapshots yet — run COLLECT NOW in telemetry" })]));
    } }, [ic("history", 15), "PULL SNAPSHOTS"]);
    cards.push(card("history", "CONFIG TIMELINE",
      el("div", { class: "muted small", text: "saved running-config snapshots — diff any of them against the baseline" }),
      el("div", {}, [el("div", { class: "action-bar" }, [tlPull, tlDiffBtn]), tlList, tlRes]), "ARCHIVE"));

    /* --- tool 7: watchdog (port flap / error burst) --- */
    const wdRes = el("div", { class: "ops-result" });
    wdRes.appendChild(emptyBox("NO WATCH", "RUN WATCHDOG compares the last two snapshots for flaps, error bursts and link drops"));
    const wdBtn = el("button", { class: "btn yellow", onclick: async () => {
      busy(wdBtn, "SCANNING…");
      const r = await API.watchdog().catch(() => null);
      idle(wdBtn, "RUN WATCHDOG", "siren");
      if (!r || !r.ok) {
        setRes(wdRes, el("div", { class: "drift-err", text: "watchdog failed — " + ((r && r.error) || "backend unreachable") }));
        return;
      }
      const s = r.summary || {};
      const rows = (r.alerts || []).map((a) => el("div", {
        class: "fixall-row " + (a.severity === "critical" ? "fail" : a.severity === "warn" ? "skip" : "ok"),
      }, [
        el("span", { class: "mono small", style: "min-width:150px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap", text: a.iface }),
        el("span", { class: "mono", style: "font-size:9px;color:var(--muted)", text: a.kind.toUpperCase() }),
        el("span", { class: "spacer" }),
        el("span", { class: "fixall-v", style: "text-align:right", text: a.detail }),
      ]));
      setRes(wdRes, el("div", {}, [
        el("div", { class: "fixall-panel", style: "margin-bottom:8px" }, [
          el("div", { class: "fixall-head", text: `WATCHDOG // ${s.critical || 0} CRITICAL · ${s.warn || 0} WARN · ${s.info || 0} INFO` }),
          rows.length ? rows : [el("div", { class: "fixall-row ok" }, [el("span", { class: "fixall-v", text: "no anomalies between the last two snapshots" })])],
        ]),
        el("div", { class: "muted small", text: (r.note || "") + ((r.window && r.window.length) ? ` — window ${r.window.join(" → ")}` : "") }),
      ]));
    } }, [ic("siren", 15), "RUN WATCHDOG"]);
    cards.push(card("siren", "WATCHDOG // PORT-FLAP + ERROR BURST",
      el("div", { class: "muted small", text: "client-side pattern detection over collected counters (Cat8kv has no guestshell, so the PortFlap/Spark EEM samples run here on snapshot deltas)" }),
      el("div", {}, [wdBtn, wdRes]), "SNAPSHOTS"));

    /* --- tool 8: extra restconf verbs (dns post / ip delete) --- */
    const rvRes = el("div", { class: "ops-result" });
    rvRes.appendChild(emptyBox("NO VERB RUN", "DNS POST adds a domain name; IP DELETE removes an interface's primary IPv4"));
    const rvDns = field("rv-domain", "DOMAIN NAME", null, "CAT8k-SYNC.local");
    const rvIface = field("rv-iface", "INTERFACE (e.g. 1 or 0/0/1)", null, "1");
    const rvAdd = el("button", { class: "btn teal", onclick: async () => {
      const d = (host.querySelector('[data-key="rv-domain"]') || {}).value || "";
      if (!d.trim()) { toast("domain required", "warn"); return; }
      busy(rvAdd, "POST…");
      const r = await API.dnsAdd(d.trim()).catch(() => null);
      idle(rvAdd, "DNS POST", "globe");
      if (!r || !r.ok) { setRes(rvRes, errBox("REJECTED", (r && r.error) || "backend unreachable")); return; }
      setRes(rvRes, ackRow(`domain applied via ${(r.verb || "POST").toUpperCase()} (native/ip/domain name-container)`, r.domain));
    } }, [ic("globe", 15), "DNS POST"]);
    const rvDel = el("button", { class: "btn ghost red", onclick: async () => {
      const i = (host.querySelector('[data-key="rv-iface"]') || {}).value || "";
      if (!i.trim()) { toast("interface required", "warn"); return; }
      busy(rvDel, "DELETE…");
      const r = await API.ifaceIpDelete(i.trim()).catch(() => null);
      idle(rvDel, "IP DELETE", "trash-2");
      if (!r || !r.ok) { setRes(rvRes, errBox("REJECTED", (r && r.error) || "backend unreachable")); return; }
      setRes(rvRes, ackRow("primary IPv4 removed via DELETE (no address → interface is unnumbered/absent)", r.iface));
    } }, [ic("trash-2", 15), "IP DELETE"]);
    cards.push(card("spline", "RESTCONF VERBS // DNS POST + IP DELETE",
      el("div", { class: "muted small", text: "the two sample verbs the project previously lacked — list-instance create (POST) and instance delete (DELETE)" }),
      el("div", {}, [el("div", { class: "ops-form grid2" }, [rvDns, rvIface]), el("div", { class: "action-bar" }, [rvAdd, rvDel]), rvRes]), "POST · DELETE"));

    host.append(
      el("div", { class: "section-title" }, [
        el("span", { class: "no", text: "∓" }), el("span", { class: "t", text: "OPS TOOLBOX" }),
        el("span", { class: "s", text: "Cisco-approved operations — every run hits the fabric live, never demo data" }),
      ]),
      healthHost,
      el("div", { class: "ops-grid" }, cards),
    );
  }

  /* ============================================================ AUDIT */
  const BANNER_DEFAULT = "Authorized access only. All activity is monitored.";
const FIX = {
    "ssh-version": { cli: ["ip ssh version 2"], summary: "Force SSH v2 (blocks SSHv1)" },
    "vty-transport": { cli: ["line vty 0 4", " transport input ssh"], summary: "Restrict vty 0-4 to SSH input" },
    "exec-timeout": { cli: ["line vty 0 4", " exec-timeout 10 0"], summary: "Set 10m idle session timeout on vty 0-4" },
    "password-encryption": { cli: ["service password-encryption"], summary: "Enable type-7 password encryption" },
    "enable-secret": { cli: ["enable secret 9 <NEW-SECRET>"], summary: "Install enable secret with type-9 hash", needs_value: "New enable secret" },
    "http-plane": { cli: ["ip http secure-server"], summary: "Enable HTTPS-only management HTTP" },
    "domain-lookup": { cli: ["no ip domain lookup"], summary: "Disable IP domain lookup (anti-DNS poisoning)" },
    "syslog": { cli: ["logging host <SYSLOG-SERVER-IP>"], summary: "Point syslog at a collector", needs_value: "Syslog server IP" },
    "ntp": { cli: ["ntp server <NTP-SERVER-IP>"], summary: "Synchronize clock (log integrity)", needs_value: "NTP server IP" },
    "banner": {
      cli: ["banner motd ^C <your phrase> ^C"],
      summary: "Set legal MOTD banner",
      needs_value: "Banner phrase",
      valuePlaceholder: BANNER_DEFAULT,
      allowEmpty: true,
      revert: {
        cli: ["banner motd ^C " + BANNER_DEFAULT + " ^C"],
        summary: "restore the default banner phrase",
      },
      factory: {
        cli: ["no banner motd"],
        summary: "remove the MOTD banner — Catalyst factory default (none)",
      },
    },
  };
const SANDBOX_WARN = "This writes to the LIVE device. DevNet sandboxes are shared and routinely rolled back — pushing to them may violate reservation rules. These remediation actions are intended for your own Catalyst hardware (see CAT8k-SYNC scope: same pipeline runs against any reachable IOS-XE node).";
  const SEV = {
    critical: ["#ff3b5c", "CRITICAL"], high: ["#ff7a45", "HIGH"],
    medium: ["#ffd166", "MEDIUM"], low: ["#8b98b3", "LOW"],
  };
  const CAT_COLOR = {
    "TRANSPORT & SESSION": "var(--teal)", "AUTH & AAA": "var(--blue)",
    "MANAGEMENT PLANE": "var(--green)", "MONITORING": "var(--yellow)",
    "SERVICES & BANNER": "var(--purple)",
  };

  async function commitFlow(check, kind, host) {
    const spec = FIX[check.remediation_id];
    if (!spec) return;
    const isFix = kind === "fix";
    const mode = isFix ? spec : (kind === "revert" ? (spec.revert || null) : (spec.factory || null));
    if (!mode) return;
    const summary = mode.summary || "";
    const body = [
      el("div", { class: "warn-box" }, [ic("triangle-alert", 15), el("span", { text: SANDBOX_WARN })]),
      el("div", { class: "muted small", style: "margin-top:10px", text: isFix
        ? "CLI equivalent — what will be pushed (PATCH /restconf/data + YANG body):"
        : kind === "revert"
          ? "Undo — this writes the default back to the live device (PATCH /restconf/data + YANG body):"
          : "Factory reset — this DELETES the config node (DELETE /restconf/data + YANG path), restoring the Catalyst factory default:" }),
      el("pre", { class: "cli-snippet" }, (mode.cli || []).map((l) => el("div", { text: l })).concat([el("div", { class: "dimmed", text: `→ ${summary}` })])),
    ];
    const title = isFix ? `APPLY REMEDIATION // ${check.id.toUpperCase()}`
      : kind === "revert" ? `REVERT TO DEFAULT :: ${check.id.toUpperCase()}`
      : `FACTORY DEFAULT :: ${check.id.toUpperCase()}`;
    const cta = isFix ? "PUSH TO DEVICE" : kind === "revert" ? "REVERT TO DEFAULT" : "REMOVE FROM DEVICE";
    const cancel = isFix ? API.remediate(check.id, false)
      : kind === "revert" ? API.revert(check.id, false) : API.factory(check.id, false);
    const res = await UI.confirm({
      title, sub: `${check.check} — severity ${(SEV[check.severity] || SEV.medium)[1]}`,
      body, cta, danger: true,
      requireValue: isFix ? spec.needs_value || null : null,
      valuePlaceholder: isFix ? spec.valuePlaceholder || "" : "",
      allowEmpty: isFix ? spec.allowEmpty || false : false,
      onCancel: () => cancel.catch(() => null),
    });
    if (res === false || res == null) {
      toast("remediation cancelled — recorded in ledger", "warn");
      return;
    }
    const value = isFix && typeof res === "string" ? res : "";
    toast(isFix ? "applying — re-scanning fabric after write…"
      : kind === "revert" ? "reverting — re-scanning fabric after write…"
      : "removing — re-scanning fabric after delete…", "sys", 4200);
    const out = isFix
      ? await API.remediate(check.id, true, value).catch(() => null)
      : kind === "revert" ? await API.revert(check.id, true).catch(() => null)
      : await API.factory(check.id, true).catch(() => null);
    if (out && out.ok) {
      const fresh = out.scan;
      const still = isFix && fresh && fresh.checks
        ? fresh.checks.find((c) => c.id === check.id) : null;
      if (still && still.status !== "PASS") {
        toast(`write ok but rescan still reports ${still.status} — verify on the device`, "warn", 5200);
      } else {
        toast(isFix ? "remediation applied — fabric rescanned, check now PASS"
          : kind === "revert" ? "reverted to default — fabric rescanned"
          : "factory default restored — banner removed, fabric rescanned", "ok", 4200);
      }
      setTimeout(() => App.nav("audit"), 1400);
    } else {
      toast(`${isFix ? "remediation" : kind} failed — ${(out && out.reason) || "backend unreachable"}`, "bad");
    }
  }

  async function audit(host) {
    const [sec, posture] = await Promise.all([
      API.security().catch(() => ({ ok: false, checks: [], ledger: [], verify: {} })),
      API.securityPosture(false).catch(() => ({ ok: false, items: [], summary: {}, error: "unreachable" })),
    ]);
    const checks = Array.isArray(sec.checks) ? sec.checks : [];
    const ledger = Array.isArray(sec.ledger) ? sec.ledger : [];
    const verify = sec.verify || {};
    const counts = sec.counts || {};
    const scan = sec.scan || null;
    const score = Number.isFinite(sec.score) ? sec.score : 0;
    const lastScan = scan ? String(scan.ts).slice(0, 16) : "NO SCAN RUN";
    const fixable = (c) => c.remediation_id && FIX[c.remediation_id];

    const cell = (cap, val, accent) => el("div", { class: "chart-cell", style: `--accent:${accent}` }, [
      el("div", { class: "cap", text: cap }), el("div", { class: "val", text: val }),
    ]);
    const sevTag = (s) => {
      const [c, label] = SEV[s] || SEV.medium;
      return el("span", { class: "sev", style: `--sc:${c}` }, [el("i"), label]);
    };
    const catChip = (c) => el("span", {
      class: "cat-chip", style: `--cc:${CAT_COLOR[c] || "var(--teal)"}`,
    }, [el("i"), c]);
    const short = (h) => (h && h.length > 12 ? h.slice(0, 12) + "…" : h || "—");

    /* -------- ledger integrity banner -------- */
    const integ = verify.ok
      ? el("div", { class: "ledger-ok" }, [
          ic("shield-check", 15), el("span", { text: `SHA-256 chain verified — ${verify.total} sealed entries` }),
          el("span", { class: "mono muted", style: "margin-left:auto", text: short(verify.last_hash) }),
        ])
      : el("div", { class: "ledger-bad" }, [
          ic("octagon-alert", 15), el("span", { text: `LEDGER INTEGRITY BROKEN AT ENTRY #${verify.broken_at || "?"} — tampering detected` }),
        ]);

    /* -------- live posture rows -------- */
    const p = posture.summary || {};
    const postureRows = el("div", { class: "card-body", style: "padding-top:0" });
    const renderPosture = (summary) => {
      postureRows.innerHTML = "";
      const defs = [
        ["nacm", "NACM enabled (YANG RBAC)", "RFC 6536 — read/write per YANG node"],
        ["aaa_new_model", "AAA new-model active", "authentication/authorization/accounting"],
        ["ssh_v2", "SSH server v2 only", "SSHv1 is cryptographically broken"],
        ["http_secure", "HTTPS secure-server", "encrypted web management plane"],
        ["http_plain", "Plain HTTP server detected", "exposes config over cleartext"],
      ];
      for (const [k, label, tip] of defs) {
        const row = el("div", { class: "row", style: "justify-content:space-between;padding:7px 0;border-bottom:1px dashed var(--line)" }, [
          el("span", {}, [el("span", { text: label }), el("span", { class: "muted small", style: "margin-left:6px", text: tip })]),
          el("span", { "data-key": k, class: "posture-val" }, [statusTag(summary[k] ? "yes" : "no")]),
        ]);
        postureRows.appendChild(row);
      }
      if (posture.ok === false && posture.error) {
        postureRows.appendChild(el("div", { class: "muted small", style: "margin-top:6px", text: `live survey error: ${posture.error}` }));
      }
    };
    renderPosture(p);

    /* -------- checks table -------- */
    const body = el("tbody", {});
    const renderChecks = () => {
      body.innerHTML = "";
      const list = checks.filter((c) => filter === "ALL" || c.status === filter);
      for (const c of list) {
        body.appendChild(el("tr", { class: "check-row" }, [
          el("td", { class: "st" }, [el("div", { text: c.check }), el("div", { class: "muted small mono", text: c.id })]),
          el("td", {}, [catChip(c.category)]),
          el("td", {}, [sevTag(c.severity)]),
          el("td", {}, [statusTag(c.status.toLowerCase())]),
          el("td", { class: "muted small", text: c.evidence || "—" }),
          el("td", {}, fixable(c)
            ? el("div", { class: "row", style: "gap:6px;justify-content:flex-end" }, [
                el("button", { class: "btn ghost red small", onclick: () => commitFlow(c, "fix", host) }, [ic("wrench", 13), "FIX"]),
                (FIX[c.remediation_id] && FIX[c.remediation_id].revert && c.status === "PASS")
                  ? el("button", { class: "btn ghost gray small iconbtn", title: "Undo — restore default", onclick: () => commitFlow(c, "revert", host) }, [ic("rotate-ccw", 13)])
                  : null,
                (FIX[c.remediation_id] && FIX[c.remediation_id].factory && c.status === "PASS")
                  ? el("button", { class: "btn ghost gray small iconbtn", title: "Factory default — remove config", onclick: () => commitFlow(c, "factory", host) }, [ic("delete", 13)])
                  : null,
              ])
            : el("span", { class: "muted small", title: c.status === "PASS"
                ? "No remediation defined — manual-only check (see glossary)"
                : "Manual-only: no safe YANG endpoint — remediate on the device CLI",
                text: c.status === "PASS" ? "ok" : "manual" })),
        ]));
      }
      if (!list.length) {
        body.appendChild(el("tr", {}, [el("td", { colspan: 6, class: "muted", text: "no checks match this filter" })]));
      }
    };

    /* -------- filter chips -------- */
    const reFilter = () => {
      filterBar.innerHTML = "";
      for (const f of ["ALL", "FAIL", "WARN", "PASS"]) {
        const active = f === filter;
        filterBar.appendChild(el("button", {
          class: "chip" + (active ? " on" : ""), text: f,
          onclick: () => { filter = f; reFilter(); },
        }));
      }
      renderChecks();
    };
    const _firstFilter = reFilter;

    /* -------- fix-all batch remediate -------- */
    const fixBox = el("div", { style: "margin:4px 0 12px" });
    const fixableFailing = () => checks.filter((c) => c.status === "FAIL" && fixable(c));
    const batchable = (c) => {
      const spec = FIX[c.remediation_id];
      return spec && !(spec.needs_value && !spec.allowEmpty);
    };
    const renderFixAllBtn = () => {
      const failing = fixableFailing();
      const n = failing.filter(batchable).length;
      const btn = el("button", {
        class: "btn ghost red small", disabled: !failing.length,
        title: failing.length
          ? n === failing.length
            ? `Batch-apply all ${n} fixable failing checks`
            : `Batch-apply ${n} fixable failing checks (value-required ones need individual input)`
          : "no failing checks to fix",
        onclick: fixAll,
      }, [ic("zap", 13), `FIX-ALL FAILING${n ? " (" + n + ")" : ""}`]);
      filterBarRow.innerHTML = "";
      filterBarRow.append(chipsRow, btn);
    };
    const fixAll = async () => {
      const failing = fixableFailing();
      const will = failing.filter(batchable);
      const skipped = failing.filter((c) => !batchable(c));
      const res = await UI.confirm({
        title: `FIX-ALL // ${will.length} CHECK${will.length === 1 ? "" : "S"}`,
        sub: "batch remediation — PATCH every fixable failing check on the live device, then one re-scan",
        body: [
          el("div", { class: "warn-box" }, [ic("triangle-alert", 15), el("span", { text: SANDBOX_WARN })]),
          el("div", { class: "muted small", style: "margin-top:10px" }, [
            will.length
              ? [el("span", { text: "WILL PUSH — " }), el("span", { class: "mono", text: will.map((c) => c.id).join(", ") })]
              : "nothing to push",
            skipped.length
              ? el("div", { style: "margin-top:6px", text: `SKIPPED (need an operator value — apply individually): ${skipped.map((c) => c.id).join(", ")}` })
              : null,
          ]),
          el("pre", { class: "cli-snippet", style: "margin-top:10px" },
            will.slice(0, 6).flatMap((c) => {
              const spec = FIX[c.remediation_id];
              const lines = (spec && spec.cli) || [];
              return [el("div", { class: "dimmed", text: `# ${c.id.toUpperCase()} — ${c.check}` }),
                ...lines.map((l) => el("div", { text: l }))];
            }).concat([el("div", { class: "dimmed", text: `→ ${will.length} PATCH /restconf/data + YANG bodies, then one re-scan` })])),
        ],
        cta: `PUSH ${will.length} TO DEVICE`, danger: true,
        onCancel: () => API.remediateAll(false).catch(() => null),
      });
      if (res === false || res == null) { toast("fix-all cancelled — recorded in ledger", "warn"); return; }
      if (!will.length) return;
      toast(`applying ${will.length} remediations — collecting once, rescan after…`, "sys", 5000);
      const out = await API.remediateAll(true).catch(() => null);
      if (!out || out.ok === false) {
        toast(`fix-all failed — ${(out && (out.reason || out.error)) || "backend unreachable"}`, "bad");
        return;
      }
      const results = out.results || [];
      const okN = results.filter((r) => r.ok === true).length;
      const skipN = results.filter((r) => r.ok == null).length;
      const failN = results.filter((r) => r.ok === false).length;
      fixBox.innerHTML = "";
      fixBox.append(el("div", { class: "fixall-panel" }, [
        el("div", { class: "fixall-head", text: `FIX-ALL RESULT // ${okN} APPLIED · ${skipN} SKIPPED · ${failN} FAILED` }),
        ...(results.length ? results.map((r) => el("div", { class: "fixall-row " + (r.ok === true ? "ok" : r.ok == null ? "skip" : "fail") }, [
          el("span", { class: "fixall-id mono", text: r.id.toUpperCase() }),
          el("span", { class: "spacer" }),
          el("span", { class: "fixall-v", text: r.ok === true
            ? "APPLIED — fabric rescanned"
            : r.ok == null ? "SKIPPED — needs an operator value (see row button)"
            : "FAILED — " + String(r.reason || "").slice(0, 140) }),
        ])) : [el("div", { class: "fixall-row skip" }, [
          el("span", { class: "fixall-id", text: "—" }), el("span", { class: "spacer" }),
          el("span", { class: "fixall-v", text: "no results returned by backend" }),
        ])]),
      ]));
      toast(`fix-all: ${okN} applied · ${skipN} skipped · ${failN} failed`, failN ? "warn" : "ok");
      if (okN) setTimeout(() => App.nav("audit"), 2200);
    };
    const chipsRow = el("div", { class: "chips", style: "flex:1" });
    const filterBarRow = el("div", { class: "row", style: "gap:8px;align-items:center;margin:12px 0" });
    let filter = "ALL";
    const filterBar = chipsRow;
    _firstFilter();
    renderFixAllBtn();
    host.append(
      el("div", { class: "section-title" }, [
        el("span", { class: "no", text: "A" }), el("span", { class: "t", text: "SECURITY AUDIT" }),
        el("span", { class: "s" }, [
          "hardening posture · ", UI.term("AAA"), " · ", UI.term("TACACS+"), " · ", UI.term("RADIUS"),
          " · ", UI.term("NACM"), " · ", UI.term("RESTCONF"), " · ", UI.term("SHA-256"),
        ]),
      ]),

      el("div", { class: "grid2" }, [
        el("div", { class: "card", style: "--accent:var(--teal)" }, [
          el("div", { class: "card-head" }, [
            el("span", { class: "icon-tile" }, [ic("shield-check", 16, "var(--teal)")]),
            el("span", { class: "t", text: "COMPLIANCE POSTURE" }),
            el("span", { class: "spacer" }),
            el("button", {
              class: "btn teal", onclick: async (ev) => {
                ev.currentTarget.disabled = true;
                const r = await API.scanCompliance(true).catch(() => null);
                toast(r?.ok ? "live scan queued — collecting config first" : "scan failed", r?.ok ? "ok" : "bad");
                setTimeout(() => App.nav("audit"), 1600);
              },
            }, [ic("refresh-cw", 15), "RE-SCAN"]),
          ]),
          el("div", { class: "card-body", style: "display:flex;align-items:center;gap:26px" }, [
            el("span", {
              class: "mono",
              style: `font-size:54px;color:${score >= 80 ? "var(--teal)" : score >= 50 ? "var(--yellow)" : "var(--red)"}`,
              text: String(score) + "%",
            }),
            el("div", { style: "flex:1" }, [
              el("div", { class: "grid2", style: "gap:8px" }, [
                cell("PASS", String(counts.pass ?? 0), "var(--green)"),
                cell("FAIL", String(counts.fail ?? 0), "var(--red)"),
                cell("WARN", String(counts.warn ?? 0), "var(--yellow)"),
                cell("TOTAL", String(checks.length), "var(--teal)"),
              ]),
              el("div", { class: "muted small", style: "margin-top:10px" }, [
                el("span", { text: "LAST SCAN " }), el("span", { class: "mono", text: lastScan }),
                scan && scan.filename ? el("div", { class: "mono", text: scan.filename }) : null,
              ]),
            ]),
          ]),
        ]),

          el("div", { class: "card", style: "--accent:var(--blue)" }, [
          el("div", { class: "card-head" }, [
            el("span", { class: "icon-tile" }, [ic("scan-search", 16, "var(--blue)")]),
            el("span", { class: "t", text: "LIVE POSTURE SURVEY" }),
            el("span", { class: "spacer" }),
            el("span", { class: "muted small", text: "read-only" }),
            el("button", {
              class: "btn ghost teal", style: "margin-left:8px", onclick: async (ev) => {
                ev.currentTarget.disabled = true;
                const pp = await API.securityPosture(true).catch(() => null);
                if (pp) renderPosture(pp.summary || {});
                ev.currentTarget.disabled = false;
              },
            }, [ic("refresh-cw", 14), "REFRESH"]),
          ]),
          postureRows,
        ]),
      ]),

      el("div", { class: "section-title", style: "margin-top:18px" }, [
        el("span", { class: "no", text: "01" }), el("span", { class: "t", text: "HARDENING CHECKS" }),
        el("span", { class: "s", text: `${checks.length} rules — expandable with FIX for RESTCONF-writable controls` }),
      ]),
      el("div", { class: "card" }, [
        filterBarRow,
        fixBox,
        el("table", { class: "tbl" }, [
          el("thead", {}, [el("tr", {}, ["CHECK", "CATEGORY", "SEVERITY", "STATUS", "EVIDENCE", "ACTION"].map((h) => el("th", { text: h })))]),
          body,
        ]),
      ]),

      el("div", { class: "section-title", style: "margin-top:18px" }, [
        el("span", { class: "no", text: "02" }), el("span", { class: "t", text: "IMMUTABLE AUDIT LEDGER" }),
        el("span", { class: "s", text: `append-only ${UI.term("SHA-256")} hash chain — auth, writes, scans, remediation` }),
      ]),
      el("div", { class: "card" }, [
        integ,
        el("table", { class: "tbl", style: "margin-top:10px" }, [
          el("thead", {}, [el("tr", {}, ["#", "TIME", "EVENT", "ACTOR", "ACTION", "HASH"].map((h) => el("th", { text: h })))]),
          el("tbody", {}, ledger.length
            ? ledger.map((e) => el("tr", {}, [
                el("td", { class: "muted", text: String(e.id) }),
                el("td", { class: "muted", text: String(e.ts).slice(5, 16) }),
                el("td", {}, [el("span", { class: "mono st", text: e.event_type })]),
                el("td", { text: e.actor || "system" }),
                el("td", { class: "muted", text: e.action }),
                el("td", { class: "mono muted", text: short(e.checksum) }),
              ]))
            : [el("tr", {}, [el("td", { colspan: 6, class: "muted", text: "ledger empty — first entries appear on login, scans and writes" })])]),
        ]),
      ]),
    );
  }

  /* ============================================================ ANALYTICS */
  async function analytics(host) {
    host.classList.add("no-actions");
    let [stats, telemetry, compliance] = await Promise.all([
      API.stats().catch(() => ({})),
      API.telemetry("interfaces").catch(() => ({})),
      API.compliance().catch(() => ({ checks: [], score: 0, counts: {} })),
    ]);

    const fmtK = (v) => (v == null ? "—"
      : v >= 1e9 ? (v / 1e9).toFixed(2) + "B"
      : v >= 1e6 ? (v / 1e6).toFixed(1) + "M"
      : v >= 1e3 ? (v / 1e3).toFixed(1) + "K"
      : String(v));
    const arr = (o, k) => (o && Array.isArray(o[k]) ? o[k] : []);
    const shortX = (o) => arr(o, "x").map((t) => String(t).slice(5, 16));
    const fill = (vals) => {          /* carry last value over null gaps */
      let p = null;
      return (vals || []).map((v) => {
        if (v == null || !isFinite(v)) return p;
        p = v; return v;
      });
    };
    const cov = (o) => {
      const xs = arr(o, "x");
      return xs.length
        ? "window " + xs.length + " collections · " + String(xs[0]).slice(5, 16) + " → " + String(xs[xs.length - 1]).slice(5, 16)
        : "no history yet — run collections to seed this window";
    };
    const head = (iconName, title, extra) => el("div", { class: "card-head" }, [
      el("span", { class: "icon-tile" }, [ic(iconName, 16, "var(--teal)")]),
      el("span", { class: "t", text: title }),
      el("span", { class: "spacer" }),
      extra || null,
    ]);
    const card = (iconName, title, bodyChildren, extra) => el("div", { class: "card" }, [
      head(iconName, title, extra),
      el("div", { class: "card-body" }, bodyChildren),
    ]);
    const note = (text) => el("div", { class: "an-note", text });
    const sec = (no, t, s) => el("div", { class: "section-title", style: "margin-top:18px" }, [
      el("span", { class: "no", text: no }), el("span", { class: "t", text: t }),
      s ? el("span", { class: "s", text: s }) : null,
    ]);
    const cell = (cap, val, accent) => el("div", { class: "chart-cell", style: `--accent:${accent}` }, [
      el("div", { class: "cap", text: cap }), el("div", { class: "val", text: val }),
    ]);

    /* ---------- compliance / verdict (static) ---------- */
    const checks = Array.isArray(compliance.checks) ? compliance.checks : [];
    const counts = compliance.counts || {};
    const score = Number.isFinite(compliance.score) ? compliance.score : (stats?.compliance ?? 0);
    const lastScan = compliance.ts ? String(compliance.ts).slice(0, 16).replace("T", " ") : "—";
    const verdict = score >= 90
      ? { t: "HEALTHY", c: "var(--green)", i: "shield-check", d: "all policy checks green — keep the baseline current" }
      : score >= 70
        ? { t: "REVIEW", c: "var(--yellow)", i: "triangle-alert", d: "one or more checks need attention — inspect the FAIL / WARN rows below" }
        : { t: "CRITICAL", c: "var(--red)", i: "siren", d: "policy drift is material — re-scan after fixing the failing checks" };

    /* ---------- live links (pure numbers, no charts for counts) ---------- */
    const links = Array.isArray(telemetry?.entries) ? telemetry.entries : [];

    const kpi = (cap, val, color) => el("div", { class: "kpi", style: `--c:${color || "var(--teal)"}` }, [
      el("div", { class: "cap", text: cap }), el("div", { class: "v", text: val }),
    ]);
    const kpiStrip = el("div", { class: "kpi-strip" });
    function renderKpis() {
      const upN = links.filter((l) => String(l.status).toLowerCase() === "up").length;
      const downN = links.length - upN;
      const avail = links.length ? Math.round((100 * upN) / links.length) : null;
      kpiStrip.replaceChildren(
        kpi("INTERFACES", links.length ? String(links.length) : "—", "var(--teal)"),
        kpi("UP", links.length ? String(upN) : "—", "var(--green)"),
        kpi("DOWN", links.length ? String(downN) : "—", "var(--red)"),
        kpi("AVAILABILITY", avail == null ? "—" : avail + "%", "var(--blue)"),
        kpi("DRIFT", String(stats?.drift ?? "—"), "var(--yellow)"),
        kpi("SNAPSHOTS", String(stats?.snapshots ?? "—"), "var(--blue)"),
        kpi("UPTIME", (stats?.uptime_days ?? "—") + " d", "var(--teal)"),
      );
    }

    /* ---------- deep long-term analytics (SQL history) ---------- */
    const RANGES = [[24, "1D"], [72, "1W"], [168, "1M"], [400, "ALL"]];
    let span = 72;
    let deep = await API.analyticsDeep(span).catch(() => null);
    const deepHost = el("div", { class: "col", style: "gap:16px" });

    function pktCard() {
      const pk = (deep && deep.pkt) || { labels: [], entries: [] };
      const entries = pk.entries || [];
      let idx = 0;
      const btns = [];
      const chartBox = el("div");
      function draw() {
        const e = entries[idx];
        chartBox.replaceChildren(e
          ? Charts.bars({ labels: pk.labels || [], h: 200, series: [
              { name: "RX", color: "var(--teal)", vals: e.rx },
              { name: "TX", color: "var(--blue)", vals: e.tx },
            ] })
          : el("div", { class: "muted small", text: "no packet-size distribution collected yet — collect pkt-dist in telemetry" }));
      }
      draw();
      return card("boxes", "PACKET SIZE DISTRIBUTION", [
        entries.length ? el("div", { class: "chips-row" }, entries.map((en, i) => {
          const b = el("button", {
            class: "chip-sel" + (i === idx ? " on" : ""),
            onclick: () => { idx = i; btns.forEach((x, j) => x.classList.toggle("on", j === i)); draw(); },
          }, [el("span", { class: "mono", text: en.name }), el("span", { class: "muted", text: fmtK(en.total_rx) + " rx" })]);
          btns.push(b);
          return b;
        })) : null,
        chartBox,
        note("cumulative packets per octet bucket — the shape of the flow mix (small vs large frames)"),
      ]);
    }

    function renderDeep() {
      const d = deep || {};
      const downN = links.filter((l) => String(l.status).toLowerCase() !== "up").length;
      const snapTs = telemetry?.ts ? String(telemetry.ts).slice(0, 16).replace("T", " ") : null;
      const talkers = (d.talkers || []).slice(0, 3);
      deepHost.replaceChildren(
        sec("01", "LONG-TERM TRENDS", "drawn from the local snapshot database — pick a window above"),
        el("div", { class: "grid2" }, [
          card("cpu", "RESOURCE LOAD", [
            Charts.area({ x: shortX(d.cpu), h: 190, unit: "%", series: [
              { name: "CPU %", color: "var(--teal)", vals: d.cpu && d.cpu.vals },
              { name: "MEM %", color: "var(--green)", vals: d.mem && d.mem.vals },
            ] }),
            note(cov(d.cpu)),
          ], winChips()),
          card("activity", "FABRIC AVAILABILITY", [
            Charts.area({ x: shortX(d.avail), h: 190, unit: "%", series: [
              { name: "AVAIL %", color: "var(--blue)", vals: fill(d.avail && d.avail.vals) },
            ] }),
            note(cov(d.avail)),
          ], winChips()),
        ]),
        el("div", { class: "grid2" }, [
          card("shield-check", "COMPLIANCE SCORE HISTORY", [
            Charts.area({ x: shortX(d.audit), h: 190, unit: "%", series: [
              { name: "SCORE %", color: "var(--green)", vals: d.audit && d.audit.score },
            ] }),
            note(cov(d.audit)),
          ], winChips()),
          card("network", "ARP SCALE", [
            Charts.area({ x: shortX(d.arp), h: 190, series: [
              { name: "ARP ENTRIES", color: "var(--teal)", vals: d.arp && d.arp.vals },
            ] }),
            note(cov(d.arp) + ((d.arp && d.arp.vals && d.arp.vals.length) ? " · last " + d.arp.vals[d.arp.vals.length - 1] : "")),
          ], winChips()),
        ]),
        sec("02", "TRAFFIC & ERROR ANALYSIS", "throughput and counter anomalies per snapshot window"),
        el("div", { class: "grid-3-2" }, [
          card("activity", "THROUGHPUT — FABRIC RX / TX", [
            Charts.area({ x: shortX(d.thr), h: 200, unit: "k", series: [
              { name: "RX kbps", color: "var(--teal)", vals: d.thr && d.thr.rx },
              { name: "TX kbps", color: "var(--blue)", vals: d.thr && d.thr.tx },
            ] }),
            note(cov(d.thr)),
          ], winChips()),
          card("siren", "ERROR & FLAP BURSTS", [
            Charts.bars({ labels: shortX(d.errs), h: 200, series: [
              { name: "IN-ERR", color: "var(--red)", vals: d.errs && d.errs.in_errors },
              { name: "CRC", color: "var(--yellow)", vals: d.errs && d.errs.crc },
              { name: "FLAPS", color: "var(--blue)", vals: d.errs && d.errs.flaps },
            ] }),
            note(cov(d.errs)),
          ], winChips()),
        ]),
        el("div", { class: "grid-3-2" }, [
          card("gauge", "TOP TALKERS — RX TREND", [
            Charts.area({ x: shortX(d.thr), h: 200, unit: "k", series: talkers.map((t, i) => ({
              name: t.name, color: ["var(--teal)", "var(--yellow)", "var(--blue)"][i], vals: t.vals,
            })) }),
            note(talkers.length ? talkers.map((t) => `${t.name} ${fmtK(t.rx)}k rx`).join(" · ") : "no talker data yet"),
          ], winChips()),
          card("triangle-alert", "PROBLEM INTERFACES", [
            (d.problems && d.problems.length)
              ? el("table", { class: "tbl" }, [
                  el("thead", {}, [el("tr", {}, ["INTERFACE", "STATE", "RX", "TX", "CRC", "FLAPS", "IN-ERR"].map((h) => el("th", { text: h })))]),
                  el("tbody", {}, d.problems.map((p) => el("tr", {}, [
                    el("td", { class: "st", text: p.name }),
                    el("td", {}, [statusTag(String(p.state).toLowerCase() === "up" ? "up" : "down")]),
                    el("td", { class: "mono", text: fmtK(p.rx) + "k" }),
                    el("td", { class: "mono", text: fmtK(p.tx) + "k" }),
                    el("td", { class: "mono", style: p.crc ? "color:var(--yellow)" : "", text: String(p.crc) }),
                    el("td", { class: "mono", style: p.flaps ? "color:var(--yellow)" : "", text: String(p.flaps) }),
                    el("td", { class: "mono", style: p.in_errors ? "color:var(--red)" : "", text: String(p.in_errors) }),
                  ]))),
                ])
              : el("div", { class: "ops-empty" }, [
                  el("div", { class: "t", text: "NO COUNTER ANOMALIES" }),
                  el("div", { class: "muted small", text: "latest snapshot is clean — no flaps, CRC or input-error growth" }),
                ]),
            note("interfaces with flaps / CRC / input errors > 0 in the latest snapshot"),
          ]),
        ]),
        sec("03", "PACKET INSPECTION & EVENT PROFILE", "flow mix by size + activity windows"),
        el("div", { class: "grid-3-2" }, [
          pktCard(),
          card("activity", "EVENT ACTIVITY — 24H", [
            Charts.heat({ cells: d.hourly, h: 200 }),
            note("logged events per hour of day — spot quiet and noisy windows"),
          ]),
        ]),
        sec("04", "POLICY & LINKS", "compliance detail + live link alerts"),
        el("div", { class: "grid-3-2" }, [
          card("shield-check", "COMPLIANCE POLICY CHECKS", [
            checks.length
              ? el("div", { class: "chk-list" }, checks.map((chk) => {
                  const st = chk.pass ? "pass" : chk.status === "WARN" ? "warn" : "fail";
                  return el("div", { class: "chk-row " + st }, [
                    el("div", { class: "col", style: "gap:3px;flex:1;min-width:0" }, [
                      el("div", { class: "mono", text: chk.name }),
                      chk.detail ? el("div", { class: "muted small", text: chk.detail }) : null,
                    ]),
                    statusTag(st),
                  ]);
                }))
              : el("div", { class: "ops-empty" }, [
                  el("div", { class: "t", text: "NO SCAN RUN YET" }),
                  el("div", { class: "muted small", text: "hit RE-SCAN to audit the last collected running-config" }),
                ]),
            note(String(counts.pass ?? 0) + " PASS · " + String(counts.fail ?? 0) + " FAIL · " + String(counts.warn ?? 0) + " WARN across " + checks.length + " checks"),
          ], el("span", { class: "muted small", text: "last scan " + lastScan })),
          card("network", "LINK ALERTS — LIVE TELEMETRY", [
            downN
              ? el("div", { class: "link-alerts" }, [
                  el("div", { class: "t", text: downN + " DOWN LINK" + (downN > 1 ? "S" : "") }),
                  links.filter((l) => String(l.status).toLowerCase() !== "up").map((l) =>
                    el("div", { class: "link-row" }, [
                      el("span", { class: "mono", text: l.name }),
                      el("span", { class: "muted small", text: (l.vlan ? "vlan " + l.vlan : "") || l.ip || "—" }),
                      statusTag("down"),
                    ])),
                ])
              : el("div", { class: "ops-ack", style: "margin-top:6px" }, [
                  el("span", {}, [statusTag("ok")]),
                  el("span", { style: "font-weight:600", text: "all links healthy" }),
                ]),
            note(snapTs ? "telemetry snapshot " + snapTs + " — COLLECT NOW in telemetry refreshes" : "no telemetry snapshot yet — collect in telemetry"),
          ]),
        ]),
      );
    }

    const winChips = () => el("div", { class: "seg-row win-chips" }, [
      RANGES.map(([n, lbl]) => el("button", {
        class: "seg-btn" + (span === n ? " on" : ""),
        title: "last " + n + " collections",
        onclick: async () => {
          span = n;
          deep = await API.analyticsDeep(span).catch(() => null);
          renderDeep();
        },
      }, [lbl])),
    ]);

    const rescanBtn = el("button", {
      class: "btn teal", style: "justify-content:center", onclick: async (ev) => {
        ev.currentTarget.disabled = true;
        ev.currentTarget.replaceChildren(
          el("span", { html: ic("loader-circle", 15) }), el("span", { text: " SCAN QUEUED — COLLECTING CONFIG…" }));
        const r = await API.scanCompliance(true).catch(() => null);
        toast(r?.ok ? "live scan queued — collecting a fresh config first" : "scan failed", r?.ok ? "ok" : "bad");
        setTimeout(() => App.nav("analytics"), 1400);
      },
    }, [ic("refresh-cw", 15), "RE-SCAN"]);

    renderKpis();
    renderDeep();

    /* ---------- auto-refresh: re-read the SQL store every 30s ---------- */
    const AUTOREFRESH_MS = 30000;
    const liveChip = el("span", { class: "live-chip" }, [
      el("span", { class: "dot" }), "LIVE · " + AUTOREFRESH_MS / 1000 + "S",
    ]);
    let tickBusy = false;
    let ticks = 0;
    async function tickDeep() {
      if (tickBusy || !document.contains(deepHost)) return;
      tickBusy = true;
      try {
        const [d, tel, st] = await Promise.all([
          API.analyticsDeep(span).catch(() => null),
          API.telemetry("interfaces").catch(() => null),
          API.stats().catch(() => null),
        ]);
        if (!document.contains(deepHost)) return;
        if (d) deep = d;
        if (tel) { telemetry = tel; links.length = 0; links.push(...(Array.isArray(tel.entries) ? tel.entries : [])); }
        if (st) stats = st;
        renderKpis();
        renderDeep();
        ticks += 1;
      } finally { tickBusy = false; }
    }
    let autoId = setInterval(tickDeep, AUTOREFRESH_MS);
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) { clearInterval(autoId); autoId = null; }
      else if (!autoId) autoId = setInterval(tickDeep, AUTOREFRESH_MS);
    });
    window.__cat8kDebug = window.__cat8kDebug || {};
    window.__cat8kDebug.tickAnalytics = tickDeep;
    window.__cat8kDebug.ticks = () => ticks;
    window.__cat8kDebug.lastX = () => (deep && deep.cpu && deep.cpu.x ? deep.cpu.x[deep.cpu.x.length - 1] : "");
    window.__cat8kDebug.nSamples = (k) => (deep && deep[k] && deep[k].vals ? deep[k].vals.length : 0);

    host.append(
      el("div", { class: "section-title" }, [
        el("span", { class: "no", text: "∓" }), el("span", { class: "t", text: "FABRIC ANALYTICS" }),
        el("span", { class: "s", text: "long-term series drawn from the snapshot database — numbers, not decoration" }),
        liveChip,
      ]),
      kpiStrip,
      el("div", { class: "grid-3-2", style: "margin-top:16px" }, [
        el("div", { class: "card", style: "--accent:var(--teal)" }, [
          head("percent", "COMPLIANCE SCORE", el("span", { class: "verdict", style: `--c:${verdict.c}` }, [ic(verdict.i, 13), verdict.t])),
          el("div", { class: "card-body" }, [
            el("div", { class: "score-grid" }, [
              Charts.gauge({ value: score, max: 100, label: "SCORE", unit: "%", sub: verdict.d }),
              el("div", { class: "grid2", style: "flex:1" }, [
                cell("PASS", String(counts.pass ?? 0), "var(--green)"),
                cell("FAIL", String(counts.fail ?? 0), "var(--red)"),
                cell("WARN", String(counts.warn ?? 0), "var(--yellow)"),
                cell("TOTAL CHECKS", String(checks.length), "var(--teal)"),
              ]),
            ]),
            el("div", { class: "an-meta", style: "margin-top:10px" }, [
              el("span", { class: "chip" }, [ic("calendar-days", 12), " LAST SCAN " + lastScan]),
              el("span", { class: "chip" }, [ic("timer", 12), " UPTIME " + (stats?.uptime_days ?? "—") + " d"]),
              el("span", { class: "chip" }, [ic("triangle-alert", 12), " DRIFT " + (stats?.drift ?? 0) + " items"]),
            ]),
          ]),
        ]),
        el("div", { class: "card", style: "--accent:var(--green)" }, [
          head("scan-line", "SCAN CONTROL"),
          el("div", { class: "card-body" }, [
            el("div", { class: "pipe" }, [
              el("div", { class: "pipe-step" }, [ic("download", 15, "var(--teal)"), el("span", { text: "COLLECT" }), el("span", { class: "muted", text: (stats?.snapshots ?? 0) + " snaps" })]),
              el("div", { class: "pipe-step" }, [ic("scan-line", 15, "var(--teal)"), el("span", { text: "SCAN" }), el("span", { class: "muted", text: (stats?.audits ?? 0) + " audits" })]),
              el("div", { class: "pipe-step" }, [ic("percent", 15, "var(--teal)"), el("span", { text: "SCORE" }), el("span", { class: "muted", text: String(score) + "%" })]),
            ]),
            rescanBtn,
            el("div", { class: "muted small", text: "RE-SCAN pulls a fresh running-config over RESTCONF first, then audits policy against the baseline — results land on this page when the task completes." }),
          ]),
        ]),
      ]),
      deepHost,
    );
  }

  /* ============================================================ PROFILE */
  async function profile(host) {
    const st = await API.getState();
    const creds = await API.creds();
    const vpn = st.vpn;
    const res = st.res_creds || {};
    const STANCE = {
      auto: { icon: "wand-2", t: "AUTO STANCE", s: "probe decides — reservation when its tunnel answers, else the public instance" },
      normal: { icon: "globe", t: "NORMAL // PUBLIC C8K", s: "always the public Catalyst 8000 — no VPN required" },
      reservation: { icon: "router", t: "RESERVATION // CAT8KV", s: "IOS XE on Cat8kv behind AnyConnect — tunnel required" },
    };
    const fold = (icon, color, title, body, open = true) => {
      const chev = el("span", { class: "fold-chev", html: ic("chevron-right", 14) });
      const head = el("button", { class: "fold-head", type: "button", onclick: () => {
        const hidden = body.classList.toggle("hidden");
        chev.classList.toggle("open", !hidden);
      } }, [
        el("span", { class: "icon-tile" }, [ic(icon, 14, color)]),
        el("span", { class: "t", text: title }),
        el("span", { style: "flex:1" }),
        chev,
      ]);
      if (!open) body.classList.add("hidden");
      else chev.classList.add("open");
      return el("div", { class: "fold" }, [head, body]);
    };
    const compIcon = { devbox: "terminal", xrv: "layers-3", nexus: "network" };
    const stackField = (key, label, value, placeholder = "") => {
      const row = el("div", { class: "field stack" });
      row.appendChild(el("label", { text: label }));
      const input = el("input", { type: "text", value, placeholder });
      input.dataset.key = key;
      row.appendChild(input);
      return row;
    };
    const compRow = (s) => {
      const body = el("div", { class: "comp-body" }, [
        el("div", { class: "cred-grid" }, [
          el("div", { class: "wide" }, [stackField(`res_${s.slug}_host`, "HOST", s.host || "", "10.10.20.x")]),
          stackField(`res_${s.slug}_port`, "PORT", String(s.port || 22), "22"),
          stackField(`res_${s.slug}_user`, "USERNAME", s.username || "", "developer"),
          el("div", { class: "wide" }, [passwordField(`res_${s.slug}_pass`, "PASSWORD", s.password || "", "••••••••", null, true)]),
        ]),
        el("div", { class: "comp-save" }, [
          el("button", { class: "btn teal xsmall", onclick: () => saveResSet(s.slug) }, [ic("save", 12), "SEAL & SAVE"]),
        ]),
      ]);
      const chev = el("span", { class: "fold-chev", html: ic("chevron-right", 14) });
      const head = el("button", { class: "comp-head", type: "button", onclick: () => {
        const hidden = body.classList.toggle("hidden");
        chev.classList.toggle("open", !hidden);
      } }, [
        el("span", { class: "icon-tile small" }, [ic(compIcon[s.slug] || "server", 13, "var(--dim)")]),
        el("span", { class: "t", html: s.label + ' <span class="comp-desc">// ' + s.desc + "</span>" }),
        el("span", { class: "mono muted comp-addr", text: `${s.host}:${s.port} · ${s.username}` }),
        chev,
      ]);
      if (s.slug !== "devbox") body.classList.add("hidden");
      else chev.classList.add("open");
      return el("div", { class: "comp" }, [head, body]);
    };
    const tiles = (b) => ["auto", "normal", "reservation"].map((m) => {
      const c = STANCE[m];
      return el("button", {
        class: "inst-opt" + (b?.mode === m ? " on" : ""), "data-backend": m,
        onclick: () => pickBackend(m),
      }, [
        el("span", { class: "inst-ic" }, [ic(c.icon, 17)]),
        el("span", { class: "inst-lines" }, [
          el("span", { class: "inst-t", text: c.t }),
          el("span", { class: "inst-s", text: c.s }),
        ]),
      ]);
    });
    const liveCell = (label, id, val) =>
      el("div", { class: "live-cell" }, [
        el("div", { class: "cap", text: label }),
        el("div", { class: "val", id, text: val || "…" }),
      ]);

    const ACTS = [
      {
        m: "public", icon: "globe", color: "var(--green)",
        t: "INSTANCE 01 // PUBLIC CATALYST 8000",
        d: "the always-on public instance — RESTCONF/SSH at devnetsandboxiosxec8k.cisco.com, no VPN required",
        cta: "OPEN CREDENTIALS",
      },
      {
        m: "reservation", icon: "router", color: "var(--yellow)",
        t: "INSTANCE 02 // CAT8KV RESERVATION",
        d: "IOS XE on Cat8kv behind AnyConnect — tunnel access, router login and companion devices",
        cta: "OPEN CREDENTIALS",
      },
    ];
    const modeBar = el("div", { class: "row", style: "gap:10px;margin-bottom:14px;display:none" }, [
      el("button", { id: "mode-back", class: "btn ghost gray", onclick: () => enterMode(null) }, [ic("arrow-left", 14), "OVERVIEW"]),
      el("span", { class: "muted mono small", id: "mode-label", text: "" }),
      el("span", { class: "spacer" }),
    ]);
    const body = el("div", { class: "card", style: "padding:0" });

    function enterMode(m) {
      mode = m;
      modeBar.style.display = m === null ? "none" : "flex";
      const label = m === "public" ? "PUBLIC C8K // CREDENTIALS"
        : m === "reservation" ? "CAT8KV RESERVATION // CREDENTIALS" : "";
      const ml = modeBar.querySelector("#mode-label");
      if (ml) ml.textContent = label;
      render();
    }

    function renderOverview() {
      body.innerHTML = "";
      body.appendChild(el("div", {}, [
        el("div", { class: "section-title" }, [
          el("span", { class: "no", text: "∓" }), el("span", { class: "t", text: "OPERATOR PROFILE" }),
          el("span", { class: "s", text: "introduction — who you are, which fabric is live, and which instance's credits to manage" }),
        ]),
        el("div", { class: "grid-3-2" }, [
          el("div", { class: "card", style: "--accent:var(--teal)" }, [
            el("div", { class: "card-head" }, [el("span", { class: "icon-tile" }, [ic("fingerprint", 16, "var(--teal)")]), el("span", { class: "t", text: "IDENTITY" })]),
            el("div", { class: "card-body" }, [
              field("full_name", "OPERATOR NAME", null, st.profile?.full_name || ""),
              field("role", "ROLE", null, st.profile?.role || ""),
              field("site", "NOC SITE", null, st.profile?.site || ""),
              el("div", { style: "text-align:right;margin-top:8px" }, [
                el("button", { class: "btn teal", onclick: async () => {
                  const g = (k) => (host.querySelector(`[data-key="${k}"]`) || {}).value || "";
                  await API.updateProfile({ full_name: g("full_name"), role: g("role"), site: g("site") });
                  toast("profile updated", "ok");
                } }, [ic("save", 15), "SAVE"]),
              ]),
            ]),
          ]),
          el("div", { class: "card", style: "--accent:var(--teal)" }, [
            el("div", { class: "card-head" }, [el("span", { class: "icon-tile" }, [ic("milestone", 16, "var(--teal)")]), el("span", { class: "t", text: "FABRIC SELECTOR // ACTIVE INSTANCE" })]),
            el("div", { class: "card-body" }, [
              el("div", { class: "hint", style: "margin:0 0 10px", text: "One console, two instances. Choose which fabric the console targets — every endpoint (RESTCONF / SSH / NETCONF / ping) follows the choice below instantly." }),
              el("div", { class: "inst-stack", id: "backend-seg" }, tiles(st.backend)),
              el("div", { class: "live-grid", id: "backend-live" }, [
                liveCell("ACTIVE INSTANCE", "b-source", st.backend?.source),
                liveCell("IDENTITY", "b-identity", st.backend?.identity),
                liveCell("STANCE", "b-mode", st.backend?.mode),
                liveCell("DEVICE", "b-host", st.backend?.host),
                liveCell("TUNNEL", "b-tunnel", st.backend?.tunnel ? "UP" : "DOWN"),
                liveCell("RESERVATION DEV", "b-vpn-host", st.backend?.vpn_host),
                liveCell("STATUS", "b-reason", st.backend?.reason || "ok"),
              ]),
              el("div", { class: "muted small", style: "margin-top:10px;line-height:1.6", text: "The stance (device.backend) and the resolved instance (device.identity) are persisted to SQLite — instance-specific pages key off them automatically." }),
            ]),
          ]),
        ]),
        el("div", { class: "row", style: "gap:10px;margin-top:14px;flex-wrap:wrap" }, [
          el("span", { class: "chip", text: "IDENTITY // " + (st.backend?.identity || "—") }),
          el("span", { class: "chip", text: "STANCE // " + (st.backend?.mode || "—") }),
          el("span", { class: "chip", text: "DEVICE // " + (st.backend?.host || "—") }),
          el("span", { class: "chip", text: "TUNNEL // " + (st.backend?.tunnel ? "UP" : "DOWN") }),
        ]),
        el("div", { class: "section-title", style: "margin-top:18px" }, [
          el("span", { class: "no", text: "P" }), el("span", { class: "t", text: "CREDENTIAL HUB" }),
          el("span", { class: "s", text: "choose the instance — its credits open in a dedicated studio" }),
        ]),
        el("div", { class: "act-grid" }, ACTS.map((a) =>
          el("div", { class: "card act-card", "data-studio": a.m, style: `--accent:${a.color}`, onclick: () => enterMode(a.m) }, [
            el("div", { class: "act-ic" }, [ic(a.icon, 24, a.color)]),
            el("div", { class: "act-t", text: a.t }),
            el("div", { class: "act-d", text: a.d }),
            el("div", { class: "act-cta" }, [el("span", { text: a.cta }), ic("arrow-right", 14)]),
          ]))),
      ]));
    }

    function renderPublic() {
      body.innerHTML = "";
      body.appendChild(el("div", {}, [
        el("div", { class: "section-title" }, [
          el("span", { class: "no", text: "S1" }), el("span", { class: "t", text: "PUBLIC INSTANCE // CREDENTIALS" }),
          el("span", { class: "s", text: "the always-on public Catalyst 8000 — sealed fernet vault, verified against the live device" }),
        ]),
        el("div", { class: "grid-2" }, [
          el("div", { class: "card", style: "--accent:var(--green)" }, [
            el("div", { class: "card-head" }, [el("span", { class: "icon-tile" }, [ic("globe", 16, "var(--green)")]), el("span", { class: "t", text: "PUBLIC DEVICE LOGIN" })]),
            el("div", { class: "card-body" }, [
              el("div", { class: "cred-grid" }, [
                el("div", { class: "wide" }, [stackField("creds_host", "DEVICE HOST", creds?.host || "", "devnetsandboxiosxec8k.cisco.com")]),
                stackField("creds_username", "USERNAME", creds?.username || "", "admin"),
                passwordField("creds_password", "PASSWORD", creds?.password || "", "••••••••", null, true),
                el("div", { class: "wide" }, [passwordField("creds_secret", "ENABLE SECRET (optional)", creds?.secret || "", "••••••••", null, true)]),
              ]),
              el("div", { id: "creds-status" }),
              el("div", { class: "row", style: "justify-content:flex-end;gap:8px;margin-top:10px" }, [
                el("button", {
                  class: "btn ghost gray", onclick: () => modal({
                    title: "VAULT POLICY",
                    sub: "key material",
                    body: [el("p", { class: "muted", text: "Fernet 256-bit master key stored in the user profile directory. Credentials are sealed before they touch disk — this console never logs them." })],
                  }),
                }, [ic("key-square", 14), "VAULT DETAILS"]),
                el("button", { class: "btn teal", id: "creds-save", onclick: () => saveCreds() }, [ic("plug-zap", 14), "TEST & SAVE"]),
              ]),
            ]),
          ]),
          el("div", { class: "card", style: "--accent:var(--green)" }, [
            el("div", { class: "card-head" }, [el("span", { class: "icon-tile" }, [ic("activity", 16, "var(--green)")]), el("span", { class: "t", text: "SEALED STATE" })]),
            el("div", { class: "card-body" }, [
              el("div", { id: "creds-live", class: "creds-live" }, [
                el("div", { class: "row", style: "justify-content:space-between;padding:6px 0" }, [el("span", { text: "host" }), el("span", { class: "mono muted", id: "c-host", text: creds?.host || "—" })]),
                el("div", { class: "row", style: "justify-content:space-between;padding:6px 0" }, [el("span", { text: "username" }), el("span", { class: "mono muted", id: "c-user", text: creds?.username || "—" })]),
                el("div", { class: "row", style: "justify-content:space-between;padding:6px 0" }, [el("span", { text: "secret" }), el("span", { class: "mono muted", id: "c-secret", text: creds?.secret ? "********" : "unset" })]),
              ]),
              el("div", { class: "hint neutral", style: "margin-top:10px", text: "Nothing is stored until the live probe succeeds — TEST & SAVE validates host, username and password against the device first." }),
            ]),
          ]),
        ]),
        el("div", { class: "row", style: "gap:10px;margin-top:14px" }, [
          el("button", { class: "btn ghost gray", onclick: () => enterMode(null) }, [ic("arrow-left", 15), "BACK TO OVERVIEW"]),
        ]),
      ]));
    }

    function renderReservation() {
      body.innerHTML = "";
      body.appendChild(el("div", {}, [
        el("div", { class: "section-title" }, [
          el("span", { class: "no", text: "S1" }), el("span", { class: "t", text: "RESERVATION INSTANCE // CREDENTIALS" }),
          el("span", { class: "s", text: "IOS XE on Cat8kv behind AnyConnect — tunnel access, router login and companion devices" }),
        ]),
        el("div", { class: "grid-2" }, [
          el("div", { class: "card", style: "--accent:var(--yellow)" }, [
            el("div", { class: "card-head" }, [el("span", { class: "icon-tile" }, [ic("router", 16, "var(--yellow)")]), el("span", { class: "t", text: "TUNNEL + ROUTER LOGIN" })]),
            el("div", { class: "card-body" }, [
              el("div", { class: "live-grid" }, [
                liveCell("QUICK ACCESS", "v-address", vpn?.address),
                liveCell("QUICK USER", "v-user", vpn?.username),
                liveCell("ROUTER DEVICE", "v-devhost", vpn?.device_host || "10.10.20.48 (default)"),
                liveCell("ROUTER LOGIN", "v-devuser", vpn?.device_username || "developer (default)"),
                liveCell("CLIENT", "v-client", "…"),
                liveCell("TUNNEL", "v-tunnel", "…"),
              ]),
              el("div", { id: "vpn-status" }),
              fold("wifi", "var(--yellow)", "TUNNEL ACCESS // ANYCONNECT QUICK ACCESS", el("div", { class: "fold-body" }, [
                el("div", { class: "cred-grid" }, [
                  el("div", { class: "wide" }, [stackField("vpn_address", "vpn_address", vpn?.address || "", "devnetsandbox-usw1-reservation.cisco.com:20291")]),
                  stackField("vpn_username", "vpn_username", vpn?.username || "", "reqasse"),
                  passwordField("vpn_password", "vpn_password", vpn?.password || "", "••••••••", null, true),
                ]),
              ])),
              fold("key-square", "var(--teal)", "ROUTER ACCESS // IOS XE ON CAT8KV", el("div", { class: "fold-body" }, [
                el("div", { class: "cred-grid" }, [
                  el("div", { class: "wide" }, [stackField("vpn_device_host", "VPN DEVICE HOST // INSIDE TUNNEL", vpn?.device_host || "", "10.10.20.48 — mgmt IP of the IOS XE on Cat8kv, from your reservation page")]),
                  stackField("vpn_device_user", "vpn_device_username", vpn?.device_username || "", "developer"),
                  passwordField("vpn_device_pass", "vpn_device_password", vpn?.device_password || "", "C1sco12345", "leave as-is for the DevNet default", true),
                ]),
                el("div", { class: "warn-box", style: "margin-top:10px" }, [ic("circle-help", 14), el("span", { text: "The device host lives ONLY inside the tunnel. The router login is NOT the Quick-Access login — this box keeps them separate and the sandbox default applies when left empty." })]),
              ]), false),
            ]),
          ]),
          el("div", { class: "card", style: "--accent:var(--yellow)" }, [
            el("div", { class: "card-head" }, [el("span", { class: "icon-tile" }, [ic("server", 16, "var(--dim)")]), el("span", { class: "t", text: "FABRIC COMPANIONS" })]),
            el("div", { class: "card-body" }, [
              el("div", { class: "hint", style: "margin:0 0 8px", text: "Side devices of the same reservation — each sealed separately; DevNet defaults apply when left empty." }),
              ...["devbox", "xrv", "nexus"].map((slug) => compRow(res[slug] || { slug })),
              el("div", { class: "vpn-actions" }, [
                el("button", { class: "btn ghost gray", id: "vpn-check", title: "re-check client + tunnel state", onclick: () => vpnRefresh() }, [ic("refresh-cw", 14), "REFRESH"]),
                el("button", { class: "btn ghost red", id: "vpn-disconnect", title: "tear down the AnyConnect tunnel", onclick: () => vpnDisconnect() }, [ic("power", 14), "DISCONNECT"]),
                el("button", { class: "btn ghost", id: "vpn-save", title: "seal the reservation access into the fernet vault", onclick: () => saveVpnAccess() }, [ic("save", 14), "SAVE RESERVATION"]),
                el("button", { class: "btn teal", id: "vpn-connect", title: "connect AnyConnect with the quick-access login", onclick: () => vpnConnect() }, [ic("wifi", 14), "CONNECT VPN"]),
              ]),
            ]),
          ]),
        ]),
      ]));
    }

    function render() {
      if (mode === "public") renderPublic();
      else if (mode === "reservation") renderReservation();
      else renderOverview();
    }

    let mode = null;
    host.append(el("div", { class: "stagger" }, [modeBar, body]));
    render();
    vpnRefresh();

    function passwordField(key, label, value, placeholder = "••••••••", hint = null, stack = false) {
      const input = el("input", { type: "password", value, placeholder });
      input.dataset.key = key;
      const eye = el("button", {
        class: "btn ghost gray iconbtn", type: "button",
        title: "show / hide", onclick: () => {
          const show = input.type === "password";
          input.type = show ? "text" : "password";
          eye.replaceChildren(el("span", { html: ic(show ? "eye-off" : "eye", 13) }));
        },
      }, [el("span", { html: ic("eye", 13) })]);
      const row = el("div", { class: stack ? "field stack" : "field" });
      row.appendChild(el("label", { text: label }));
      row.appendChild(el("div", { class: "pw-wrap" }, [input, eye]));
      if (hint) row.appendChild(el("div", { class: "hint", text: hint }));
      return row;
    }

    async function saveCreds() {
      const g = (k) => (host.querySelector(`[data-key="${k}"]`) || {}).value || "";
      const c = { host: g("creds_host").trim(), username: g("creds_username").trim(), password: g("creds_password") };
      const secret = g("creds_secret");
      const status = host.querySelector("#creds-status");
      const saveBtn = host.querySelector("#creds-save");
      const need = !c.host || !c.username || !c.password;
      if (need) {
        status.replaceChildren(el("div", { class: "creds-status bad" }, [ic("triangle-alert", 15), el("span", { text: "host, username and password are all required" })]));
        return;
      }
      saveBtn.disabled = true;
      saveBtn.replaceChildren(el("span", { class: "spinner" }), el("span", { text: " PROBING" }));
      const res = await API.testCreds(c).catch(() => null);
      if (!res || !res.ok) {
        saveBtn.replaceChildren(el("span", { html: ic("plug-zap", 14) }), el("span", { text: " TEST & SAVE" }));
        saveBtn.disabled = false;
        status.replaceChildren(el("div", { class: "creds-status bad" }, [ic("octagon-alert", 15), el("span", { text: `${res && res.error ? res.error : "device unreachable — backend did not answer"}` })]));
        return;
      }
      if (secret) c.secret = secret;
      await API.updateCreds(c).catch(() => null);
      status.replaceChildren(el("div", { class: "creds-status ok" }, [ic("badge-check", 15), el("span", { text: `verified ${res.user} @ ${c.host} — device hostname "${res.hostname}" — sealed in fernet vault` })]));
      const set = (id, v) => { const n = host.querySelector("#" + id); if (n) n.textContent = v; };
      set("c-host", c.host);
      set("c-user", c.username);
      set("c-secret", c.secret ? "********" : "unset");
      toast("credentials verified and sealed in the vault", "ok");
    }

    async function saveVpnAccess() {
      const g = (k) => (host.querySelector(`[data-key="${k}"]`) || {}).value || "";
      const address = g("vpn_address").trim();
      const username = g("vpn_username").trim();
      const deviceHost = g("vpn_device_host").trim();
      const deviceUser = g("vpn_device_user").trim();
      let pw = g("vpn_password");
      let devicePw = g("vpn_device_pass");
      const status = host.querySelector("#vpn-status");
      const saveBtn = host.querySelector("#vpn-save");
      if (!address || !username) {
        status.replaceChildren(el("div", { class: "creds-status bad" }, [ic("triangle-alert", 15), el("span", { text: "vpn_address and vpn_username are required" })]));
        return;
      }
      if (pw && pw === (vpn?.password || "")) pw = "";
      if (devicePw && devicePw === (vpn?.device_password || "")) devicePw = "";
      saveBtn.disabled = true;
      saveBtn.replaceChildren(el("span", { class: "spinner" }), el("span", { text: " SEALING" }));
      const ok = await API.saveVpn({
        address, username, password: pw, device_host: deviceHost,
        device_username: deviceUser, device_password: devicePw,
      }).catch(() => null);
      saveBtn.replaceChildren(el("span", { html: ic("save", 14) }), el("span", { text: " SAVE" }));
      saveBtn.disabled = false;
      if (!ok) {
        status.replaceChildren(el("div", { class: "creds-status bad" }, [ic("octagon-alert", 15), el("span", { text: "backend did not answer" })]));
        return;
      }
      status.replaceChildren(el("div", { class: "creds-status ok" }, [ic("badge-check", 15), el("span", { text: `vpn access sealed — ${address}` })]));
      const set = (id, v) => { const n = host.querySelector("#" + id); if (n) n.textContent = v; };
      set("v-address", address);
      set("v-user", username);
      set("v-devhost", deviceHost || "10.10.20.48 (default)");
      set("v-devuser", deviceUser || "developer (default)");
      toast("vpn access saved", "ok");
      await vpnRefresh();
    }

    async function saveResSet(slug) {
      const g = (k) => (host.querySelector(`[data-key="res_${slug}_${k}"]`) || {}).value || "";
      const cur = res[slug] || {};
      let pw = g("pass");
      if (pw && pw === (cur.password || "")) pw = "";
      const r = await API.saveRes(slug, {
        host: g("host").trim(), port: g("port").trim(),
        username: g("user").trim(), password: pw,
      }).catch(() => null);
      toast(r && r.ok ? `companion '${slug}' sealed` : `companion '${slug}' save failed`, r && r.ok ? "ok" : "err");
      return r;
    }

    const VPN_ERR = {
      "client-not-found": "Cisco Secure Client not found — install it first",
      "vpn-credentials-missing": "save vpn_address / vpn_username / vpn_password first",
      "login-rejected": "login rejected — the reservation password may have rotated",
      "endpoint-unreachable": "VPN gateway unreachable — CAT8k-SYNC filters it; try from home",
      "client-busy": "client busy — window closed automatically, retry",
      timeout: "connection attempt timed out",
      "unknown-state": "client returned no usable state — verify the tunnel manually",
      "still-connected": "client reports it is still connected — retry or disconnect manually",
    };
    const vpnErr = (e) => VPN_ERR[e] || String(e || "backend did not answer").replace(/-/g, " ");

    function setVpnLive(st) {
      const set = (id, v) => { const n = host.querySelector("#" + id); if (n) n.textContent = v; };
      set("v-client", st.client ? "found" : "not found");
      const tunnel = host.querySelector("#v-tunnel");
      if (tunnel) {
        tunnel.textContent = st.tunnel ? "UP" : "DOWN";
        tunnel.style.color = st.tunnel ? "var(--green)" : "var(--red)";
      }
      if (st.backend) setBackendLive(st.backend);
    }

    function setBackendLive(b) {
      const set = (id, v) => { const n = host.querySelector("#" + id); if (n) n.textContent = v; };
      set("b-mode", b.mode);
      set("b-source", b.source);
      set("b-host", b.host || "—");
      set("b-tunnel", b.tunnel ? "UP" : "DOWN");
      set("b-vpn-host", b.vpn_host || "—");
      set("b-identity", b.identity || "—");
      const reason = host.querySelector("#b-reason");
      if (reason) {
        if (b.mode === "reservation" && b.reason === "vpn-device-host-missing") {
          reason.textContent = "reservation device host required — fill ROUTER ACCESS above";
          reason.style.color = "var(--red)";
        } else {
          reason.textContent = "ok";
          reason.style.color = "var(--green)";
        }
      }
      host.querySelectorAll("#backend-seg [data-backend]").forEach((btn) => {
        btn.classList.toggle("on", btn.dataset.backend === b.mode);
      });
    }

    async function pickBackend(mode) {
      const res = await API.setBackend(mode).catch(() => null);
      if (res && res.ok) setBackendLive(res.backend);
      toast(res && res.ok ? `backend -> ${res.backend.mode}` : "backend switch failed", res && res.ok ? "ok" : "err");
      await vpnRefresh();
    }

    async function vpnRefresh() {
      const st = await API.vpnStatus().catch(() => null);
      if (st) setVpnLive(st);
      return st;
    }

    async function vpnConnect() {
      const btn = host.querySelector("#vpn-connect");
      const status = host.querySelector("#vpn-status");
      if (!btn || btn.disabled) return;
      btn.disabled = true;
      btn.replaceChildren(el("span", { class: "spinner" }), el("span", { text: " CONNECTING" }));
      const res = await API.vpnConnect().catch(() => null);
      btn.replaceChildren(el("span", { html: ic("wifi", 13) }), el("span", { text: " CONNECT VPN" }));
      btn.disabled = false;
      if (!res || !res.ok) {
        status.replaceChildren(el("div", { class: "creds-status bad" }, [ic("octagon-alert", 15), el("span", { text: vpnErr(res && res.error) })]));
        await vpnRefresh();
        return;
      }
      status.replaceChildren(el("div", { class: "creds-status ok" }, [ic("badge-check", 15), el("span", { text: "tunnel established — device should answer now" })]));
      toast("vpn connected", "ok");
      await vpnRefresh();
    }

    async function vpnDisconnect() {
      const res = await API.vpnDisconnect().catch(() => null);
      const status = host.querySelector("#vpn-status");
      if (!res || !res.ok) {
        if (status) status.replaceChildren(el("div", { class: "creds-status bad" }, [ic("octagon-alert", 15), el("span", { text: vpnErr(res && res.error) })]));
        return;
      }
      if (status) status.replaceChildren(el("div", { class: "creds-status ok" }, [ic("badge-check", 15), el("span", { text: "tunnel disconnected" })]));
      toast("vpn disconnected", "ok");
      await vpnRefresh();
    }

    vpnRefresh();
  }

  return { auth, home, provision, telemetry, models, topology, audit, analytics, profile, ops, opsResult, opsHealth };
})();
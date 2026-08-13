/* app.js — boot + shell: sidebar, topbar, routing, console, task feed. */
"use strict";

const App = (() => {
  const NAV = [
    ["home", "HOME", "gauge", "hub / trends overview"],
    ["provision", "PROVISION", "store", "branch deployment studio"],
    ["telemetry", "TELEMETRY", "radio-tower", "live interface + payloads"],
    ["models", "MODELS", "binary", "netconf yang model explorer"],
    ["ops", "OPS", "wrench", "hardware + config ops toolbox"],
    ["topology", "TOPOLOGY", "network", "fabric radar map"],
    ["audit", "AUDIT", "notebook-text", "immutable operation ledger"],
    ["analytics", "ANALYTICS", "chart-no-axes-column", "series + compliance"],
    ["profile", "PROFILE", "circle-user-round", "operator identity + vault"],
  ];

  let st = null;
  let current = "";
  let navSeq = 0;

  const DEMO = location.search.includes("demo") || location.search.includes("mock");

  async function boot() {
    UI.Console.write("CAT8k-SYNC WEB CORE // " + API.mode.toUpperCase(), "sys");
    await Sprite.load();
    st = await API.getState().catch((e) => {
      console.warn("[boot] state rejected:", e && e.message);
      return null;
    });
    if (!st) {
      renderBridgeDown();
      return;
    }
    wireConsole();
    window.addEventListener("hashchange", () => {
      const h = location.hash.slice(1);
      if (h && h !== current && Views[h]) nav(h);
    });
    if (DEMO) {
      st.mode = st.mode || "provision";
      st.creds = st.creds || { host: "demo-fabric" };
    }
    const forceSetup = location.search.includes("setup");
    if (forceSetup || (!DEMO && (st.mode == null || st.mode === "" || !st.creds || !st.creds.host))) {
      enterAuth();
      return;
    }
    await enter();
    const h = location.hash.slice(1);
    nav(Views[h] ? h : "home");
  }

  /* ---------- console + task bridge ---------- */
  function wireConsole() {
    const dock = document.getElementById("console-dock");
    const reopen = document.getElementById("console-reopen");
    const collapse = document.getElementById("console-collapse");
    const closeBtn = document.getElementById("console-close");
    const syncCollapseIcon = () => {
      if (collapse) {
        collapse.classList.toggle("flipped", dock.classList.contains("collapsed"));
      }
    };
    if (collapse) {
      collapse.addEventListener("click", () => {
        dock.classList.toggle("collapsed");
        syncCollapseIcon();
      });
    }
    if (closeBtn) {
      closeBtn.addEventListener("click", () => {
        dock.classList.add("closed");
        if (reopen) reopen.hidden = false;
      });
    }
    if (reopen) {
      reopen.addEventListener("click", () => {
        dock.classList.remove("closed");
        reopen.hidden = true;
      });
    }
    document.getElementById("console-copy").addEventListener("click", async () => {
      const txt = document.getElementById("console").textContent;
      try { await navigator.clipboard.writeText(txt); UI.toast("terminal feed copied", "ok"); }
      catch (e) { UI.toast("copy denied", "bad"); }
    });
    syncCollapseIcon();
  }

  /* pywebview engine → window.Company.onTask / onResult / onHealth */
  window.Company = {
    onTask: (task) => {
      if (!task) return;
      UI.Console.write(`TASK ${task.id} :: ${task.state}`, task.state === "done" ? "ok" : task.state === "failed" ? "fail" : "warn");
      if (task.state === "done") UI.toast(`task ${task.id} complete`, "ok");
      if (task.state === "failed") UI.toast(`task ${task.id} failed`, "bad");
    },
    onResult: (r) => { if (Views.opsResult) Views.opsResult(r); },
    onHealth: (h) => setHealth(h),
  };

  /* ---------- live fabric health (topbar pill + ops view) ---------- */
  let health = { ok: null, host: "", at: null };
  let downDismissed = false;

  function setHealth(h) {
    if (h && typeof h === "object" && "ok" in h) {
      const wasDown = health.ok === false;
      health = h;
      if (h.ok === false) {
        if (!wasDown && !downDismissed) showUnreachableModal(h);
      } else {
        downDismissed = false;
      }
    }
    renderFabricPill();
    renderSidebarAlert();
    if (current === "ops" && Views.opsHealth) Views.opsHealth(health);
  }

  function showUnreachableModal(h) {
    const m = UI.modal({
      title: "FABRIC UNREACHABLE",
      sub: `destination ${h.host || "?"} did not answer the fabric probe`,
      body: [
        el("div", { class: "fabric-alert" }, [
          el("div", { class: "fabric-alert-ic" }, [UI.ic("octagon-alert", 26, "var(--red)")]),
          el("div", {}, [
            el("p", { text: `The Catalyst device at ${h.host || "unknown"} is not reachable over the management plane.` }),
            el("p", { class: "muted", text: `last probe ${h.at || "unknown"} — CAT8k-SYNC retries every 30s; the sidebar stays red until the device answers.` }),
          ]),
        ]),
      ],
      actions: [el("button", { class: "btn red", text: "DISMISS", onclick: () => m.close() })],
      onClose: () => { downDismissed = true; },
    });
  }

  function renderFabricPill() {
    const p = document.getElementById("fabric-pill");
    if (!p) return;
    p.innerHTML = "";
    p.append(
      el("span", { class: "dot " + (health.ok === true ? "online" : health.ok === false ? "offline" : "") }),
      el("span", {}, [el("b", { text: "FABRIC" }),
        health.ok === true ? " LIVE // " + (health.host || "?") : health.ok === false ? " UNREACHABLE" : " PROBE"]),
    );
  }

  async function probe() {
    try {
      const r = await API.checkHealth();
      if (r && "ok" in r && !r.queued) setHealth(r);
    } catch (e) {
      setHealth({ ok: false, host: "", at: null });
    }
  }

  /* ---------- shell ---------- */
  let probeTimer = null;
  async function enter() {
    document.getElementById("auth").classList.add("hidden");
    const shell = document.getElementById("shell");
    shell.classList.remove("hidden");
    st = await API.getState();
    renderSidebar();
    if (localStorage.getItem("cat8k-rail") === "1") {
      shell.classList.add("rail");
      const btn = document.querySelector(".side-toggle");
      if (btn) btn.title = "expand sidebar";
    }
    renderTopbar();
    setInterval(() => { const c = document.getElementById("clock"); if (c) c.textContent = new Date().toLocaleTimeString(); }, 1000);
    if (!probeTimer) { probeTimer = setInterval(probe, 30000); }
    probe();
  }

  function enterAuth() {
    document.getElementById("shell").classList.add("hidden");
    const auth = document.getElementById("auth");
    auth.classList.remove("hidden");
    const card = document.getElementById("auth-card");
    card.innerHTML = "";
    Views.auth(card);
  }

  /* the desktop bridge never answered — show a real error, never a blank grid */
  function renderBridgeDown() {
    const auth = document.getElementById("auth");
    auth.classList.remove("hidden");
    document.getElementById("shell").classList.add("hidden");
    const card = document.getElementById("auth-card");
    card.innerHTML = "";
    card.append(
      el("div", { class: "auth-brand" }, [
        el("div", { class: "brand-glyph glyph" }, [el("span", { html: UI.ic("octagon-alert", 30, "var(--red)") })]),
        el("h2", { text: "CAT8k-SYNC" }),
        el("div", { class: "sub", text: "ENGINE UNREACHABLE" }),
      ]),
      el("div", { class: "auth-error", text: "the local backend bridge did not respond." +
        " relaunch the desktop app to reconnect — no demo data is shown." }),
      el("div", { class: "auth-error", style: "margin-top:10px", text: "if this persists beyond a relaunch, check `%TEMP%\\webapp-detached.log`" }),
    );
  }

  function renderSidebar() {
    const sb = document.getElementById("sidebar");
    sb.innerHTML = "";
    sb.append(
      el("div", { class: "side-top" }, [
        el("button", { class: "side-toggle", type: "button", title: "collapse sidebar", onclick: toggleRail }, [
          UI.ic("chevron-left", 16),
        ]),
      ]),
      el("div", { class: "brand" }, [
        el("div", { class: "brand-glyph" }, [el("img", { src: "icons/LOGO.png", alt: "CAT8k-SYNC" })]),
        el("div", {}, [
          el("div", { class: "brand-name", text: "CAT8k-SYNC" }),
          el("div", { class: "brand-sub", text: "CONTROL CLOUD" }),
        ]),
      ]),
      el("nav", { class: "nav" }, NAV.map(([id, label]) =>
        el("a", { class: "nav-item", href: "#" + id, title: label, onclick: (e) => { e.preventDefault(); nav(id); } }, [
          el("span", { class: "icon" }, UI.ic(iconFor(id), 17)),
          el("span", { text: label }),
        ]))),
      el("div", { id: "side-alert" }),
      el("div", { class: "side-foot" }, [
        el("div", { class: "side-chip" }, [
          el("span", { class: "cap", text: "LIVE FABRIC" }),
          el("span", { class: "val", text: st?.creds?.host || "—" }),
        ]),
        el("div", { class: "welcome-tag", text: `MODE // ${(st?.mode || "SETUP").toUpperCase()}` }),
      ]),
    );
  }

  function toggleRail() {
    const shell = document.getElementById("shell");
    const on = shell.classList.toggle("rail");
    localStorage.setItem("cat8k-rail", on ? "1" : "0");
    const btn = document.querySelector(".side-toggle");
    if (btn) btn.title = on ? "expand sidebar" : "collapse sidebar";
  }

  /* big red sidebar warning while the destination is unreachable */
  function renderSidebarAlert() {
    const host = document.getElementById("side-alert");
    if (!host) return;
    host.innerHTML = "";
    if (health.ok !== false) return;
    host.append(el("div", { class: "side-alert", role: "alert" }, [
      el("span", { class: "side-alert-ic" }, [UI.ic("octagon-alert", 16, "var(--red)")]),
      el("div", {}, [
        el("b", { text: "FABRIC UNREACHABLE" }),
        el("div", { class: "side-alert-sub", text: (health.host || "no host") + " · probe " + (health.at || "…") }),
      ]),
    ]));
  }

  function iconFor(id) {
    const map = {
      home: "gauge", provision: "store", telemetry: "radio-tower", ops: "wrench", topology: "network",
      audit: "notebook-text", analytics: "chart-no-axes-column", profile: "circle-user-round",
    };
    return map[id] || "circle-dot";
  }

  function renderTopbar() {
    const tb = document.getElementById("topbar");
    tb.innerHTML = "";
    tb.append(
      el("div", { class: "crumb" }, [
        el("span", { class: "num", text: "CAT8k-SYNC//WEB" }),
        el("h1", { id: "crumb-title", text: "MISSION CONTROL" }),
        el("span", { class: "sub", id: "crumb-sub", text: "" }),
      ]),
      el("div", { class: "top-actions" }, [
        el("span", { class: "status-pill", id: "fabric-pill" }),
        el("span", { class: "status-pill" }, [
          el("span", { class: "icon-sm" }, UI.ic("clock-3", 13, "var(--teal)")),
          el("span", { id: "clock", text: new Date().toLocaleTimeString() }),
        ]),
      ]),
    );
    renderFabricPill();
  }

  /* ---------- routing ---------- */
  async function nav(id) {
    const seq = ++navSeq;
    current = id;
    const viewHost = document.getElementById("view-host");
    const slot = el("div", { class: "view-slot" });
    viewHost.innerHTML = "";
    viewHost.appendChild(slot);
    slot.scrollTop = 0;
    document.querySelectorAll(".nav-item").forEach((n) => n.classList.toggle("active", n.getAttribute("href") === "#" + id));

    const meta = NAV.find(([i]) => i === id);
    if (meta) {
      const t = document.getElementById("crumb-title");
      const s = document.getElementById("crumb-sub");
      if (t) t.textContent = meta[1];
      if (s) s.textContent = meta[3];
    }

    const loading = UI.loading(meta ? meta[1] : id, "rendering console…");
    slot.appendChild(loading);
    const t0 = performance.now();

    try {
      await Views[id](slot);
    } catch (e) {
      console.error("[view]", id, e);
      UI.Console.write(`VIEW ${id.toUpperCase()} ERROR :: ${e.message}`, "fail");
      if (seq === navSeq) {
        loading.remove();
        slot.append(el("div", { class: "auth-error", text: "view error: " + e.message }));
      } else {
        slot.remove();
      }
    }
    /* keep the skeleton long enough to not flash on fast views */
    const remain = 260 - (performance.now() - t0);
    const settle = () => {
      if (seq !== navSeq) return;
      loading.remove();
    };
    if (remain > 0) setTimeout(settle, remain);
    else settle();
  }

  function logout() {
    API.logout().then(() => { st = null; enterAuth(); });
  }

  return { boot, enter, enterAuth, nav, logout };
})();

document.addEventListener("DOMContentLoaded", () => App.boot());

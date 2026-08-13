/* ui.js — tiny DOM toolkit: el builder, toasts, tags, modal, console feed. */
"use strict";

const el = (tag, attrs = {}, children = []) => {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "html") node.innerHTML = v;
    else if (k === "text") node.textContent = v;
    else if (k === "style") node.style.cssText = v;
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else if (v != null && v !== false) node.setAttribute(k, v === true ? "" : v);
  }
  const list = (Array.isArray(children) ? children : [children]).flat(Infinity);
  for (const c of list) {
    if (c == null) continue;
    if (c.nodeType) {
      node.append(c);
    } else if (typeof c === "string" && c.includes("<")) {
      const t = document.createElement("template");
      t.innerHTML = c;
      node.append(t.content);
    } else {
      node.append(document.createTextNode(c));
    }
  }
  return node;
};

const UI = (() => {
  /* ---------- icons ---------- */
  const ic = (name, size = 16, color = "currentColor") => Sprite.icon(name, size, color);

  /* ---------- toasts ---------- */
  function toast(msg, kind = "ok", ms = 3200) {
    const host = document.getElementById("toasts");
    const colors = { ok: "var(--teal)", warn: "var(--yellow)", bad: "var(--red)", sys: "var(--green)" };
    const t = el("div", { class: "toast", style: `--tc:${colors[kind] || colors.ok}` }, [
      ic(kind === "ok" ? "check-circle-2" : kind === "bad" ? "octagon-alert" : kind === "warn" ? "triangle-alert" : "cpu", 16),
      el("span", { text: msg }),
    ]);
    host.appendChild(t);
    setTimeout(() => { t.classList.add("out"); setTimeout(() => t.remove(), 320); }, ms);
  }

  /* ---------- tags ---------- */
  function tag(text, kind = "dark", iconName = null) {
    const t = el("span", { class: `tag ${kind}` }, iconName ? [ic(iconName, 12), text] : [text]);
    return t;
  }
  function statusTag(status) {
    const map = {
      up: ["green", "chevron-up-circle"], down: ["red", "chevron-down-circle"],
      pass: ["green", "shield-check"], fail: ["red", "shield-alert"],
      ok: ["green", "check-circle-2"], warn: ["yellow", "triangle-alert"],
      clean: ["green", "sparkles"], drift: ["red", "git-compare-arrows"],
      online: ["green", "wifi"], offline: ["red", "wifi-off"],
      queued: ["yellow", "clock-3"], running: ["yellow", "loader-2"], done: ["green", "check-circle-2"], failed: ["red", "x-circle"],
      yes: ["green", "check"], no: ["red", "x"],
    };
    const [k, i] = map[status] || ["dark", "circle-dot"];
    return tag(status.toUpperCase(), k, i);
  }

  /* ---------- glossary tooltip ---------- */
  const GLOSSARY = {
    "TACACS+": "Terminal Access Controller Access-Control System Plus — AAA protocol; separates authentication, authorization and accounting, encrypts the full packet payload.",
    RADIUS: "Remote Authentication Dial-In User Service — AAA protocol over UDP; encrypts only the shared secret, not the whole body.",
    AAA: "Authentication, Authorization, Accounting — the access-control framework network devices use for every login and command.",
    NTP: "Network Time Protocol — keeps device clocks accurate so timestamps, logs and certificates are trustworthy.",
    NACM: "NETCONF Access Control Model (RFC 6536) — YANG-level RBAC: which user/group may read or write which YANG data nodes over NETCONF/RESTCONF.",
    RESTCONF: "HTTP-based RESTful interface for YANG datastores (RFC 8040) — the API this console talks to.",
    NETCONF: "Network management protocol using XML RPCs over SSH (RFC 6241).",
    SNMP: "Simple Network Management Protocol — v1/v2c use cleartext community strings; v3 adds user authentication and encryption.",
    "SNMPv3": "Simple Network Management Protocol version 3 — authenticated + encrypted monitoring.",
    SSH: "Secure Shell — encrypted remote CLI transport (the only safe way into a device).",
    "HTTP/HTTPS": "Plaintext web management vs TLS-wrapped (encrypted) management plane.",
    MOTD: "Message Of The Day — the banner users see at login; doubles as the legal notice they accept.",
    "SHA-256": "Cryptographic hash function — used here to chain the audit ledger so any tampering is detected.",
    ACL: "Access Control List — allow/deny filters for interfaces or the management plane.",
    PKI: "Public Key Infrastructure — certificates and trust anchors behind SSH/HTTPS identity.",
    Syslog: "Standard logging protocol that ships device events to a remote collector.",
    OSPF: "Open Shortest Path First — link-state routing protocol.",
  };
  function term(text, explanation = null) {
    const exp = explanation || GLOSSARY[text] || GLOSSARY[text.toUpperCase()] || null;
    const t = el("span", { class: "term", tabindex: 0, title: exp || "" });
    t.appendChild(el("span", { text }));
    t.appendChild(el("span", { class: "q", text: exp ? "?" : "·" }));
    if (exp) {
      const tip = el("span", { class: "tip", text: exp });
      t.appendChild(tip);
      const open = () => t.classList.add("open");
      const close = () => t.classList.remove("open");
      t.addEventListener("mouseenter", open);
      t.addEventListener("mouseleave", close);
      t.addEventListener("click", (e) => {
        e.stopPropagation();
        t.classList.toggle("open");
      });
      t.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); t.classList.toggle("open"); }
        if (e.key === "Escape") close();
      });
      document.addEventListener("click", (e) => {
        if (!t.contains(e.target)) close();
      });
    }
    return t;
  }

  /* ---------- loading skeleton (shown while a view fetches) ---------- */
  function loading(label = "VIEW", sub = "fetching live fabric data") {
    const l = el("div", { class: "view-loading" });
    const row = (w) => el("div", { class: "load-line", style: `width:${w}%` });
    const card = el("div", { class: "load-card" }, [
      el("div", { class: "load-head" }, [el("div", { class: "load-tile" }), row(26)]),
      el("div", { class: "load-body" }, [row(88), row(64), row(74)]),
    ]);
    l.appendChild(el("div", { class: "load-status" }, [
      el("span", { class: "load-dot" }),
      el("span", { class: "load-k" }, "LOADING · "),
      el("span", { class: "load-label", text: label }),
      el("span", { class: "load-ellipsis" }),
      el("span", { class: "load-sub", text: sub }),
    ]));
    l.append(
      el("div", { class: "load-hero" }, [
        el("div", { class: "load-title" }, [row(30), row(52)]),
        el("div", { class: "load-big" }),
      ]),
      el("div", { class: "load-grid" }, [card.cloneNode(true), card.cloneNode(true)]),
      el("div", { class: "load-card wide" }, [
        el("div", { class: "load-head" }, [row(20)]),
        el("div", { class: "load-table" }, [row(96), row(92), row(95), row(93), row(94)]),
      ]),
    );
    return l;
  }

  /* ---------- confirmation modal (gates destructive writes) ---------- */
  function confirm({ title, sub, body = null, cta = "PROCEED", danger = false,
                     requireValue = null, valuePlaceholder = "", allowEmpty = false,
                     onCancel = null }) {
    return new Promise((resolve) => {
      let settled = false;
      const finish = (v) => {
        if (settled) return;
        settled = true;
        document.removeEventListener("keydown", esc);
        resolve(v);
      };
      const esc = (e) => { if (e.key === "Escape") finish(false); };
      document.addEventListener("keydown", esc);

      const box = el("label", { class: "confirm-check" }, [
        el("input", { type: "checkbox" }),
        el("span", { text: requireValue
          ? `I understand — I will provide a value and accept the consequences`
          : "I understand the warning above and want to proceed anyway" }),
      ]);
      const check = box.querySelector("input");
      let valueEl = null;
      const bodyParts = [];
      if (body) bodyParts.push(...([].concat(body)));
      bodyParts.push(box);
      if (requireValue) {
        valueEl = el("input", { type: "text", placeholder: valuePlaceholder || requireValue });
        valueEl.addEventListener("input", arm);
        bodyParts.push(el("div", { class: "confirm-value" }, [
          allowEmpty
            ? el("div", { class: "confirm-value-label", text: requireValue + " — leave empty for the default" })
            : null,
          valueEl,
        ]));
      }
      const proceed = el("button", { class: "btn " + (danger ? "danger" : "primary"), text: cta, disabled: true });
      const cancel = el("button", { class: "btn ghost gray", text: "CANCEL" });
      function arm() {
        const ok = check.checked && (!valueEl || allowEmpty || valueEl.value.trim().length > 0);
        proceed.disabled = !ok;
        proceed.classList.toggle("dim", !ok);
      }
      check.addEventListener("change", arm);
      proceed.addEventListener("click", () => {
        finish(valueEl ? valueEl.value.trim() : true);
        m.close();
      });
      cancel.addEventListener("click", () => {
        if (onCancel) onCancel();
        finish(false);
        m.close();
      });
      const m = modal({ title, sub, body: bodyParts, actions: [cancel, proceed], wide: true });
      const origClose = m.close;
      m.close = () => { origClose(); finish(false); };
    });
  }

  /* ---------- modal ---------- */
  function modal({ title, sub, body, actions = null, wide = false, onClose = null }) {
    const overlay = el("div", { class: "overlay" });
    const m = el("div", { class: "modal" + (wide ? " wide" : "") });
    const head = el("div", { class: "modal-head" }, [
      el("div", {}, [
        el("h3", { text: title }),
        sub ? el("div", { class: "sub", text: sub }) : null,
      ]),
      el("span", { class: "spacer" }),
      el("button", {
        class: "btn ghost gray", text: "ESC",
        onclick: () => close(),
      }, [ic("x", 13)]),
    ]);
    m.append(head, el("div", { class: "modal-body" }, body));
    if (actions) m.append(el("div", { class: "modal-body", style: "padding-top:0" }, actions));
    overlay.append(m);
    document.body.appendChild(overlay);
    const close = () => {
      overlay.remove();
      document.removeEventListener("keydown", kd);
      if (onClose) onClose();
    };
    const kd = (e) => { if (e.key === "Escape") close(); };
    document.addEventListener("keydown", kd);
    return { overlay, m, close };
  }

  /* ---------- console feed ---------- */
  const Console = (() => {
    let c = 0;
    const out = () => document.getElementById("console");
    function write(line, level = "info") {
      const o = out();
      if (!o) return;
      c++;
      const div = el("span", { class: `l ${level}`, text: line });
      o.appendChild(div);
      o.scrollTop = o.scrollHeight;
      while (o.children.length > 400) o.removeChild(o.firstChild);
      const hint = document.getElementById("console-hint");
      if (hint) hint.textContent = `${c} events`;
    }
    return { write, count: () => c };
  })();

  /* ---------- bars (mini sparkline) ---------- */
  function bars(values, accent = "var(--teal)") {
    const host = el("div", { class: "bars", style: `--accent:${accent}` });
    const max = Math.max(...values, 1);
    for (const v of values) {
      const h = Math.round((v / max) * 100);
      host.appendChild(el("div", { class: "bar", style: `height:${h}%` }));
    }
    return host;
  }

  /* ---------- field builder ---------- */
  function field({ key, label, value = "", type = "text", placeholder = "", hint = null, required = false, readonly = false, options = null }) {
    const row = el("div", { class: "field" });
    row.appendChild(el("label", { text: label }));
    let input;
    if (options) {
      input = el("select", {}, options.map((o) =>
        typeof o === "object" ? el("option", { value: o.v, text: o.t }) : el("option", { value: o, text: o })));
      input.value = value;
    } else {
      input = el("input", { type, placeholder, value, readonly, required });
    }
    input.dataset.key = key;
    row.appendChild(input);
    if (hint) row.appendChild(el("div", { class: "hint", text: hint }));
    return row;
  }

  return { ic, toast, tag, statusTag, modal, confirm, term, GLOSSARY, loading, Console, bars, field };
})();

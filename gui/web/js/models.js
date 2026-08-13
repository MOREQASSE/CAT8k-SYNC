/* models.js — NETCONF model explorer helpers.
   Turns raw YANG schema text and raw XML <get> replies into real UI
   component trees, with a PROFILE / TREE / RAW toggle (raw stays available). */
"use strict";

const Models = (() => {
  const chip = (text, cls) => el("span", { class: "mdl-chip" + (cls ? " " + cls : ""), text });
  const ic = (name, size = 15, color = "currentColor") => Sprite.icon(name, size, color);
  const icSpan = (name, cls = "", size = 15, color = "var(--muted)") =>
    el("span", { class: "mdl-ic " + cls, html: ic(name, size, color) });

  /* ============================= YANG side ============================= */

  function tokenize(src) {
    const toks = [];
    let i = 0;
    const n = src.length;
    const isWord = (c) => /[A-Za-z0-9_\-.:/+=%@*?]/.test(c);
    while (i < n) {
      const c = src[i];
      if (c === '"' || c === "'") {
        const q = c;
        let j = i + 1;
        let s = "";
        while (j < n && src[j] !== q) { s += src[j]; j++; }
        toks.push({ t: "str", v: s });
        i = j + 1;
        continue;
      }
      if (c === "/" && src[i + 1] === "/") {
        while (i < n && src[i] !== "\n") i++;
        continue;
      }
      if (c === "/" && src[i + 1] === "*") {
        i += 2;
        while (i < n && !(src[i] === "*" && src[i + 1] === "/")) i++;
        i += 2;
        continue;
      }
      if (c === "{") { toks.push({ t: "{", v: "{" }); i++; continue; }
      if (c === "}") { toks.push({ t: "}", v: "}" }); i++; continue; }
      if (c === ";") { toks.push({ t: ";", v: ";" }); i++; continue; }
      if (/\s/.test(c)) { i++; continue; }
      if (isWord(c)) {
        let j = i;
        let w = "";
        while (j < n && isWord(src[j])) { w += src[j]; j++; }
        toks.push({ t: "w", v: w });
        i = j;
        continue;
      }
      i++;
    }
    return toks;
  }

  function parseStatements(toks, pos) {
    const stmts = [];
    while (pos < toks.length && toks[pos].t !== "}") {
      const tok = toks[pos];
      if (tok.t !== "w") { pos++; continue; }
      const kw = tok.v;
      pos++;
      const args = [];
      const children = [];
      while (pos < toks.length && toks[pos].t !== ";" && toks[pos].t !== "{" && toks[pos].t !== "}") {
        args.push(toks[pos].v);
        pos++;
      }
      if (toks[pos] && toks[pos].t === "{") {
        pos++;
        const kids = parseStatements(toks, pos);
        pos = kids.pos;
        children.push(...kids.stmts);
        if (toks[pos] && toks[pos].t === "}") pos++;
      } else if (toks[pos] && toks[pos].t === ";") {
        pos++;
      }
      stmts.push({ kw, args, children });
    }
    return { stmts, pos };
  }

  const stmt = (s, kw) => s.kw === kw;
  const stmtVal = (s, kw) => {
    const hit = s.children.find((c) => c.kw === kw);
    return hit ? hit.args[0] : "";
  };
  const has = (s, kw) => s.children.some((c) => c.kw === kw);
  const isExt = (kw) => kw.includes(":");

  function countKinds(stmts) {
    const counts = {};
    for (const s of stmts) {
      counts[s.kw] = (counts[s.kw] || 0) + 1;
      for (const c of s.children) {
        if (c.kw && !isExt(c.kw)) {
          counts[c.kw] = (counts[c.kw] || 0) + 1;
          if (c.children) {
            for (const d of c.children) {
              if (d.kw && !isExt(d.kw)) counts[d.kw] = (counts[d.kw] || 0) + 1;
            }
          }
        }
      }
    }
    return counts;
  }

  const KIND_ICON = { container: "box", list: "list", leaf: "dot", "leaf-list": "rows-3", rpc: "zap", notification: "bell", grouping: "puzzle", typedef: "hash", feature: "flag", augment: "git-merge", uses: "link-2" };

  function leafType(s) {
    const tstmt = s.children.find((c) => c.kw === "type");
    const t = tstmt ? tstmt.args[0] : "string";
    if (t === "leafref") {
      const p = (tstmt.children.find((c) => c.kw === "path") || {}).args || [];
      return "leafref " + (p[0] || "");
    }
    if (t === "enumeration") {
      const enums = tstmt.children.filter((c) => c.kw === "enum").map((c) => c.args[0]);
      return enums.length ? `enumeration(${enums.join(",")})` : "enumeration";
    }
    return t;
  }

  function rowBadges(s) {
    const b = [];
    if (stmtVal(s, "config") === "false") b.push(chip("ro", "mdl-ro"));
    if (stmtVal(s, "mandatory") === "true") b.push(chip("req"));
    if (has(s, "presence")) b.push(chip("presence"));
    return b;
  }

  function rowTitle(s) {
    const d = stmtVal(s, "description");
    if (!d) return "";
    const one = d.split("\n")[0].trim();
    return one.length > 160 ? one.slice(0, 160) + "…" : one;
  }

  function dataRows(stmts, depth) {
    const out = [];
    for (const s of stmts) {
      const kw = s.kw;
      const isData = ["container", "list", "leaf", "leaf-list"].includes(kw);
      const isRef = ["grouping", "typedef", "feature", "rpc", "notification", "augment", "uses"].includes(kw) || isExt(kw);
      if (!isData && !isRef) continue;
      const collapsible = (isData || ["augment", "grouping", "typedef"].includes(kw)) && s.children.some((c) => ["container", "list", "leaf", "leaf-list"].includes(c.kw));
      const name = el("span", { class: "mdl-name mono", text: s.args[0] || (isExt(kw) ? kw : "?") });
      let mid = null;
      if (kw === "leaf" || kw === "leaf-list") {
        mid = el("span", { class: "mdl-type", text: ": " + leafType(s) });
      } else if (kw === "list") {
        const k = stmtVal(s, "key");
        mid = k ? el("span", { class: "mdl-type", text: "[key " + k + "]" }) : el("span", { class: "mdl-type", text: "[]" });
      } else if (kw === "augment") {
        mid = el("span", { class: "mdl-type", text: "→ " + (s.args[0] || "") });
      } else if (kw === "uses" || kw === "grouping" || kw === "typedef") {
        mid = el("span", { class: "mdl-type", text: s.args[0] ? "→ " + s.args[0] : "" });
      }
      const row = el("div", { class: "mdl-row", title: rowTitle(s) });
      row.appendChild(el("span", { class: "mdl-caret" + (collapsible ? "" : " empty"), text: collapsible ? "▾" : "·" }));
      row.appendChild(el("span", { class: "mdl-kw", text: kw }));
      row.appendChild(name);
      if (mid) row.appendChild(mid);
      for (const b of rowBadges(s)) row.appendChild(b);
      out.push(row);

      if (collapsible) {
        const kids = dataRows(s.children, depth + 1);
        const body = el("div", { class: "mdl-children" });
        body.append(...kids);
        row.appendChild(el("span", { class: "mdl-badge", text: String(kids.length) }));
        row.appendChild(body);
        row.classList.add("has-kids");
        row.addEventListener("click", () => {
          row.classList.toggle("closed");
          body.classList.toggle("closed");
        });
      }
    }
    return out;
  }

  function yangTree(text) {
    const stmts = parseStatements(tokenize(String(text || "")), 0).stmts;
    const head = stmts.find((s) => s.kw === "module") || {};
    const header = el("div", { class: "mdl-meta" });
    header.append(
      chip(head.args[0] || "?", "mdl-name-chip"),
      chip(stmtVal(head, "namespace") || "no namespace"),
      chip("prefix " + (stmtVal(head, "prefix") || "?")),
      chip("yang " + (stmtVal(head, "yang-version") || "1")),
    );
    const revs = head.children.filter((c) => c.kw === "revision");
    const imports = head.children.filter((c) => c.kw === "import");
    if (revs.length) header.append(chip(revs.length + " revision" + (revs.length > 1 ? "s" : "") + " · latest " + revs[0].args[0]));
    if (imports.length) header.append(chip("imports " + imports.length));
    const counts = countKinds(head.children || []);
    const label = (k) => (counts[k] || 0) + " " + k + (counts[k] === 1 ? "" : "s");
    const meta = el("div", { class: "mdl-meta", style: "margin-top:6px" });
    const parts = ["container", "leaf", "list", "leaf-list", "grouping", "typedef", "feature", "rpc", "augment"]
      .filter((k) => counts[k])
      .map(label);
    if (parts.length) meta.append(chip(parts.join(" · "), "mdl-counts"));

    const rows = dataRows(head.children || [], 0);
    const wrap = el("div", { class: "mdl-tree" });
    wrap.append(header, meta);
    if (rows.length) {
      const body = el("div", { style: "margin-top:4px" });
      body.append(...rows);
      wrap.append(body);
    } else {
      wrap.append(el("div", { class: "muted small", style: "padding:8px", text: "no data nodes found in this module — likely an RPC/notification-only or submodule schema" }));
    }
    return { node: wrap, meta, rows };
  }

  /* ============================== XML side ============================== */

  function xmlStats(el_, acc) {
    acc.elements++;
    let leaf = true;
    for (const child of el_.childNodes) {
      if (child.nodeType === 1) { leaf = false; xmlStats(child, acc); }
    }
    if (leaf) acc.leaves++;
    return acc;
  }

  function elAttrs(el_) {
    const attrs = [];
    const ns = [];
    for (const a of el_.attributes || []) {
      if (a.name.startsWith("xmlns")) ns.push({ name: a.name, value: a.value });
      else attrs.push({ name: a.name, value: a.value });
    }
    return { attrs, ns };
  }

  function elText(el_) {
    let t = "";
    for (const child of el_.childNodes) {
      if (child.nodeType === 3 && child.textContent.trim()) t += child.textContent.trim();
    }
    return t;
  }

  function renderXmlRow(el_, depth) {
    const hasKids = el_.children && el_.children.length > 0;
    const { attrs, ns } = elAttrs(el_);
    const isLeaf = !hasKids && !attrs.length && !ns.length;
    const name = el("span", { class: "mdl-name mono", text: el_.tagName });
    const row = el("div", {
      class: "mdl-row" + (isLeaf ? "" : " has-kids"),
      title: ns.map((x) => `${x.name} → ${x.value}`).join("  ") || undefined,
    });
    row.appendChild(el("span", { class: "mdl-caret" + (hasKids ? "" : " empty"), text: hasKids ? "▾" : "·" }));
    row.appendChild(name);
    for (const a of attrs) {
      row.appendChild(el("span", { class: "mdl-att mono", text: `${a.name}="${a.value}"` }));
    }
    if (isLeaf) {
      const v = elText(el_);
      if (v) row.appendChild(el("span", { class: "mdl-val mono", text: v }));
      else row.appendChild(el("span", { class: "mdl-kw", text: "∅" }));
    }
    if (hasKids) {
      row.appendChild(el("span", { class: "mdl-badge", text: String(el_.children.length) }));
      const body = el("div", { class: "mdl-children" });
      for (const child of el_.children) body.appendChild(renderXmlRow(child, depth + 1));
      row.appendChild(body);
      row.classList.add("has-kids");
      row.addEventListener("click", () => {
        row.classList.toggle("closed");
        body.classList.toggle("closed");
      });
    }
    return row;
  }

  function xmlTree(xml) {
    const doc = new DOMParser().parseFromString(String(xml || ""), "application/xml");
    const err = doc.querySelector("parsererror");
    if (err) {
      return { node: el("div", { class: "drift-err", text: "XML parse error — raw view still available" }), meta: null };
    }
    const root = doc.documentElement;
    const stats = xmlStats(root, { elements: 0, leaves: 0 });
    const meta = el("div", { class: "mdl-meta", style: "margin-top:6px" });
    meta.append(
      chip(`${stats.elements} elements`),
      chip(`${stats.leaves} leaves`),
      chip("depth " + (() => { let d = 0, cur = root; while (cur && cur.children.length) { d++; cur = cur.children[0]; } return d; })()),
    );
    const wrap = el("div", { class: "mdl-tree" });
    wrap.append(el("div", { class: "mdl-meta" }, [chip("ROOT", "mdl-name-chip"), chip(root.tagName)]), meta);
    const body = el("div", { style: "margin-top:4px" });
    for (const child of root.children) body.appendChild(renderXmlRow(child, 0));
    wrap.append(body);
    return { node: wrap, meta };
  }

  /* ========================= card-based rendering ========================= */

  /* module family buckets (derived from the advertised module name) */
  const FAMILY = {
    iosxe: { label: "IOS-XE", cls: "f-iosxe" },
    openconfig: { label: "OPENCONFIG", cls: "f-openconfig" },
    ietf: { label: "IETF", cls: "f-ietf" },
    mib: { label: "MIB", cls: "f-mib" },
    other: { label: "OTHER", cls: "f-other" },
  };

  function familyOf(name) {
    if (/^Cisco-IOS-XE-/i.test(name)) return "iosxe";
    if (/^openconfig-/i.test(name)) return "openconfig";
    if (/^(ietf|iana|mpls|snmp|entity|disman|ip|ospf|atm|diffserv|policy)/i.test(name)) return "ietf";
    if (/-mib/i.test(name)) return "mib";
    return "other";
  }
  const familyTag = (name) => {
    const f = FAMILY[familyOf(name)];
    return chip(f.label, "mdl-tag " + f.cls);
  };
  const FAMILY_ICON = { iosxe: "server-cog", openconfig: "network", ietf: "layers", mib: "database", other: "puzzle" };

  const separator = () => el("span", { class: "mdl-separator" });
  const stat = (value, label) => el("div", { class: "mdl-stat" }, [
    el("span", { class: "mdl-stat-val mono", text: value }),
    el("span", { class: "muted small", text: label }),
  ]);

  function moduleCard(mod, onSelect, selected) {
    const card = el("button", {
      class: "mdl-mod-card" + (selected ? " on" : ""),
      title: `${mod.name} @ ${mod.revision} — ${FAMILY[familyOf(mod.name)].label}`,
      onclick: () => onSelect(mod),
    }, [
      el("span", { class: "mdl-mod-top" }, [familyTag(mod.name)]),
      el("span", { class: "mdl-mod-name mono", text: mod.name }),
      el("span", { class: "spacer" }),
      el("span", { class: "muted mono small", text: String(mod.revision || "").slice(0, 10) }),
    ]);
    return card;
  }

  /* -------- YANG schema -> profile / inventory / structure cards -------- */

  const fieldRow = (label, value) => el("div", { class: "mdl-frow" }, [
    el("span", { class: "mdl-fk", text: label }),
    el("span", { class: "mdl-fv mono", text: value || "—" }),
  ]);

  function structureNodes(stmts) {
    const out = [];
    for (const s of stmts) {
      if (["container", "list", "augment"].includes(s.kw)) {
        const counts = { leaf: 0, "leaf-list": 0, list: 0, container: 0 };
        for (const c of s.children) if (counts[c.kw] !== undefined) counts[c.kw]++;
        if (s.kw === "container" && counts.leaf + counts["leaf-list"] + counts.list + counts.container === 0) continue;
        out.push({ kw: s.kw, name: s.args[0] || "", children: s.children, counts, key: stmtVal(s, "key") });
      } else if (s.kw === "leaf" || s.kw === "leaf-list") {
        out.push({ kw: s.kw, name: s.args[0] || "", type: leafType(s), children: s.children });
      }
    }
    return out;
  }

  function parseXml(xml) {
    const doc = new DOMParser().parseFromString(String(xml || ""), "application/xml");
    if (doc.querySelector("parsererror")) return null;
    return doc.documentElement;
  }

  function leafChildren(el_) {
    const leaves = [];
    for (const child of el_.children) {
      if (!child.children || !child.children.length) leaves.push({ tag: child.tagName, value: elText(child) });
    }
    return leaves;
  }

  /* -- social-media profile card for a YANG module ---------------------- */
  function yangProfileCard(head, stats) {
    const kids = head.children || [];
    const name = head.args[0] || "?";
    const fkey = familyOf(name);
    const fam = FAMILY[fkey];
    const prefix = stmtVal(head, "prefix") || name;
    const ns = stmtVal(head, "namespace");
    const yangVer = stmtVal(head, "yang-version") || "1";
    const revs = kids.filter((c) => c.kw === "revision");
    const latest = revs[0] ? revs[0].args[0] : "—";
    const imports = kids.filter((c) => c.kw === "import");
    const features = kids.filter((c) => c.kw === "feature");
    const desc = stmtVal(head, "description");
    const org = stmtVal(head, "organization");
    const bioLine = (desc || "").split("\n")[0].trim();

    const statTiles = [
      ["containers", stats.container || 0, "box"],
      ["lists", stats.list || 0, "list"],
      ["leafs", (stats.leaf || 0) + (stats["leaf-list"] || 0), "circle-dot"],
      ["groupings", stats.grouping || 0, "puzzle"],
      ["rpcs", stats.rpc || 0, "zap"],
      ["imports", imports.length, "git-merge"],
    ].filter(([, v]) => v > 0);

    const tileColor = { iosxe: "var(--green)", openconfig: "var(--blue)", ietf: "var(--teal)", mib: "var(--yellow)", other: "var(--muted)" }[fkey];
    const tiles = statTiles.length
      ? el("div", { class: "mdl-prof-tiles" }, statTiles.map(([lbl, v, icon]) =>
          el("div", { class: "mdl-prof-tile" }, [
            icSpan(icon, "", 15, tileColor),
            el("span", { class: "mdl-prof-tile-v mono", text: String(v) }),
            el("span", { class: "mdl-prof-tile-l", text: lbl }),
          ])))
      : null;

    const prof = el("div", { class: "mdl-card mdl-prof" });
    prof.append(
      el("div", { class: "mdl-prof-cover " + fam.cls }),
      el("div", { class: "mdl-prof-body" }, [
        el("div", { class: "mdl-prof-id" }, [
          el("span", { class: "mdl-prof-avatar " + fam.cls, html: ic(FAMILY_ICON[fkey], 24, "rgba(255,255,255,.92)") }),
          el("div", { class: "mdl-prof-names" }, [
            el("div", { class: "mdl-prof-name mono" }, [
              el("span", { text: name }),
              el("span", { class: "mdl-prof-verified", title: "module identity confirmed", html: ic("badge-check", 14, "var(--teal)") }),
            ]),
            el("div", { class: "mdl-prof-handle mono" }, [
              el("span", { html: ic("at-sign", 12, "var(--muted)") }),
              el("span", { text: prefix }),
              el("span", { class: "mdl-prof-dot", text: "·" }),
              el("span", { class: "mdl-prof-ns", text: ns, title: ns }),
            ]),
          ]),
          el("span", { class: "spacer" }),
          familyTag(name),
        ]),
        separator(),
        bioLine
          ? el("div", { class: "mdl-prof-bio" }, [
              icSpan("file-text", "", 15, "var(--green)"),
              el("span", { class: "mdl-prof-bio-t", text: bioLine.slice(0, 180) + (bioLine.length > 180 ? "…" : ""), title: desc || "" }),
            ])
          : el("div", { class: "mdl-prof-bio muted" }, [icSpan("file-text", "", 15, "var(--muted)"), el("span", { text: "no description shipped in this module" })]),
        separator(),
        tiles,
        el("div", { class: "mdl-prof-meta" }, [
          stat(yangVer, "yang version"),
          stat(revs.length, "revisions"),
          stat(latest, "latest rev"),
          stat(org ? "yes" : "—", "vendor"),
        ]),
        el("div", { class: "mdl-prof-chips" }, [
          chip("prefix " + prefix, "mdl-inv"),
          chip("yang " + yangVer, "mdl-inv"),
          chip(revs.length + " revision" + (revs.length === 1 ? "" : "s"), "mdl-inv"),
          chip(features.length + " feature" + (features.length === 1 ? "" : "s"), "mdl-inv"),
        ]),
      ]),
    );
    return prof;
  }

  /* -- skeleton that mirrors the profile/inventory/structure cards -------- */
  function schemaSkeleton(statusText) {
    const s = (cls, style) => el("div", { class: "ske " + cls, ...(style ? { style } : {}) });
    const wrap = el("div", { class: "mdl-cards-stack mdl-ske" });

    const prof = el("div", { class: "mdl-card mdl-prof" });
    prof.append(
      s("ske-cover"),
      el("div", { class: "mdl-prof-body" }, [
        el("div", { class: "mdl-prof-id" }, [
          s("ske-avatar"),
          el("div", { class: "mdl-prof-names ske-grow" }, [
            s("ske-line", "width:46%"),
            s("ske-line", "width:64%"),
            s("ske-chip" ),
          ]),
          el("span", { class: "spacer" }),
          s("ske-tag"),
        ]),
        el("span", { class: "mdl-separator ske-sep" }),
        el("div", { class: "mdl-prof-bio" }, [s("ske-line", "width:100%;height:13px")]),
        el("span", { class: "mdl-separator ske-sep" }),
        el("div", { class: "mdl-prof-tiles" }, [0, 1, 2, 3].map(() => s("ske-tile"))),
        el("div", { class: "mdl-prof-meta" }, [0, 1, 2, 3].map(() => s("ske-stat"))),
        el("div", { class: "mdl-prof-chips" }, [0, 1, 2, 3].map(() => s("ske-chip"))),
      ]),
    );
    wrap.append(prof);

    const inv = el("div", { class: "mdl-card" }, [
      el("div", { class: "mdl-chead" }, [s("ske-chip"), el("span", { class: "spacer" }), s("ske-chip")]),
      el("div", { class: "mdl-cbody" }, [
        el("div", { class: "mdl-cc" }, [0, 1, 2, 3, 4, 5].map(() => s("ske-chip"))),
      ]),
    ]);
    wrap.append(inv);

    const st = el("div", { class: "mdl-card" }, [
      el("div", { class: "mdl-chead" }, [s("ske-chip"), el("span", { class: "spacer" }), s("ske-chip")]),
      el("div", { class: "mdl-cbody" }, [
        [0, 1, 2].map(() => el("div", { class: "mdl-struct-card" }, [
          s("ske-line", "width:64px"),
          s("ske-line", "width:120px"),
          s("ske-chip"),
          s("ske-chip"),
          s("ske-chip"),
        ])),
      ]),
    ]);
    wrap.append(st);

    if (statusText) {
      wrap.insertBefore(el("div", { class: "mdl-ske-status" }, [
        el("span", { class: "load-dot" }),
        el("span", { class: "load-k", text: "FETCHING SCHEMA · " }),
        el("span", { class: "muted mono small", text: statusText }),
      ]), wrap.firstChild);
    }
    return wrap;
  }

  function yangCards(text) {
    const stmts = parseStatements(tokenize(String(text || "")), 0).stmts;
    const head = stmts.find((s) => s.kw === "module") || {};
    const kids = head.children || [];
    const counts = countKinds(kids);
    const wrap = el("div", { class: "mdl-cards-stack" });

    /* --- profile card (social media style) --- */
    wrap.append(yangProfileCard(head, counts));

    /* --- inventory card --- */
    const INV_LABEL = {
      container: "Containers", list: "Lists", leaf: "Leafs", "leaf-list": "Leaf-Lists",
      grouping: "Groupings", typedef: "Typedefs", rpc: "RPCs", notification: "Notifications",
      augment: "Augments", uses: "Uses",
    };
    const inv = Object.keys(INV_LABEL).filter((k) => counts[k]).map((k) => `${INV_LABEL[k]} ${counts[k]}`);
    const invCard = el("div", { class: "mdl-card" });
    invCard.append(
      el("div", { class: "mdl-chead" }, [
        chip("INVENTORY", "mdl-name-chip"),
        el("span", { class: "spacer" }),
        chip((counts.leaf || 0) + " leaf values", "mdl-counts"),
      ]),
      el("div", { class: "mdl-cbody" }, [
        el("div", { class: "mdl-cc" }, inv.length
          ? inv.map((i) => chip(i, "mdl-inv"))
          : [el("span", { class: "muted small", text: "no data nodes in this module — RPC/notification-only or submodule" })]),
      ]),
    );
    wrap.append(invCard);

    /* --- structure cards --- */
    const nodes = structureNodes(kids);
    const struct = el("div", { class: "mdl-card" });
    struct.append(
      el("div", { class: "mdl-chead" }, [
        chip("STRUCTURE", "mdl-name-chip"),
        el("span", { class: "spacer" }),
        chip(nodes.length + " top-level node" + (nodes.length === 1 ? "" : "s"), "mdl-counts"),
      ]),
      el("div", { class: "mdl-cbody mdl-struct" }, nodes.map((s) => {
        const headEl = el("div", { class: "mdl-crow" }, [
          el("span", { class: "mdl-kw", text: s.kw }),
          el("span", { class: "mdl-name mono", text: s.name }),
        ]);
        const metaRow = el("div", { class: "mdl-crow", style: "gap:4px;flex-wrap:wrap" }, []);
        if (s.kw === "list" && s.key) metaRow.append(chip("[key " + s.key + "]", "mdl-inv"));
        if (s.kw === "augment") metaRow.append(chip("→ " + (s.name || ""), "mdl-inv"));
        if (s.kw === "leaf" || s.kw === "leaf-list") {
          metaRow.append(chip(": " + s.type, "mdl-inv"));
        } else {
          for (const [k, label] of [["leaf", "leaves"], ["leaf-list", "leaf-lists"], ["list", "lists"], ["container", "containers"]]) {
            if (s.counts[k]) metaRow.append(chip(`${s.counts[k]} ${label}`, "mdl-inv"));
          }
        }
        const desc = stmtVal(s, "description") || (s.children && s.children.find((c) => c.kw === "description")?.args[0]);
        if (desc) metaRow.title = desc.split("\n")[0].slice(0, 160);
        return el("div", { class: "mdl-struct-card", title: metaRow.title }, [headEl, metaRow]);
      })),
    );
    wrap.append(struct);
    return { node: wrap };
  }

  /* -------- XML -> summary strip + entity cards -------- */

  function xmlCards(xml) {
    const wrap = el("div", { class: "mdl-cards-stack" });
    const parsed = parseXml(xml);
    if (!parsed) {
      return { node: el("div", { class: "drift-err", text: "XML parse error — raw view still available" }) };
    }
    const kids = [...(parsed.children || [])];
    if (kids.length) {
      const stats = xmlStats(parsed, { elements: 0, leaves: 0 });
      let depth = 0, cur = parsed;
      while (cur && cur.children && cur.children.length) { depth++; cur = cur.children[0]; }
      const sum = el("div", { class: "mdl-card mdl-sum" });
      sum.append(
        chip(stats.elements + " elements"),
        chip(stats.leaves + " leaves"),
        chip("depth " + depth),
        el("span", { class: "spacer" }),
        chip(String(xml || "").length.toLocaleString() + " chars", "mdl-counts"),
      );
      wrap.append(sum);
    }

    /* --- pattern detection: repeated leaf list -> chip cloud --- */
    const firstTag = kids[0] && kids[0].tagName;
    const allSameTag = kids.length > 1 && kids.every((k) => k.tagName === firstTag);
    const allLeaf = kids.every((k) => !k.children || !k.children.length);
    if (allSameTag && allLeaf) {
      const cloud = el("div", { class: "mdl-card" });
      cloud.append(
        el("div", { class: "mdl-chead" }, [
          chip(firstTag.toUpperCase(), "mdl-name-chip"),
          el("span", { class: "spacer" }),
          chip(kids.length + " values", "mdl-counts"),
        ]),
        el("div", { class: "mdl-cbody" }, [
          el("div", { class: "mdl-cc" }, kids.map((k) => chip(elText(k) || "∅", "mdl-inv"))),
        ]),
      );
      wrap.append(cloud);
      return { node: wrap };
    }

    /* --- entity cards --- */
    for (const el_ of kids) {
      const leaves = leafChildren(el_);
      const nameLeaf = leaves.find((l) => ["name", "id", "index"].includes(l.tag.toLowerCase()));
      const stLeaf = leaves.find((l) => ["enabled", "status", "oper-status", "link-state", "admin-status"].includes(l.tag.toLowerCase()));
      const card = el("div", { class: "mdl-card mdl-entity" });
      const chead = el("div", { class: "mdl-chead" });
      if (stLeaf) {
        chead.appendChild(el("span", {
          class: "mdl-status " + (String(stLeaf.value).toLowerCase() === "true" ? "up" : "down"),
          title: `${stLeaf.tag} = ${stLeaf.value}`,
        }));
      }
      chead.append(
        el("span", { class: "mdl-kw", text: el_.tagName }),
        el("span", { class: "mdl-name mono", text: nameLeaf ? nameLeaf.value : "—", style: "overflow:hidden;text-overflow:ellipsis" }),
        el("span", { class: "spacer" }),
        chip((el_.children ? el_.children.length : 0) + " fields", "mdl-counts"),
      );
      card.append(chead);
      card.append(el("div", { class: "mdl-cbody mdl-fields" }, leaves.map((l) => fieldRow(l.tag, l.value))));
      if (el_.children && el_.children.length) {
        const nested = [...new Set([...el_.children].filter((c) => c.children && c.children.length).map((c) => c.tagName))];
        if (nested.length) {
          card.append(el("div", { class: "mdl-crow", style: "gap:4px;padding:0 12px 10px;flex-wrap:wrap" },
            nested.slice(0, 8).map((t) => chip(t + " {}", "mdl-inv"))));
        }
      }
      const ns = el_.namespaceURI || (el_.attributes && [...el_.attributes].find((a) => a.name === "xmlns")?.value);
      if (ns) card.title = ns;
      wrap.append(card);
    }
    return { node: wrap };
  }

  /* ========================= segmented toggle ========================= */

  const seg = (options, initial, cb) => {
    const wrap = el("div", { class: "mdl-seg" });
    const btns = options.map((o) => el("button", {
      class: "mdl-seg-btn" + (o === initial ? " on" : ""),
      text: o,
      onclick: () => {
        for (const b of btns) b.classList.remove("on");
        btns[options.indexOf(o)].classList.add("on");
        cb(o);
      },
    }));
    wrap.append(...btns);
    return wrap;
  };

  return { yangTree, xmlTree, yangCards, xmlCards, moduleCard, familyOf, FAMILY, seg, schemaSkeleton };
})();
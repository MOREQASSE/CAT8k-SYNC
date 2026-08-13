/* icons.js — Lucide sprite (1,756) + 22 custom network glyphs, offline.
   Usage: icon("server", 18, "var(--teal)") -> SVG string with <use>. */
"use strict";

const Sprite = (() => {
  /* DOM ids that must not collide with sprite symbol ids (e.g. lucide "shell") */
  const PROTECTED = ["sprite", "app", "auth", "auth-card", "shell", "sidebar", "main",
    "topbar", "view-host", "console", "console-dock", "console-head", "console-toggle",
    "console-title", "console-hint", "console-copy", "toasts", "clock", "brand", "nav",
    "card", "overlay", "modal", "toast", "field", "row", "tag", "dot", "icon", "bars"];

  let ready = null;
  function load() {
    if (ready) return ready;
    ready = new Promise((resolve) => {
      fetch("icons/sprite.svg")
        .then((r) => r.text())
        .then((svg) => {
          const host = document.getElementById("sprite");
          host.innerHTML = svg.replace(/^<svg[^>]*>/, "").replace(/<\/svg>$/, "");
          for (const id of PROTECTED) {
            const sym = host.querySelector(`symbol#${id}`);
            if (sym) sym.id = `sp-${id}`;
          }
          resolve(true);
        })
        .catch(() => resolve(false));
    });
    return ready;
  }
  function icon(name, size = 18, color = "currentColor", cls = "") {
    return `<svg class="icon ${cls}" width="${size}" height="${size}" aria-hidden="true">` +
      `<use href="#${name}" stroke="${color}" fill="none" stroke-width="1.8"` +
      ` stroke-linecap="round" stroke-linejoin="round"></use></svg>`;
  }
  return { load, icon };
})();

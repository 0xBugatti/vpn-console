/* vpn-console SPA — hash router, api client, friction-tier dialogs, toasts,
   health polling, ⌘K palette. Pages registered in PAGES below (one per section).
   Design system: design-system/MASTER.md (binding). */
import { icon, osIcon } from "./icons.js";
import { renderProfiles } from "./pages/profiles.js";
import { renderDevices, searchDevices } from "./pages/devices.js";
import { renderOverview } from "./pages/overview.js";
import { renderAcl } from "./pages/acl.js";
import { renderNode } from "./pages/node.js";
import { renderExposures } from "./pages/exposures.js";
import { renderServices } from "./pages/services.js";
import { renderLogs } from "./pages/logs.js";
import { renderAudit } from "./pages/audit.js";
import { renderSettings } from "./pages/settings.js";

/* ---------- tiny helpers ---------- */
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

export function h(html) {
  const t = document.createElement("template");
  t.innerHTML = html.trim();
  return t.content.firstElementChild;
}

export function relTime(iso) {
  if (!iso || iso.startsWith("0001")) return "never";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const diff = then - Date.now();
  const abs = Math.abs(diff);
  const unit = abs < 60e3 ? ["s", 1e3] : abs < 3600e3 ? ["m", 60e3]
    : abs < 86400e3 ? ["h", 3600e3] : abs < 30 * 86400e3 ? ["d", 86400e3] : ["mo", 30 * 86400e3];
  const n = Math.round(abs / unit[1]);
  const suffix = unit[0] === "mo" ? "mo" : unit[0];
  return diff >= 0 ? `in ${n}${suffix}` : `${n}${suffix} ago`;
}

export function fmtDate(iso) {
  if (!iso || iso.startsWith("0001")) return "never";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function copyText(text, label = "Copied") {
  navigator.clipboard?.writeText(text).then(
    () => toast(`${label}.`, "success"),
    () => toast("Copy failed — select the text manually.", "error"),
  );
}

/* ---------- api client ---------- */
export async function api(path, opts = {}) {
  const res = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
    body: opts.body !== undefined ? (typeof opts.body === "string" ? opts.body : JSON.stringify(opts.body)) : undefined,
  });
  if (res.status === 401 && !path.startsWith("/auth/")) {
    location.hash = "#/login";
    throw { code: "not_signed_in", message: "Signed out" };
  }
  if (!res.ok) {
    let err = { code: "error", message: `HTTP ${res.status}` };
    try { err = (await res.json()).error || err; } catch { /* keep */ }
    throw err;
  }
  if (res.status === 204) return null;
  const type = res.headers.get("content-type") || "";
  return type.includes("json") ? res.json() : res.text();
}

/* ---------- toasts (undo = friction tier 1) ---------- */
export function toast(msg, kind = "info", action = null) {
  const box = $(".toasts");
  const el = h(`<div class="toast ${kind}" role="status">
    <span class="msg">${esc(msg)}</span>
    ${action ? `<button class="undo-btn">${esc(action.label)}</button>` : ""}
    <button class="close" aria-label="Dismiss">${icon("x", 14)}</button>
  </div>`);
  box.appendChild(el);
  const kill = () => el.remove();
  const timer = setTimeout(kill, action ? 10000 : 4500); // 10 s undo window (FR-013)
  $(".close", el).onclick = () => { clearTimeout(timer); kill(); };
  if (action) $(".undo-btn", el).onclick = async () => {
    clearTimeout(timer);
    try { await action.run(); } catch (e) { toast(errorText(e), "error"); }
    kill();
  };
}

export function errorText(e) {
  return e?.message || e?.code || "Something went wrong";
}

/* ---------- dialogs: friction tiers 2 & 3 (FR-051) ---------- */
/* Dialogs: Escape cancels, Tab stays inside, focus returns to the trigger. */
export function trapKeys(scrim, close) {
  const prev = document.activeElement;
  scrim.addEventListener("keydown", (e) => {
    if (e.key === "Escape") { e.preventDefault(); close(false); }
    if (e.key === "Tab") {
      const focusables = $$("button, input, select, [tabindex]:not([tabindex='-1'])", scrim)
        .filter((el) => !el.disabled && el.offsetParent !== null);
      if (!focusables.length) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
    }
  });
  return () => { if (prev && typeof prev.focus === "function") prev.focus(); };
}

export function confirmDialog({ title, body, confirmLabel = "Confirm", danger = false }) {
  return new Promise((resolve) => {
    const scrim = h(`<div class="dialog-scrim" role="dialog" aria-modal="true">
      <div class="dialog ${danger ? "danger-accent" : ""}">
        <h2>${esc(title)}</h2>
        <div class="body">${body}</div>
        <div class="btn-row">
          <button class="btn ghost" data-no>Cancel</button>
          <button class="btn ${danger ? "danger" : "primary"}" data-yes>${esc(confirmLabel)}</button>
        </div>
      </div>
    </div>`);
    document.body.appendChild(scrim);
    let done = false;
    const close = (v) => {
      if (done) return;
      done = true;
      scrim.remove();
      restore();
      resolve(v);
    };
    const restore = trapKeys(scrim, close);
    $("[data-no]", scrim).onclick = () => close(false);
    $("[data-yes]", scrim).onclick = () => close(true);
    scrim.onclick = (e) => { if (e.target === scrim) close(false); };
    $("[data-no]", scrim).focus(); // no default focus on the destructive action
  });
}

export function typeConfirmDialog({ title, body, phrase, confirmLabel = "Confirm" }) {
  return new Promise((resolve) => {
    const scrim = h(`<div class="dialog-scrim" role="dialog" aria-modal="true">
      <div class="dialog danger-accent">
        <h2>${esc(title)}</h2>
        <div class="body">${body}</div>
        <div class="field">
          <label>Type <strong class="mono">${esc(phrase)}</strong> to confirm</label>
          <input class="input" data-phrase autocomplete="off" spellcheck="false">
        </div>
        <div class="btn-row">
          <button class="btn ghost" data-no>Cancel</button>
          <button class="btn danger" data-yes disabled>${esc(confirmLabel)}</button>
        </div>
      </div>
    </div>`);
    document.body.appendChild(scrim);
    const input = $("[data-phrase]", scrim);
    const yes = $("[data-yes]", scrim);
    input.oninput = () => { yes.disabled = input.value.trim() !== phrase; };
    let done = false;
    const close = (v) => {
      if (done) return;
      done = true;
      scrim.remove();
      restore();
      resolve(v);
    };
    const restore = trapKeys(scrim, close);
    $("[data-no]", scrim).onclick = () => close(false);
    yes.onclick = () => close(true);
    $("[data-no]", scrim).focus();
  });
}

/* ---------- status rendering (FR-052) ---------- */
export function status(kind, label) {
  return `<span class="status ${kind}"><span class="dot"></span>${esc(label)}</span>`;
}

export function healthBanner(result) {
  if (!result || result.state === "ok") return "";
  const stale = result.age_seconds > 5 && result.data !== null;
  const cls = result.state === "unavailable" ? "err" : "";
  return `<div class="health-banner ${cls}">
    ${icon(result.state === "unavailable" ? "wifioff" : "alert", 16)}
    <span><strong>${result.state === "unavailable" ? "Unavailable" : "Degraded"}.</strong>
    Showing ${stale ? `data from ${Math.round(result.age_seconds)}s ago` : "no data"}. ${esc(result.detail || "")}
    Mutations are disabled until it recovers.</span>
  </div>`;
}

/* ---------- theme ---------- */
export function applyTheme(pref) {
  const root = document.documentElement;
  if (pref === "system") { root.removeAttribute("data-theme"); return; }
  root.dataset.theme = pref;
}
applyTheme(localStorage.getItem("vc_theme") || "system");

/* ---------- health polling (topbar dots, FR-003) ---------- */
const HEALTH_LABELS = { tscloud: "Tailnet", tslocal: "Node", host: "Host" };
let healthTimer = null;

function healthKind(state) {
  return state === "ok" ? "ok" : state === "degraded" ? "warn" : "err";
}

async function pollHealth() {
  try {
    const data = await api("/health");
    const host = $(".health-dots");
    if (!host) return;
    host.innerHTML = Object.entries(data.subsystems).map(([name, hsub]) =>
      `<span class="health-pill" title="${esc(hsub.detail || HEALTH_LABELS[name])}">${status(healthKind(hsub.state), HEALTH_LABELS[name] || name)}</span>`
    ).join("");
  } catch { /* signed out — login page has no dots */ }
}

function startHealthPolling() {
  pollHealth();
  clearInterval(healthTimer);
  const secs = Number(localStorage.getItem("vc_poll_status_s")) || 12;
  healthTimer = setInterval(pollHealth, secs * 1000);
}

/* ---------- pages registry ---------- */
export const PAGES = {
  overview:   { title: "Overview",      icon: "overview", render: () => stub("Overview") },
  profiles:   { title: "Profiles",      icon: "profiles", render: () => stub("Profiles") },
  devices:    { title: "Devices",       icon: "devices",  render: () => stub("Devices") },
  acl:        { title: "Access Control",icon: "acl",      render: () => stub("Access Control") },
  node:       { title: "Local Node",    icon: "node",     render: () => stub("Local Node") },
  exposures:  { title: "Exposures",     icon: "exposures",render: () => stub("Exposures") },
  services:   { title: "Services",      icon: "services", render: () => stub("Services") },
  logs:       { title: "Logs",          icon: "logs",     render: () => stub("Logs") },
  audit:      { title: "Audit Log",     icon: "audit",    render: () => stub("Audit Log") },
  settings:   { title: "Settings",      icon: "settings", render: () => stub("Settings") },
};

const NAV_ORDER = Object.keys(PAGES);
const stub = (name) => `<div class="card"><h2>${esc(name)}</h2><p class="muted">This section is being built.</p></div>`;

PAGES.overview.render = renderOverview; // US6 — built page
PAGES.profiles.render = renderProfiles; // US2 — built page
PAGES.acl.render = renderAcl;           // US7 — built page
PAGES.devices.render = renderDevices;   // US4 — built page
PAGES.devices.search = searchDevices;   // ⌘K / global search jumps here
PAGES.node.render = renderNode;         // US8 — built page
PAGES.exposures.render = renderExposures; // US10 — built page
PAGES.services.render = renderServices; // US9 — built page
PAGES.logs.render = renderLogs;         // US9 — built page
PAGES.audit.render = renderAudit;       // US11 — built page
PAGES.settings.render = renderSettings; // US12 — built page

/* ---------- router ---------- */
let pageTimers = [];

function clearPageTimers() { pageTimers.forEach(clearInterval); pageTimers = []; }

export function every(ms, fn) { const t = setInterval(fn, ms); pageTimers.push(t); return t; }

function currentRoute() {
  const hash = location.hash.replace(/^#\/?/, "");
  const [name, ...rest] = hash.split("/");
  return { name: PAGES[name] ? name : "overview", rest, raw: hash };
}

function renderNav() {
  const nav = $("#nav");
  nav.innerHTML = NAV_ORDER.map((key) => {
    const page = PAGES[key];
    return `<a class="nav-item" data-nav="${key}" href="#/${key}">${icon(page.icon, 16)}<span>${esc(page.title)}</span><span class="count" data-count="${key}"></span></a>`;
  }).join("");
}

function render() {
  clearPageTimers();
  const { name } = currentRoute();
  if (location.hash === "" || location.hash === "#") location.hash = "#/overview";
  const root = $("#page");
  root.innerHTML = "";
  PAGES[name].render(root, currentRoute());
  $$(".nav-item").forEach((el) => el.classList.toggle("active", el.dataset.nav === name));
  $("#crumb").textContent = PAGES[name].title;
  document.title = `${PAGES[name].title} · VPN Console`;
  $$(".scrim[data-menu]").forEach((s) => s.remove());
  $(".sidebar").classList.remove("open");
}

function renderShell() {
  $("#app").innerHTML = `
  <a class="skip-link" href="#page">Skip to content</a>
  <div class="shell">
    <aside class="sidebar">
      <div class="brand">VPN<span class="dot">·</span>Console</div>
      <nav id="nav" aria-label="Sections"></nav>
      <div class="spacer"></div>
      <div class="sidebar-footer">internal · single admin</div>
    </aside>
    <div class="main">
      <header class="topbar">
        <button class="btn ghost sm menu-btn" data-menu aria-label="Menu">${icon("menu", 16)}</button>
        <span class="kicker" id="crumb"></span>
        <div class="spacer"></div>
        <label class="search" title="Search (⌘K)">${icon("search", 15)}
          <input id="global-q" placeholder="Search — ⌘K">
        </label>
        <div class="health-dots" aria-label="Subsystem health"></div>
        <button class="btn ghost sm" id="signout" title="Sign out">${icon("logout", 15)}</button>
      </header>
      <main class="content" id="page" tabindex="-1"></main>
    </div>
  </div>
  <div class="toasts" aria-live="polite"></div>`;
  renderNav();
  $("#signout").onclick = async () => {
    await api("/auth/logout", { method: "POST" });
    location.hash = "#/login";
    location.reload();
  };
  $("[data-menu]").onclick = () => {
    $(".sidebar").classList.add("open");
    const scrim = h('<div class="scrim" data-menu></div>');
    scrim.onclick = () => { $(".sidebar").classList.remove("open"); scrim.remove(); };
    document.body.appendChild(scrim);
  };
  $("#global-q").onkeydown = (e) => {
    if (e.key === "Enter") { handoffSearch($("#global-q").value); $("#global-q").value = ""; }
  };
  startHealthPolling();
  render();
}

/* ---------- login (US1) ---------- */
function renderLogin(message = "") {
  $("#app").innerHTML = `
  <div class="login-wrap">
    <form class="login-card" id="login-form">
      <div class="brand">VPN<span class="dot">·</span>Console</div>
      <p class="sub">Sign in to manage profiles, devices, and this server.</p>
      <p class="form-error" id="login-err">${esc(message)}</p>
      <div class="field">
        <label for="pw">Admin password</label>
        <input class="input" type="password" id="pw" autocomplete="current-password" required>
      </div>
      <button class="btn primary" style="width:100%" type="submit">Sign in</button>
    </form>
  </div>`;
  $("#pw").focus();
  $("#login-form").onsubmit = async (e) => {
    e.preventDefault();
    const btn = $("#login-form button[type=submit]");
    btn.disabled = true;
    try {
      await api("/auth/login", { method: "POST", body: { password: $("#pw").value } });
      location.hash = "#/overview";
      renderShell();
    } catch (err) {
      btn.disabled = false;
      $("#login-err").textContent = err.code === "rate_limited" || err.message.includes("wait")
        ? "Too many attempts — wait a minute and try again."
        : "Wrong password. Try again.";
    }
  };
}

/* ---------- boot ---------- */
async function boot() {
  try {
    await api("/auth/me");
    renderShell();
  } catch {
    renderLogin();
  }
}

/* ---------- ⌘K palette ---------- */
let paletteItems = [];

function handoffSearch(q) {
  q = (q || "").trim();
  if (!q) return;
  PAGES.devices.search?.(q);          // state must be set BEFORE the page renders
  if (currentRoute().name === "devices") render();
  else location.hash = "#/devices";
}

function openPalette() {
  const extra = PAGES[currentRoute().name].paletteItems?.() || [];
  paletteItems = [
    ...NAV_ORDER.map((key) => ({ label: `Go to ${PAGES[key].title}`, icon: PAGES[key].icon, run: () => { location.hash = `#/${key}`; } })),
    { label: "Import profiles", icon: "upload", run: () => {
        location.hash = "#/profiles";
        setTimeout(() => $("#import-btn")?.click(), 350);
      } },
    { label: "Connect a device", icon: "plus", run: () => {
        location.hash = "#/overview";
        setTimeout(() => $("#qa-connect")?.click(), 350);
      } },
    { label: "Download last profile", icon: "download", run: () => {
        location.hash = "#/overview";
        setTimeout(() => $("#qa-download")?.click(), 350);
      } },
    { label: "Test the Tailscale credential", icon: "external", run: () => { location.hash = "#/settings"; } },
    { label: "Export the audit log", icon: "audit", run: () => { location.hash = "#/audit"; } },
    ...extra,
  ];
  const scrim = h(`<div class="palette-scrim"><div class="palette" role="dialog" aria-modal="true">
    <input placeholder="Type a command, or search devices…" aria-label="Command palette">
    <div class="items"></div>
  </div></div>`);
  document.body.appendChild(scrim);
  const input = $("input", scrim);
  const items = $(".items", scrim);
  let sel = 0;
  let matches = [];
  const draw = (q = "") => {
    const needle = q.toLowerCase();
    matches = paletteItems.filter((it) => it.label.toLowerCase().includes(needle));
    // free text that matches nothing structural becomes a device search (FR-020 handoff)
    if (q.trim() && !matches.length) {
      matches = [{ label: `Search devices for “${q.trim()}”`, icon: "search", run: () => handoffSearch(q) }];
    }
    sel = 0;
    items.innerHTML = matches.map((it, i) =>
      `<div class="item ${i === 0 ? "sel" : ""}" data-i="${i}">${icon(it.icon || "chevron", 15)}<span>${esc(it.label)}</span></div>`
    ).join("") || `<div class="item muted">No matches</div>`;
  };
  const setSel = (i) => {
    sel = (i + matches.length) % matches.length;
    $$(".item", items).forEach((el, j) => el.classList.toggle("sel", j === sel));
    $(`.item[data-i="${sel}"]`, items)?.scrollIntoView({ block: "nearest" });
  };
  draw();
  input.oninput = () => draw(input.value);
  input.onkeydown = (e) => {
    if (e.key === "Escape") scrim.remove();
    if (e.key === "ArrowDown") { e.preventDefault(); setSel(sel + 1); }
    if (e.key === "ArrowUp") { e.preventDefault(); setSel(sel - 1); }
    if (e.key === "Enter") {
      const it = matches[sel];
      scrim.remove();
      it?.run();
    }
  };
  items.onclick = (e) => {
    const item = e.target.closest(".item");
    if (item?.dataset.i !== undefined) {
      const it = matches[Number(item.dataset.i)];
      scrim.remove();
      it?.run();
    }
  };
  items.onmousemove = (e) => {
    const item = e.target.closest(".item");
    if (item?.dataset.i !== undefined) setSel(Number(item.dataset.i));
  };
  input.focus();
  scrim.onclick = (e) => { if (e.target === scrim) scrim.remove(); };
}

document.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
    e.preventDefault();
    if ($("#login-form")) return;
    openPalette();
  }
});

window.addEventListener("hashchange", () => { if ($(".topbar")) render(); });
boot();

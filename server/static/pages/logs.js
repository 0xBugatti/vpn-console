/* Logs page (US9, FR-048): per-unit journal viewer — severity filter, text
   search, live follow via cursor polling (research D13), download. */
import { api, toast, errorText, esc, $, healthBanner, icon, every } from "../app.js";

const PRIO_KIND = { 0: "err", 1: "err", 2: "err", 3: "err", 4: "warn", 5: "warn" };

let ROOT = null;
let UNIT = "";
let AFTER = "";
let FOLLOW = true;
let LINES = [];
let UNITS = [];

export async function renderLogs(root) {
  ROOT = root;
  root.innerHTML = `
  <div class="page-head">
    <h1>Logs</h1>
    <div class="btn-row">
      <button class="btn ghost sm" id="log-download" title="Download filtered entries">${icon("download", 14)} Download</button>
      <button class="btn ghost sm" id="log-follow" aria-pressed="true">${icon("refresh", 14)} Follow</button>
    </div>
  </div>
  <p class="page-sub">journald for the managed units on this host.</p>
  <div class="log-controls">
    <select class="input sm" id="log-unit" aria-label="Unit"></select>
    <select class="input sm" id="log-sev" aria-label="Severity">
      <option value="">All severities</option>
      <option value="err">Errors and worse</option>
      <option value="warning">Warnings and worse</option>
      <option value="info">Info and worse</option>
    </select>
    <input class="input sm" id="log-q" placeholder="Search messages…" aria-label="Search messages">
    <span class="freshness" id="log-note"></span>
  </div>
  <div id="log-banner"></div>
  <section class="card"><div class="log-lines mono" id="log-lines" aria-live="polite"></div></section>`;

  $("#log-unit", root).onchange = (e) => { UNIT = e.target.value; refresh(); };
  $("#log-sev", root).onchange = () => refresh();
  let qTimer = null;
  $("#log-q", root).oninput = () => {
    clearTimeout(qTimer);
    qTimer = setTimeout(refresh, 300);
  };
  $("#log-follow", root).onclick = (e) => {
    FOLLOW = !FOLLOW;
    e.currentTarget.setAttribute("aria-pressed", String(FOLLOW));
    e.currentTarget.classList.toggle("active", FOLLOW);
    if (FOLLOW) refresh();
  };
  $("#log-download", root).onclick = () => {
    const params = new URLSearchParams();
    const sev = $("#log-sev", root).value;
    const q = $("#log-q", root).value;
    if (sev) params.set("severity", sev);
    if (q) params.set("q", q);
    location.href = `/api/logs/${encodeURIComponent(UNIT)}/download?${params}`;
  };

  await loadUnits();
  await refresh();
  every(2500, tick);
}

async function loadUnits() {
  let data;
  try { data = await api("/logs"); }
  catch (err) { toast(errorText(err), "error"); return; }
  UNITS = data.units || [];
  const sel = $("#log-unit", ROOT);
  sel.innerHTML = UNITS.map((u) => `<option value="${esc(u)}">${esc(u)}</option>`).join("")
    || `<option value="">No units</option>`;
  UNIT = UNITS[0] || "";
  sel.value = UNIT;
  if (!UNITS.length) {
    $("#log-banner", ROOT).innerHTML =
      healthBanner({ ...data._health, data: null });
  }
}

function params(withCursor) {
  const p = new URLSearchParams();
  const sev = $("#log-sev", ROOT).value;
  const q = $("#log-q", ROOT).value;
  if (sev) p.set("severity", sev);
  if (q) p.set("q", q);
  if (withCursor && AFTER) p.set("after", AFTER);
  p.set("limit", "300");
  return p;
}

async function refresh() {
  if (!UNIT) return;
  AFTER = "";
  let data;
  try {
    data = await api(`/logs/${encodeURIComponent(UNIT)}?${params(false)}`);
  } catch (err) { toast(errorText(err), "error"); return; }
  LINES = data.lines || [];
  AFTER = data.next_cursor || "";
  drawLog(data);
}

async function tick() {
  if (!FOLLOW || !UNIT) return;
  let data;
  try { data = await api(`/logs/${encodeURIComponent(UNIT)}?${params(true)}`); }
  catch { return; } // transient — next tick retries
  if (data.lines?.length) {
    LINES = [...LINES, ...data.lines].slice(-500); // cap the live buffer
    AFTER = data.next_cursor || AFTER;
    drawLog(data);
  } else {
    drawNote(data._health);
  }
}

function fmtTs(us) {
  const ms = Number(us) / 1000;
  if (!ms) return "";
  return new Date(ms).toLocaleTimeString(undefined, { hour12: false });
}

function drawLog(data) {
  const host = $("#log-lines", ROOT);
  if (!LINES.length) {
    const filtered = $("#log-sev", ROOT)?.value || $("#log-q", ROOT)?.value;
    host.innerHTML = `<p class="faint">No entries match${data._health?.state !== "ok" ? " (journal unavailable)" : filtered ? " these filters" : " for this unit yet"}.</p>
      ${filtered && data._health?.state === "ok" ? '<button class="btn ghost sm" data-log-clear>Clear filters</button>' : ""}`;
    $("[data-log-clear]", host)?.addEventListener("click", () => {
      const sev = $("#log-sev", ROOT);
      const q = $("#log-q", ROOT);
      if (sev) sev.value = "";
      if (q) q.value = "";
      refresh();
    });
  } else {
    host.innerHTML = LINES.map((ln) => `
      <div class="log-line ${PRIO_KIND[ln.prio] || ""}">
        <span class="log-ts">${esc(fmtTs(ln.ts))}</span>
        <span class="log-prio" title="priority ${ln.prio}"></span>
        <span class="log-msg">${esc(ln.msg)}</span>
      </div>`).join("");
    host.scrollTop = host.scrollHeight;
  }
  drawNote(data._health);
}

function drawNote(health) {
  const note = $("#log-note", ROOT);
  if (!note) return;
  if (health && health.state !== "ok") {
    $("#log-banner", ROOT).innerHTML = healthBanner({ ...health, data: null });
    note.textContent = "journal unavailable";
  } else {
    $("#log-banner", ROOT).innerHTML = "";
    note.textContent = FOLLOW ? `following ${UNIT} · live` : `${LINES.length} entries · follow paused`;
  }
}

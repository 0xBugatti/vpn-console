/* Audit Log page (US11, FR-050): reverse-chron trail, filters, exact-set
   export. Read-only by design — no edit/delete affordances anywhere; the
   table's append-only guarantee is the point, not a limitation to hide. */
import {
  api, toast, errorText, esc, $, status, icon, every,
} from "../app.js";

const SECTIONS = ["", "profiles", "devices", "acl", "node", "exposures",
  "services", "settings", "auth"];
const OUTCOMES = ["", "ok", "failed", "undone"];
const OUTCOME_PILL = {
  ok: ["ok", "ok"],
  failed: ["err", "failed"],
  undone: ["info", "undone"],
};

let ROOT = null;
let CURSOR = null;   // next_cursor of the last loaded page
let DEBOUNCE = null;

export async function renderAudit(root) {
  ROOT = root;
  root.innerHTML = `
  <div class="page-head">
    <h1>Audit Log</h1>
    <a class="btn ghost sm" id="audit-export" href="/api/audit/export">
      ${icon("download", 14)} Export JSON</a>
    <button class="btn ghost sm" id="audit-refresh">${icon("refresh", 14)} Refresh</button>
  </div>
  <p class="page-sub">Every change, its outcome and every undo, newest first. Entries are append-only: nothing here can be edited or removed, not even by this console.</p>

  <div class="log-controls">
    <input class="input sm" id="f-action" placeholder="Action, for example profile.disable" spellcheck="false">
    <select class="input sm" id="f-section">
      ${SECTIONS.map((s) => `<option value="${s}">${s ? s : "All sections"}</option>`).join("")}
    </select>
    <select class="input sm" id="f-outcome">
      ${OUTCOMES.map((o) => `<option value="${o}">${o ? o : "All outcomes"}</option>`).join("")}
    </select>
    <label class="toggle-row">from <input class="input sm" type="date" id="f-from"></label>
    <label class="toggle-row">to <input class="input sm" type="date" id="f-to"></label>
    <span class="faint small">(times UTC)</span>
  </div>

  <section class="card">
    <div class="table-wrap">
      <table class="table" id="audit-table">
        <thead><tr><th>Time (UTC)</th><th>Action</th><th>Target</th><th>Section</th><th>Outcome</th><th>Detail</th></tr></thead>
        <tbody></tbody>
      </table>
    </div>
    <div class="btn-row" style="margin-top:10px">
      <button class="btn ghost sm" id="audit-more" hidden>Load older events</button>
    </div>
  </section>`;

  $("#f-action", root).addEventListener("input", () => refilter());
  for (const id of ["f-section", "f-outcome", "f-from", "f-to"]) {
    $(`#${id}`, root).addEventListener("change", () => refilter());
  }
  $("#audit-refresh", root).onclick = () => reload(true);
  $("#audit-more", root).onclick = () => load(false);

  await reload(false);
  every(15000, () => reload(true));
}

/* ---------- filters ---------- */
function filters() {
  const f = {};
  const action = $("#f-action", ROOT).value.trim();
  if (action) f.action = action;
  const section = $("#f-section", ROOT).value;
  if (section) f.section = section;
  const outcome = $("#f-outcome", ROOT).value;
  if (outcome) f.outcome = outcome;
  const from = $("#f-from", ROOT).value;
  if (from) f.from = `${from}T00:00:00Z`;
  const to = $("#f-to", ROOT).value;
  if (to) f.to = `${to}T23:59:59Z`;
  return f;
}

function qs(extra = {}) {
  return new URLSearchParams({ ...filters(), ...extra }).toString();
}

function refilter() {
  clearTimeout(DEBOUNCE);
  DEBOUNCE = setTimeout(() => reload(false), 300);
}

async function reload(silent) {
  CURSOR = null;
  $("#audit-table tbody", ROOT).innerHTML = "";
  await load(silent);
}

/* ---------- data ---------- */
async function load(silent) {
  const params = qs(CURSOR ? { cursor: CURSOR } : {});
  let data;
  try {
    data = await api(`/audit${params ? `?${params}` : ""}`);
  } catch (err) {
    if (!silent) toast(errorText(err), "error");
    return;
  }
  const tbody = $("#audit-table tbody", ROOT);
  if (!data.entries.length && !tbody.children.length) {
    const filtered = Object.keys(filters()).length > 0;
    tbody.innerHTML = `<tr><td colspan="6" class="faint">No events match${filtered ? " these filters" : " yet. Every change appears here as it happens"}.</td></tr>
      ${filtered ? '<tr><td colspan="6"><button class="btn ghost sm" data-clear-filters>Clear filters</button></td></tr>' : ""}`;
    $("[data-clear-filters]", tbody)?.addEventListener("click", () => {
      $("#f-action", ROOT).value = "";
      $("#f-section", ROOT).value = "";
      $("#f-outcome", ROOT).value = "";
      $("#f-from", ROOT).value = "";
      $("#f-to", ROOT).value = "";
      reload(false);
    });
  } else {
    tbody.insertAdjacentHTML("beforeend", data.entries.map(rowHtml).join(""));
  }
  CURSOR = data.next_cursor;
  $("#audit-more", ROOT).hidden = !data.next_cursor;
  // export always reflects the current filters — never a cursor position
  const exportQs = qs();
  $("#audit-export", ROOT).href = `/api/audit/export${exportQs ? `?${exportQs}` : ""}`;
}

function rowHtml(e) {
  const [kind, label] = OUTCOME_PILL[e.outcome] || ["off", e.outcome];
  const link = e.undone_by
    ? ` ${status("info", `undone by #${e.undone_by}`)}`
    : (e.undoes_event_id ? `<span class="faint small">undoes #${e.undoes_event_id}</span>` : "");
  const keys = Object.keys(e.detail || {});
  const detail = keys.length
    ? `<details class="detail-json"><summary>${keys.length} field${keys.length > 1 ? "s" : ""}</summary>
       <pre>${esc(JSON.stringify(e.detail, null, 2))}</pre></details>`
    : `<span class="faint">—</span>`;
  const failedUndo = e.action.startsWith("undo.") && e.outcome === "failed";
  return `<tr id="ev-${e.id}" class="${failedUndo ? "funnel-row" : ""}">
    <td class="log-ts small">${esc(e.ts.replace("T", " ").replace("Z", ""))}</td>
    <td class="mono small">${esc(e.action)}</td>
    <td class="small">${esc(e.target || "—")}</td>
    <td class="small faint">${esc(e.section)}</td>
    <td>${status(kind, label)}${link}</td>
    <td class="small">${detail}</td>
  </tr>`;
}

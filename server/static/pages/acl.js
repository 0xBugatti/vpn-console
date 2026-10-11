/* Access Control page (US7): HuJSON editor (formatting preserved) + structured
   view + Validate → diff → Apply (confirm) → pinned one-click Rollback (FR-040). */
import {
  api, toast, errorText, esc, h, $, $$, confirmDialog, healthBanner, icon,
} from "../app.js";

const state = { applied: "", draft: null, pinned: false, structured: [], errors: [], diff: null };

const KIND_LABEL = {
  groups: "Groups", tagOwners: "Tag owners", hosts: "Hosts",
  acls: "Access rules (legacy)", grants: "Grants", ipsets: "IP sets", nodeAttrs: "Node attributes",
};

export async function renderAcl(root) {
  root.innerHTML = `
  <div class="page-head">
    <h1>Access Control</h1>
    <div class="spacer"></div>
    <button class="btn ghost sm" id="acl-rollback" hidden>${icon("undo", 15)} Rollback to previous policy</button>
    <button class="btn ghost sm" id="acl-validate">${icon("check", 15)} Validate</button>
    <button class="btn primary sm" id="acl-apply">${icon("check", 15)} Apply…</button>
  </div>
  <p class="page-sub">The policy file is the source of truth — comments and formatting are preserved exactly.</p>
  <div id="acl-banner"></div>

  <div class="acl-grid">
    <section class="card acl-editor-card">
      <h2>Policy file <span class="faint small" id="acl-state"></span></h2>
      <textarea class="input mono acl-editor" id="acl-text" spellcheck="false"
        aria-label="Tailnet policy (HuJSON)"></textarea>
      <div id="acl-errors" aria-live="polite"></div>
    </section>

    <section class="card acl-structured-card">
      <h2>Structured view</h2>
      <p class="hint small">Generated from the applied file — read-only.</p>
      <div id="acl-structured"></div>
    </section>
  </div>

  <section class="card" id="acl-diff-card" hidden>
    <h2>Changes vs applied</h2>
    <div id="acl-diff"></div>
  </section>`;

  await load(root);
  $("#acl-validate", root).onclick = () => validate(root);
  $("#acl-apply", root).onclick = () => apply(root);
  $("#acl-rollback", root).onclick = () => rollback(root);

  const ta = $("#acl-text", root);
  ta.addEventListener("keydown", (e) => {  // keep tabs literal inside the policy file
    if (e.key === "Tab") {
      e.preventDefault();
      const { selectionStart: s, selectionEnd: en } = ta;
      ta.value = ta.value.slice(0, s) + "\t" + ta.value.slice(en);
      ta.selectionStart = ta.selectionEnd = s + 1;
    }
  });
}

async function load(root) {
  let data;
  try { data = await api("/acl"); }
  catch (err) { toast(errorText(err), "error"); return; }
  state.applied = data.applied_text;
  state.draft = data.draft;
  state.structured = data.structured;
  const down = data._health && data._health.state !== "ok";
  $("#acl-banner", root).innerHTML = healthBanner({
    ...data._health, data: data.applied_text ? 1 : null,
  });
  // mutations need a live tailnet — the editor stays open read-only (FR-053)
  const applyBtn = $("#acl-apply", root);
  applyBtn.disabled = down;
  applyBtn.title = down ? "Tailnet unreachable — applying is blocked until it recovers." : "";
  $("#acl-rollback", root).disabled = down;
  $("#acl-text", root).value = data.draft ?? data.applied_text;
  $("#acl-state", root).textContent = data.draft ? "· unsaved draft" : "";
  drawStructured(data.structured);
}

/* ---------- validate (server-side, line refs) ---------- */
async function validate(root) {
  const text = $("#acl-text", root).value;
  try {
    const r = await api("/acl/draft", { method: "PUT", body: { text } });
    state.errors = r.errors || [];
    state.draft = text;
    $("#acl-state", root).textContent = "· unsaved draft";
    drawErrors(root);
    if (r.valid) {
      const diff = await api("/acl/diff");
      state.diff = diff;
      drawDiff(root, diff);
      toast("Policy is valid. Review the changes, then apply.", "success");
    } else {
      $("#acl-diff-card", root).hidden = true;
    }
  } catch (err) { toast(errorText(err), "error"); }
}

function drawErrors(root) {
  const host = $("#acl-errors", root);
  if (!state.errors.length) {
    host.innerHTML = "";
    return;
  }
  host.innerHTML = state.errors.map((e) => `
    <div class="acl-error">${icon("alert", 14)} <span class="mono">line ${e.line}</span> — ${esc(e.message)}</div>
  `).join("");
}

/* ---------- structured view (FR-041) ---------- */
function drawStructured(items) {
  const host = $("#acl-structured", root);
  if (!items.length) {
    host.innerHTML = `<p class="faint small">No applied policy available.</p>`;
    return;
  }
  const byKind = {};
  for (const it of items) (byKind[it.kind] ||= []).push(it);
  host.innerHTML = Object.entries(byKind).map(([kind, rows]) => `
    <div class="struct-group">
      <h3>${esc(KIND_LABEL[kind] || kind)} <span class="faint">${rows.length}</span></h3>
      <ul>${rows.map((r) => `
        <li><span class="mono struct-name">${esc(r.name)}</span>
            <span class="struct-items">${r.items.map((x) => `<span class="chip mono">${esc(x)}</span>`).join("")}</span>
        </li>`).join("")}</ul>
    </div>`).join("");
}

/* ---------- diff panel ---------- */
function drawDiff(root, diff) {
  const card = $("#acl-diff-card", root);
  if (!diff.added.length && !diff.removed.length) {
    card.hidden = true;
    return;
  }
  card.hidden = false;
  $("#acl-diff", root).innerHTML = `
    ${diff.added.map((r) => `<div class="diff-line added">+ ${esc(r)}</div>`).join("")}
    ${diff.removed.map((r) => `<div class="diff-line removed">− ${esc(r)}</div>`).join("")}
    ${!diff.added.length && !diff.removed.length ? '<p class="faint small">No access-rule changes.</p>' : ""}`;
}

/* ---------- apply (tier 2: confirm) + rollback pin ---------- */
async function apply(root) {
  const text = $("#acl-text", root).value;
  try {
    const check = await api("/acl/draft", { method: "PUT", body: { text } });
    if (!check.valid) { state.errors = check.errors || []; drawErrors(root); return; }
    const diff = await api("/acl/diff");
    const summary = [
      ...diff.added.map((r) => `+ ${r}`),
      ...diff.removed.map((r) => `− ${r}`),
    ];
    const yes = await confirmDialog({
      title: "Apply policy?",
      body: `<p>This replaces the tailnet policy on Tailscale's servers.</p>
        ${summary.length
          ? `<div class="diff-box">${summary.map((l) => `<div class="mono">${esc(l)}</div>`).join("")}</div>`
          : '<p class="muted small">No access-rule changes — formatting/comments only.</p>'}
        <p class="small muted">A one-click rollback stays available afterwards.</p>`,
      confirmLabel: "Apply policy",
      danger: summary.some((l) => l.startsWith("−")),
    });
    if (!yes) return;
    await api("/acl/apply", { method: "POST", body: { confirm: true } });
    $("#acl-rollback", root).hidden = false;
    state.pinned = true;
    $("#acl-state", root).textContent = "";
    $("#acl-diff-card", root).hidden = true;
    toast("Policy applied. Rollback stays pinned for this session.", "success");
    await load(root);
  } catch (err) {
    if (err?.detail?.errors) { state.errors = err.detail.errors; drawErrors(root); }
    toast(errorText(err), "error");
  }
}

async function rollback(root) {
  const yes = await confirmDialog({
    title: "Rollback policy?",
    body: `<p>Restores the previously applied policy, byte for byte.</p>`,
    confirmLabel: "Rollback",
    danger: true,
  });
  if (!yes) return;
  try {
    await api("/acl/rollback", { method: "POST" });
    $("#acl-rollback", root).hidden = true;
    state.pinned = false;
    toast("Previous policy restored.", "success");
    await load(root);
  } catch (err) { toast(errorText(err), "error"); }
}

/* Exposures page (US10, FR-043/044): serve / funnel / taildrive with scope
   badges, the red funnel confirm (exact public URL + internet reachability),
   enable toggles, raw listening ports with the collision warning. */
import {
  api, toast, errorText, esc, $, $$, h, status, healthBanner, icon,
  confirmDialog, every, trapKeys,
} from "../app.js";

const FUNNEL_PORTS = [443, 8443, 10000];

let ROOT = null;
let DATA = null;
let TAB = "serve";

export async function renderExposures(root) {
  ROOT = root;
  root.innerHTML = `
  <div class="page-head">
    <h1>Exposures</h1>
    <button class="btn primary sm" id="exp-add">${icon("plus", 14)} Add serve</button>
    <button class="btn ghost sm" id="exp-refresh">${icon("refresh", 14)} Refresh</button>
  </div>
  <p class="page-sub">Everything this host serves over Tailscale — and the one place it can reach the public internet.</p>
  <div id="exp-banner"></div>

  <section class="card">
    <div class="tabs" id="exp-tabs">
      <button class="tab" data-tab="serve">Serve <span class="count"></span></button>
      <button class="tab" data-tab="funnel">Funnel <span class="count"></span></button>
      <button class="tab" data-tab="taildrive">Taildrive <span class="count"></span></button>
    </div>
    <div class="table-wrap">
      <table class="table" id="exp-table">
        <thead><tr><th>Source</th><th>Scope</th><th>Serves</th><th>Status</th><th></th></tr></thead>
        <tbody></tbody>
      </table>
    </div>
  </section>

  <section class="card">
    <h2>Listening ports</h2>
    <p class="hint">Raw sockets on this host, annotated by what they actually are.
      When two claims share a port, tailscaled keeps the most recent one.</p>
    <div id="exp-collisions"></div>
    <div class="table-wrap">
      <table class="table" id="ports-table">
        <thead><tr><th>Address</th><th>Proto</th><th>Port</th><th>Process</th><th>Annotation</th></tr></thead>
        <tbody></tbody>
      </table>
    </div>
  </section>

  <div id="exp-dialog-host"></div>`;

  $("#exp-refresh", root).onclick = () => load(false);
  $("#exp-add", root).onclick = () => (TAB === "taildrive" ? openDriveDialog() : openAddDialog(TAB));
  $$("#exp-tabs .tab", root).forEach((btn) => {
    btn.onclick = () => {
      TAB = btn.dataset.tab;
      syncTabs();
    };
  });
  await load(false);
  every(12000, () => load(true));
}

function syncTabs() {
  $$("#exp-tabs .tab", ROOT).forEach((b) => b.classList.toggle("active", b.dataset.tab === TAB));
  const add = $("#exp-add", ROOT);
  add.innerHTML = TAB === "taildrive"
    ? `${icon("plus", 14)} Add drive share`
    : `${icon("plus", 14)} Add ${TAB}`;
  const down = (DATA?._health?.state ?? "ok") !== "ok";
  add.disabled = down;
  add.title = down ? "Local node unreachable — mutations are blocked until it recovers." : "";
  if (DATA) drawEntries(DATA);
}

/* ---------- add exposure (serve / funnel) ---------- */
function openAddDialog(preset = "serve") {
  const scrim = h(`<div class="dialog-scrim" role="dialog" aria-modal="true">
    <div class="dialog">
      <h2>Add exposure</h2>
      <div class="body">
        <div class="field">
          <label for="exp-kind">Kind</label>
          <select class="input" id="exp-kind">
            <option value="serve">Serve — tailnet only</option>
            <option value="funnel">Funnel — public internet (red)</option>
          </select>
        </div>
        <div class="field">
          <label for="exp-port">Listen port</label>
          <input class="input" id="exp-port" type="number" min="1" max="65535" value="443">
          <p class="hint" id="exp-port-hint">Funnel works on 443, 8443 and 10000 only.</p>
        </div>
        <div class="field">
          <label for="exp-target">Forwards to</label>
          <input class="input mono" id="exp-target" placeholder="http://127.0.0.1:3000">
        </div>
        <div class="toggle-row">
          <input type="checkbox" id="exp-tls" checked>
          <span>TLS (Let's Encrypt via Tailscale)</span>
        </div>
        <p class="form-error" id="exp-err" hidden></p>
      </div>
      <div class="btn-row">
        <button class="btn ghost" data-close>Cancel</button>
        <button class="btn primary" data-create>Create</button>
      </div>
    </div>
  </div>`);
  document.body.appendChild(scrim);
  const kindSel = $("#exp-kind", scrim);
  kindSel.value = preset === "funnel" ? "funnel" : "serve";
  $("#exp-port-hint", scrim).hidden = kindSel.value !== "funnel";
  kindSel.onchange = () => {
    $("#exp-port-hint", scrim).hidden = kindSel.value !== "funnel";
  };
  let done = false;
  const close = (v = false) => {
    if (done) return;
    done = true;
    scrim.remove();
    restore();
    return v;
  };
  const restore = trapKeys(scrim, close);
  $("[data-close]", scrim).onclick = () => close(false);
  scrim.onclick = (e) => { if (e.target === scrim) close(false); };

  $("[data-create]", scrim).onclick = async (e) => {
    const btn = e.currentTarget;
    const errBox = $("#exp-err", scrim);
    errBox.hidden = true;
    btn.disabled = true;
    const body = {
      kind: kindSel.value,
      port: Number($("#exp-port", scrim).value),
      target: $("#exp-target", scrim).value.trim(),
      tls: $("#exp-tls", scrim).checked,
    };
    if (body.kind === "funnel") body.confirm = true; // the red dialog below gates it
    if (body.kind === "funnel") {
      const ok = await confirmDialog({
        title: "Expose to the public internet?",
        danger: true,
        body: `<p><strong class="mono">${esc(body.target || "(no target yet)")}</strong> will be
          reachable by <strong>anyone on the internet</strong> at port
          <strong class="mono">${body.port}</strong> — not just your tailnet.</p>
          <p>Funnel traffic arrives on Tailscale's edge — ports 443, 8443 and 10000 only —
          and forwards to this host.</p>`,
        confirmLabel: "Expose publicly",
      });
      if (!ok) { btn.disabled = false; return; }
    }
    try {
      await api("/exposures", { method: "POST", body });
      close();
      toast(`${body.kind} created on port ${body.port}.`, "success");
      await load(true);
    } catch (err) {
      errBox.textContent = errorText(err);
      errBox.hidden = false;
      btn.disabled = false;
    }
  };
}

/* ---------- add drive share (tailnet scope — its own tab & dialog) ---------- */
function openDriveDialog() {
  const scrim = h(`<div class="dialog-scrim" role="dialog" aria-modal="true">
    <div class="dialog">
      <h2>Add Taildrive share</h2>
      <div class="body">
        <div class="field">
          <label for="drv-path">Folder on this host</label>
          <input class="input mono" id="drv-path" placeholder="/srv/shared">
        </div>
        <div class="field">
          <label for="drv-name">Share name</label>
          <input class="input" id="drv-name" placeholder="shared-docs">
          <p class="hint">Letters, digits, dots, dashes. Shows up in other devices' Taildrive views.</p>
        </div>
        <p class="form-error" id="drv-err" hidden></p>
      </div>
      <div class="btn-row">
        <button class="btn ghost" data-close>Cancel</button>
        <button class="btn primary" data-create>Share</button>
      </div>
    </div>
  </div>`);
  document.body.appendChild(scrim);
  let done = false;
  const close = () => { if (done) return; done = true; scrim.remove(); restore(); };
  const restore = trapKeys(scrim, close);
  $("[data-close]", scrim).onclick = close;
  scrim.onclick = (e) => { if (e.target === scrim) close(); };

  $("[data-create]", scrim).onclick = async (e) => {
    const btn = e.currentTarget;
    const errBox = $("#drv-err", scrim);
    errBox.hidden = true;
    btn.disabled = true;
    const body = {
      kind: "drive",
      path: $("#drv-path", scrim).value.trim(),
      name: $("#drv-name", scrim).value.trim(),
    };
    const ok = await confirmDialog({
      title: `Share ${body.path || "(no path)"} with your tailnet?`,
      body: `<p><strong class="mono">${esc(body.name || "(no name)")}</strong> will list the folder
        <strong class="mono">${esc(body.path)}</strong> in the Taildrive view of <strong>every device
        on your tailnet</strong> (read-only). It is not reachable from the public internet.</p>`,
      confirmLabel: "Share on tailnet",
    });
    if (!ok) { btn.disabled = false; return; }
    body.confirm = true; // the dialog above is the consent (confirm-tier)
    try {
      await api("/exposures", { method: "POST", body });
      close();
      toast(`Share ${body.name} created.`, "success");
      TAB = "taildrive";
      await load(true);
    } catch (err) {
      errBox.textContent = errorText(err);
      errBox.hidden = false;
      btn.disabled = false;
    }
  };
}

async function load(silent) {
  let data;
  try { data = await api("/exposures"); }
  catch (err) { if (!silent) toast(errorText(err), "error"); return; }
  DATA = data;
  const unhealthy = (data._health?.state !== "ok") || (data.ports_health?.state !== "ok");
  $("#exp-banner", ROOT).innerHTML = unhealthy
    ? healthBanner({
        state: data._health?.state !== "ok" ? data._health.state : data.ports_health.state,
        detail: data._health?.state !== "ok"
          ? `serve/drive: ${data._health?.detail || ""}` : `ports: ${data.ports_health?.detail || ""}`,
        data: data.entries.length ? data.entries : null,
        age_seconds: 0,
      })
    : "";
  drawEntries(data);
  drawPorts(data);
}

/* ---------- scope badge (FR-052: never color alone — icon + word) ---------- */
function scopeBadge(scope) {
  if (scope === "public") {
    return `<span class="scope-badge public">${icon("globe", 12)} Public — Funnel</span>`;
  }
  if (scope === "share") {
    return `<span class="scope-badge share">${icon("lan", 12)} Taildrive</span>`;
  }
  return `<span class="scope-badge tailnet">${icon("lan", 12)} Tailnet</span>`;
}

function drawEntries(data) {
  const tbody = $("#exp-table tbody", ROOT);
  const down = (data._health?.state ?? "ok") !== "ok";
  const entries = data.entries || [];

  // tab counts + active tab
  $$("#exp-tabs .tab", ROOT).forEach((b) => {
    const n = entries.filter((e) => e.kind === b.dataset.tab).length;
    $(".count", b).textContent = n ? String(n) : "";
    b.classList.toggle("active", b.dataset.tab === TAB);
  });

  const rows = entries.filter((e) => e.kind === TAB);
  const addLabel = { serve: "Add the first serve", funnel: "Add the first funnel",
    taildrive: "Add the first drive share" }[TAB];
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="5" class="faint">${
      TAB === "taildrive" ? "No Taildrive shares yet." : "Nothing is being served here."
    }</td></tr>
      <tr><td colspan="5"><button class="btn primary sm" data-empty-add ${down ? "disabled" : ""}>${icon("plus", 14)} ${addLabel}</button></td></tr>`;
    $("[data-empty-add]", tbody).onclick = () =>
      (TAB === "taildrive" ? openDriveDialog() : openAddDialog(TAB));
    return;
  }
  tbody.innerHTML = rows.map((e) => {
    const drive = e.kind === "taildrive";
    const lock = down ? "disabled title=\"Local node unreachable — mutations are blocked.\"" : "";
    const toggle = drive
      ? `<button class="btn ghost sm" data-del="${esc(e.id)}" ${lock}>${icon("trash", 13)} Remove</button>`
      : `<label class="boot-toggle" title="${e.enabled ? "Serving" : "Not serving"}">
           <input type="checkbox" data-toggle="${esc(e.id)}" ${e.enabled ? "checked" : ""} ${down ? "disabled" : ""}>
           <span>${e.enabled ? "on" : "off"}</span>
         </label>
         <button class="btn ghost sm" data-del="${esc(e.id)}" title="Stop serving" ${lock}>${icon("x", 13)}</button>`;
    const statusCell = drive
      ? status("info", e.name || "share")
      : (e.tls ? status("ok", "TLS") : status("off", "plain"));
    return `<tr data-id="${esc(e.id)}" class="${e.kind === "funnel" ? "funnel-row" : ""}">
      <td><span class="mono">${esc(e.source || e.id)}</span></td>
      <td>${scopeBadge(e.scope)}</td>
      <td class="small">${esc(e.target || "—")}</td>
      <td>${statusCell}</td>
      <td class="row-actions">${toggle}</td>
    </tr>`;
  }).join("");

  $$("[data-del]", tbody).forEach((btn) => {
    btn.onclick = () => removeEntry(btn.dataset.del);
  });
  $$("[data-toggle]", tbody).forEach((box) => {
    box.onchange = () => setEnabled(box.dataset.toggle, box.checked, box);
  });
}

async function setEnabled(eid, enabled, box) {
  const entry = DATA.entries.find((e) => e.id === eid) || {};
  if (entry.kind === "funnel" && enabled) {
    const ok = await funnelConfirm(entry);
    if (!ok) { box.checked = false; return; }
  }
  try {
    // re-enabling a funnel is confirm-tier server-side — the dialog above
    // already consented, so carry the flag (matches require_confirm on PATCH)
    const body = { enabled };
    if (enabled && entry.kind === "funnel") body.confirm = true;
    await api(`/exposures/${encodeURIComponent(eid)}`, {
      method: "PATCH", body,
    });
    toast(enabled ? `${eid} is serving again.` : `${eid} stopped.`, "success",
      enabled ? undefined : { label: "Undo", run: () => reEnable(eid) });
  } catch (err) {
    toast(errorText(err), "error");
    box.checked = !enabled;
  }
  await load(true);
}

async function reEnable(eid) {
  const entry = DATA.entries.find((e) => e.id === eid) || {};
  // Undo never silently re-exposes: funnel goes back up only through the red dialog.
  if (entry.kind === "funnel") {
    const ok = await funnelConfirm(entry);
    if (!ok) { toast(`${eid} stays off.`, "info"); return; }
  }
  const body = { enabled: true, ...(entry.kind === "funnel" ? { confirm: true } : {}) };
  try {
    await api(`/exposures/${encodeURIComponent(eid)}`, { method: "PATCH", body });
    toast(`${eid} restored.`, "success");
  } catch (err) {
    toast(errorText(err), "error");
  }
  await load(true);
}

async function removeEntry(eid) {
  const entry = DATA.entries.find((e) => e.id === eid) || {};
  const drive = entry.kind === "taildrive";
  const ok = await confirmDialog({
    title: drive ? `Remove Taildrive share ${entry.source}?` : `Stop serving ${entry.source}?`,
    body: drive
      ? "<p>The folder stops appearing in other devices' Taildrive views. The files are untouched.</p>"
      : "<p>The listener is removed from tailscaled's serve config and the address stops responding.</p>",
    confirmLabel: drive ? "Remove share" : "Stop serving",
    danger: entry.kind === "funnel",
  });
  if (!ok) return;
  try {
    // the dialog above is the consent — carry confirm (server enforces it)
    await api(`/exposures/${encodeURIComponent(eid)}`, { method: "DELETE", body: { confirm: true } });
    toast("Removed.", "success");
  } catch (err) {
    toast(errorText(err), "error");
  }
  await load(true);
}

/* ---------- funnel: the one red dialog (FR-043) ---------- */
function funnelConfirm(entry) {
  const url = entry.source || "";
  return confirmDialog({
    title: "Expose to the public internet?",
    danger: true,
    body: `
      <p><strong class="mono">${esc(url)}</strong> will be reachable by
      <strong>anyone on the internet</strong> — not just your tailnet.</p>
      <p>Funnel traffic arrives on Tailscale's edge for ports
      <strong>443, 8443, 10000</strong> only, and forwards to this host.</p>`,
    confirmLabel: "Expose publicly",
  });
}

/* ---------- listening ports ---------- */
const ANN_LABEL = {
  funnel: ["err", "Public (funnel)"],
  serve: ["info", "Tailnet (serve)"],
  local_only: ["warn", "Local only"],
  unexposed: ["off", "Unexposed"],
};

function drawPorts(data) {
  const collisions = data.collisions || [];
  const host = $("#exp-collisions", ROOT);
  host.innerHTML = collisions.length
    ? `<div class="attention-item sev-red">${status("err", "Conflict")}
        <span class="msg">Port ${collisions.map((p) => `<strong>${p}</strong>`).join(", ")}
        is claimed by both a serve and a funnel entry — tailscaled keeps the most
        recent claim. Resolve this or traffic will not behave as shown.</span></div>`
    : "";

  const tbody = $("#ports-table tbody", ROOT);
  const ports = data.ports || [];
  if (!ports.length) {
    tbody.innerHTML = `<tr><td colspan="5" class="faint">No listening ports found${data.ports_health?.state !== "ok" ? " — host layer unavailable" : ""}.</td></tr>`;
    return;
  }
  tbody.innerHTML = ports.map((p) => {
    const [kind, label] = ANN_LABEL[p.annotation] || ["off", p.annotation];
    return `<tr>
      <td class="mono small">${esc(p.local_addr)}</td>
      <td class="small">${esc(p.proto)}</td>
      <td class="small mono">${p.port}</td>
      <td class="small">${esc(p.process || "—")}</td>
      <td>${status(kind, label)}</td>
    </tr>`;
  }).join("");
}

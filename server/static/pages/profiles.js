/* Profiles page (US2): import (drag-drop + parse chips + duplicate resolve),
   filterable table, detail drawer with raw editor / revert / undo tier.
   Enable starts the profile's tunnel on this server, Disable stops it. */
import {
  api, toast, errorText, esc, h, $, $$, status, relTime, fmtDate,
  confirmDialog, typeConfirmDialog, icon, copyText, BASE, trapKeys,
} from "../app.js";

const STATUS_KIND = {
  Valid: "ok", Expiring: "warn", Expired: "err", Disabled: "off", "Parse error": "err",
};

/* The tunnel state, when the server has one, outranks the library status. */
const TUNNEL_CHIP = {
  connected: ["ok", "Connected"],
  connecting: ["warn", "Connecting"],
  stopping: ["warn", "Stopping"],
  failed: ["err", "Failed"],
};
const UP = new Set(["connected", "connecting"]);                      // asks before it is touched
const LIVE = new Set(["connected", "connecting", "stopping", "failed"]); // Disable has something to stop
const CERT_WARN_DAYS = 14;

const state = { q: "", rows: [], selected: new Set() };
const following = new Set();   // job ids already being followed
const pending = new Map();     // profile id -> "Starting" | "Stopping" until its job has finished

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function tunnelOf(p) { return p.tunnel?.state || "none"; }

function stateChip(p) {
  const doing = pending.get(p.id);   // the click was accepted but systemd has not caught up yet
  if (doing === "Stopping") return status("warn", "Stopping");
  const chip = TUNNEL_CHIP[tunnelOf(p)];
  if (chip) return status(chip[0], chip[1]);
  if (doing === "Starting") return status("warn", "Starting");
  return status(STATUS_KIND[p.status] || "off", p.status);
}

function serverOf(p) {
  const ep = p.endpoints[0];
  return ep ? `${ep.host}:${ep.port}${ep.proto ? `/${ep.proto}` : ""}` : "";
}

/* Certificate warning beside the date, so a Disabled profile does not hide an expired one. */
function certBadge(p) {
  if (!p.cert_expires_at) return "";
  const days = (Date.parse(p.cert_expires_at) - Date.now()) / 86400000;
  if (days <= 0) return ' <span class="badge danger">Expired</span>';
  if (days <= CERT_WARN_DAYS) return ' <span class="badge warn">Expiring</span>';
  return "";
}

/* What the Enable/Disable button should say and do for this tunnel state. */
function toggleView(p) {
  const s = tunnelOf(p);
  if (s === "unknown") return { label: "Server state unavailable", icon: "pause", disabled: true };
  return LIVE.has(s) ? { label: "Disable", icon: "pause" } : { label: "Enable", icon: "play" };
}

/* ---------- page ---------- */
export async function renderProfiles(root) {
  state.selected.clear();
  root.innerHTML = `
  <div class="page-head">
    <h1>Profiles</h1>
    <button class="btn ghost sm" id="scan-btn">${icon("search", 15)} Scan system</button>
    <button class="btn primary sm" id="import-btn">${icon("upload", 15)} Import</button>
  </div>
  <p class="page-sub">OpenVPN client profiles. Enable starts a profile's tunnel on this server and Disable stops it. Certificate expiry is flagged before anyone is locked out.</p>
  <div class="progress-line" id="tunnel-progress" role="status" hidden></div>

  <div class="card" id="import-zone">
    <div class="dropzone" id="dropzone" tabindex="0" role="button"
         aria-label="Import .ovpn files: drop them here or click to browse">
      ${icon("upload", 20)}
      <div><strong>Drop .ovpn files here</strong> or click to browse</div>
      <div class="muted small">Multiple files welcome · parsed locally · 1 MiB per file</div>
      <input type="file" id="file-input" accept=".ovpn,.conf,text/plain" multiple hidden>
    </div>
    <div class="import-chips" id="import-chips" hidden></div>
  </div>

  <div class="filterbar">
    <label class="search">${icon("search", 15)}
      <input id="profile-q" placeholder='Filter, for example tag:office status:expired cipher:AES-256-GCM' value="${esc(state.q)}">
    </label>
  </div>
  <div class="active-filters" id="active-filters"></div>

  <div class="card" style="padding:0">
    <div class="table-wrap">
      <table class="table" id="profiles-table">
        <thead><tr>
          <th style="width:28px"><input type="checkbox" id="sel-all" aria-label="Select all"></th>
          <th>Status</th><th>Name</th><th>Server</th><th>Cipher</th>
          <th>Cert expiry</th><th>Updated</th><th style="width:130px"></th>
        </tr></thead>
        <tbody></tbody>
      </table>
    </div>
    <div class="empty" id="profiles-empty" hidden></div>
  </div>`;

  const zone = $("#dropzone", root);
  const input = $("#file-input", root);
  zone.onclick = () => input.click();
  zone.onkeydown = (e) => { if (e.key === "Enter" || e.key === " ") input.click(); };
  input.onchange = () => importFiles([...input.files]);
  for (const evt of ["dragover", "dragenter"]) {
    zone.addEventListener(evt, (e) => { e.preventDefault(); zone.classList.add("over"); });
  }
  for (const evt of ["dragleave", "drop"]) {
    zone.addEventListener(evt, (e) => { e.preventDefault(); zone.classList.remove("over"); });
  }
  zone.addEventListener("drop", (e) => importFiles([...e.dataTransfer.files]));

  $("#import-btn", root).onclick = () => input.click();
  $("#scan-btn", root).onclick = openScanDialog;
  const qInput = $("#profile-q", root);
  qInput.onkeydown = (e) => {
    if (e.key === "Enter") { state.q = qInput.value.trim(); load(root); }
    if (e.key === "Escape") { qInput.value = ""; state.q = ""; load(root); }
  };
  $("#sel-all", root).onchange = (e) => {
    const on = e.target.checked;
    state.rows.forEach((r) => on ? state.selected.add(r.id) : state.selected.delete(r.id));
    drawRows(root);
  };
  $("#active-filters", root).addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-drop]");
    if (!btn) return;
    const tokens = state.q.split(/\s+/).filter(Boolean);
    tokens.splice(Number(btn.dataset.drop), 1);
    state.q = tokens.join(" ");
    load(root);
  });

  await load(root);
}

/* ---------- data ---------- */
async function load(root) {
  $("#active-filters", root).innerHTML = drawFilterChips();
  const data = await api(`/profiles${state.q ? `?q=${encodeURIComponent(state.q)}` : ""}`);
  state.rows = data.profiles;
  drawRows(root);
  const count = $("[data-count='profiles']");
  if (count) count.textContent = state.rows.length || "";
}

function drawFilterChips() {
  const tokens = state.q.split(/\s+/).filter(Boolean);
  if (!tokens.length) return "";
  return tokens.map((t, i) =>
    `<span class="chip">${esc(t)}<button data-drop="${i}" aria-label="Remove filter ${esc(t)}">${icon("x", 11)}</button></span>`
  ).join("") + `<button class="btn ghost sm" id="clear-filters">Clear</button>`;
}

function drawRows(root) {
  const tbody = $("#profiles-table tbody", root);
  const empty = $("#profiles-empty", root);
  const bulkBar = $("#bulk-bar");
  const rows = state.rows;

  if (!rows.length) {
    tbody.innerHTML = "";
    empty.hidden = false;
    empty.innerHTML = state.q
      ? `<p>No profiles match this filter.</p><button class="btn ghost sm" id="clear-q">Clear filter</button>`
      : `<p>No profiles yet. Import your .ovpn files, or scan this server for existing ones.</p><button class="btn primary sm" id="empty-import">${icon("upload", 14)} Import profiles</button>`;
    if (state.q) $("#clear-q", empty).onclick = () => { state.q = ""; load(root); };
    else $("#empty-import", empty).onclick = () => $("#file-input", root).click();
  } else {
    empty.hidden = true;
    tbody.innerHTML = rows.map((p) => {
      const server = serverOf(p) || "—";
      const toggle = toggleView(p);
      return `<tr data-id="${p.id}">
        <td><input type="checkbox" data-sel aria-label="Select ${esc(p.name)}" ${state.selected.has(p.id) ? "checked" : ""}></td>
        <td>${stateChip(p)}${p.tunnel?.ip ? `<div class="mono small faint">${esc(p.tunnel.ip)}</div>` : ""}</td>
        <td>
          <strong>${esc(p.name)}</strong>${p.name_shared ? ' <span class="badge warn">duplicate name</span>' : ""}
          <div class="tagline">${p.tags.map((t) => `<span class="chip">${esc(t)}</span>`).join("")}</div>
        </td>
        <td class="mono small">${esc(server)}${p.endpoints.length > 1 ? ` <span class="faint">+${p.endpoints.length - 1}</span>` : ""}</td>
        <td class="mono small">${esc(p.cipher || "—")}</td>
        <td>${p.cert_expires_at
          ? `<span class="small">${fmtDate(p.cert_expires_at)}</span> <span class="faint small">${relTime(p.cert_expires_at)}</span>${certBadge(p)}`
          : '<span class="faint">—</span>'}</td>
        <td class="faint small">${relTime(p.updated_at)}</td>
        <td class="row-actions">
          <button data-act="download" title="Download">${icon("download", 15)}</button>
          <button data-act="qr" title="QR code">${icon("qr", 15)}</button>
          <button data-act="edit" title="Open">${icon("pencil", 15)}</button>
          <button data-act="toggle" title="${esc(toggle.label)}" aria-label="${esc(toggle.label)} ${esc(p.name)}" ${toggle.disabled ? "disabled" : ""}>${icon(toggle.icon, 15)}</button>
          <button data-act="delete" title="Delete" class="danger">${icon("trash", 15)}</button>
        </td>
      </tr>`;
    }).join("");
  }

  // row actions + selection (event delegation)
  tbody.onclick = (e) => {
    const tr = e.target.closest("tr[data-id]");
    if (!tr) return;
    const p = state.rows.find((r) => r.id === tr.dataset.id);
    const act = e.target.closest("[data-act]")?.dataset.act;
    if (act === "download") { window.location.href = `${BASE}/api/profiles/${p.id}/download`; return; }
    if (act === "qr") { openQrModal(p.id); return; }
    if (act === "toggle") return void (e.target.closest("[data-act]").disabled ? null : toggleProfile(root, p));
    if (act === "delete") return void deleteProfile(root, p);
    openProfilesDrawer(root, p.id); // row click and the edit icon both open detail
  };
  tbody.onchange = (e) => {
    const box = e.target.closest("input[data-sel]");
    if (!box) return;
    const id = box.closest("tr").dataset.id;
    if (box.checked) state.selected.add(id); else state.selected.delete(id);
    drawRows(root);
  };
  const selAll = $("#sel-all", root);
  if (selAll) selAll.checked = rows.length > 0 && rows.every((r) => state.selected.has(r.id));

  // bulk bar while a selection exists
  const oldBar = $("#bulk-bar");
  if (oldBar) oldBar.remove();
  if (state.selected.size) {
    const bar = h(`<div class="bulk-bar" id="bulk-bar">
      <span>${state.selected.size} selected</span>
      <button class="btn danger sm">${icon("trash", 14)} Delete selected</button>
    </div>`);
    $("button", bar).onclick = () => bulkDelete(root);
    $(".content").prepend(bar);
  }
}

/* ---------- import ---------- */
async function importFiles(files) {
  if (!files.length) return;
  const chipsBox = $("#import-chips");
  chipsBox.hidden = false;
  chipsBox.innerHTML = files.map((f) =>
    `<span class="import-chip pending" data-name="${esc(f.name)}">${icon("refresh", 13)} ${esc(f.name)}: uploading…</span>`
  ).join("");

  for (const file of files) {
    const chip = chipsBox.querySelector(`[data-name="${CSS.escape(file.name)}"]`);
    try {
      const fd = new FormData();
      fd.append("files", file, file.name);
      const res = await fetch(`${BASE}/api/profiles/import`, {
        method: "POST", body: fd, credentials: "same-origin",
      });
      if (res.status === 401) { location.hash = "#/login"; return; }
      const body = (await res.json()).results?.[0];
      drawImportChip(chipsBox, chip, body);
    } catch (err) {
      chip.className = "import-chip error";
      chip.innerHTML = `${icon("x", 13)} ${esc(file.name)}: ${esc(errorText(err))}`;
    }
  }
  await load(document.getElementById("page"));
}

function drawImportChip(chipsBox, chip, body) {
  if (!body) { chip.className = "import-chip error"; chip.innerHTML = `${icon("x", 13)} upload failed`; return; }
  if (body.status === "error") {
    chip.className = "import-chip error";
    chip.innerHTML = `${icon("x", 13)} ${esc(body.name)}: ${esc(body.message || "rejected")}`;
  } else if (body.status === "duplicate") {
    chip.className = "import-chip dup";
    chip.innerHTML = `${icon("copy", 13)} ${esc(body.name)}: already exists
      <span class="muted small">same content</span>
      <button class="btn sm" data-res="replace">Replace</button>
      <button class="btn ghost sm" data-res="keep">Keep both</button>`;
    chip.querySelector('[data-res="replace"]').onclick = () => resolveDuplicate(chip, body, "replace");
    chip.querySelector('[data-res="keep"]').onclick = () => resolveDuplicate(chip, body, "keep_both");
  } else if (body.parse_error) {
    chip.className = "import-chip warn";
    chip.innerHTML = `${icon("alert", 13)} ${esc(body.name)}: imported, but ${esc(body.parse_error)}`;
  } else {
    chip.className = "import-chip ok";
    chip.innerHTML = `${icon("check", 13)} ${esc(body.name)}: parsed`;
  }
}

async function resolveDuplicate(chip, body, action) {
  try {
    await api("/profiles/import/confirm", {
      method: "POST",
      body: { stash: body.stash, action, target: action === "replace" ? body.duplicate_of : undefined },
    });
    chip.className = "import-chip ok";
    chip.innerHTML = `${icon("check", 13)} ${esc(body.name)}: ${action === "replace" ? "replaced existing" : "kept both"}`;
    await load(document.getElementById("page"));
  } catch (err) {
    chip.className = "import-chip error";
    chip.innerHTML = `${icon("x", 13)} ${esc(body.name)}: ${esc(errorText(err))}`;
  }
}

/* ---------- system scan (US2 extension): import host configs in place ---------- */
const SCAN_CHIP = {
  new: ["ok", "New"],
  imported: ["off", "Already imported"],
  error: ["err", "Parse error"],
  "too-large": ["warn", "Too large"],
  unreadable: ["err", "Unreadable"],
};

async function openScanDialog() {
  const scrim = h(`<div class="dialog-scrim" role="dialog" aria-modal="true">
    <div class="dialog wide">
      <h2>Scan system for OpenVPN configs</h2>
      <div class="body"><p class="hint" id="scan-status">Scanning /etc/openvpn, /home, /root …</p></div>
      <div class="table-wrap" style="max-height:50vh;overflow:auto">
        <table class="table" id="scan-table">
          <thead><tr><th>Found</th><th>Endpoint</th><th>Cert expiry</th><th>State</th><th></th></tr></thead>
          <tbody></tbody>
        </table>
      </div>
      <div class="btn-row">
        <button class="btn ghost" data-close>Close</button>
        <button class="btn primary" data-import-all hidden>Import all new</button>
      </div>
    </div>
  </div>`);
  document.body.appendChild(scrim);
  $("[data-close]", scrim).onclick = () => scrim.remove();
  scrim.onclick = (e) => { if (e.target === scrim) scrim.remove(); };

  let candidates = [];
  try {
    const r = await api("/profiles/scan");
    candidates = r.candidates || [];
    $("#scan-status", scrim).textContent = candidates.length
      ? `${candidates.length} config file(s) found on this host.`
      : "No .ovpn/.conf files found in the scan locations.";
  } catch (err) {
    $("#scan-status", scrim).textContent = errorText(err);
    return;
  }

  const tbody = $("#scan-table tbody", scrim);
  const draw = () => {
    if (!candidates.length) {
      tbody.innerHTML = `<tr><td colspan="5" class="faint">Nothing to import.</td></tr>`;
      return;
    }
    tbody.innerHTML = candidates.map((c, i) => {
      const [kind, label] = SCAN_CHIP[c.status] || ["off", c.status];
      const showPath = c.display_path || c.path;
      return `<tr>
        <td><span class="mono small">${esc(c.name)}</span>
            <div class="faint small mono">${esc(showPath)}</div></td>
        <td class="small mono">${esc(c.endpoint || "—")}</td>
        <td class="small">${esc(c.cert_expires_at ? c.cert_expires_at.slice(0, 10) : "—")}</td>
        <td>${status(kind, label)}${c.parse_error ? `<div class="faint small">${esc(c.parse_error)}</div>` : ""}</td>
        <td class="row-actions">${c.status === "new"
          ? `<button class="btn primary sm" data-imp="${i}">Import</button>`
          : ""}</td>
      </tr>`;
    }).join("");
    $$("[data-imp]", tbody).forEach((btn) => {
      btn.onclick = () => importCandidate(candidates[Number(btn.dataset.imp)], btn, draw);
    });
    const newCount = candidates.filter((c) => c.status === "new").length;
    $("[data-import-all]", scrim).hidden = !newCount;
    $("[data-import-all]", scrim).textContent = `Import all new (${newCount})`;
  };
  draw();

  const importAll = $("[data-import-all]", scrim);
  importAll.onclick = async () => {
    importAll.disabled = true;
    for (const c of candidates.filter((x) => x.status === "new")) {
      try {
        await api("/profiles/import-system", { method: "POST", body: { path: c.path } });
        c.status = "imported";
      } catch { /* leave as new; per-row errors surface on retry */ }
    }
    importAll.disabled = false;
    toast("Scan import finished.", "success");
    draw();
    await load(document.getElementById("page"));
  };
}

async function importCandidate(c, btn, redraw) {
  btn.disabled = true;
  try {
    const r = await api("/profiles/import-system", { method: "POST", body: { path: c.path } });
    if (r.status === "imported") {
      c.status = "imported";
      toast(`${c.name} imported.`, "success");
    } else if (r.status === "duplicate") {
      c.status = "imported";
      toast(`${c.name} was already imported.`, "info");
    }
    await load(document.getElementById("page"));
  } catch (err) {
    toast(errorText(err), "error");
    btn.disabled = false;
    return;
  }
  redraw();
}

/* ---------- mutations ---------- */
export function undoable(msg, token) {
  toast(msg, "success", {
    label: "Undo",
    run: () => api(`/undo/${token}`, { method: "POST" }),
  });
}

/* ---------- tunnel actions: Enable starts the tunnel, Disable stops it ---------- */
function infoDialog({ title, body, closeLabel = "Close" }) {
  return new Promise((resolve) => {
    const scrim = h(`<div class="dialog-scrim" role="dialog" aria-modal="true">
      <div class="dialog">
        <h2>${esc(title)}</h2>
        <div class="body">${body}</div>
        <div class="btn-row"><button class="btn" data-close>${esc(closeLabel)}</button></div>
      </div>
    </div>`);
    document.body.appendChild(scrim);
    let done = false;
    const close = () => {
      if (done) return;
      done = true;
      scrim.remove();
      restore();
      resolve();
    };
    const restore = trapKeys(scrim, close);
    $("[data-close]", scrim).onclick = close;
    scrim.onclick = (e) => { if (e.target === scrim) close(); };
    $("[data-close]", scrim).focus();
  });
}

const findingList = (list) => `<ul class="plan-lines">${list.map((f) =>
  `<li><span class="mono">${esc(f.text)}</span><span class="faint small"> line ${f.line_no}: ${esc(f.why)}</span></li>`
).join("")}</ul>`;

/* A failed request, in a dialog: these messages name lines and files, so a toast is too brief. */
function problem(title, err) {
  const list = err?.detail?.findings?.length ? findingList(err.detail.findings) : "";
  return infoDialog({ title, body: `<p>${esc(errorText(err))}</p>${list}` });
}

function planBody(p, plan) {
  const where = serverOf(p);
  return `<p>Starts a tunnel from this server${where ? ` to <span class="mono">${esc(where)}</span>` : ""}
      and starts it again after a reboot, once it has connected.</p>
    <ul class="plan-list">${plan.notices.map((n) => `<li>${esc(n)}</li>`).join("")}
      <li>If the server has not answered within ${esc(String(plan.wait_seconds))} seconds, the tunnel is stopped and nothing is left running.</li></ul>
    <p class="small faint">Service <span class="mono">${esc(plan.unit)}</span>, interface
      <span class="mono">${esc(plan.iface)}</span>, config
      <span class="mono">/etc/openvpn/client/${esc(plan.instance)}.conf</span></p>
    ${plan.scripts.length
      ? `<p><strong>This profile runs commands as root on this server:</strong></p>${findingList(plan.scripts)}
         <p class="small">Enable it only if you wrote these lines or trust whoever did.</p>`
      : ""}`;
}

/* "…did not come up. Last log lines: a | b" becomes a sentence and a small log block. */
function detailHtml(detail) {
  const [lead, tail] = String(detail).split("Last log lines: ");
  if (tail === undefined) return `<p>${esc(detail)}</p>`;
  return `<p>${esc(lead.trim())}</p><p class="small faint">Last log lines</p>
    <pre class="log-tail">${esc(tail.split(" | ").join("\n"))}</pre>`;
}

/* Follows a start/stop job to the end. The progress line shows on the Profiles page (or wherever the
   caller points it); the outcome is a toast when it worked and a dialog when it did not. */
async function followTunnelJob(jobId, p, kind, opts = {}) {
  const name = p.name;
  if (following.has(jobId)) return null;
  following.add(jobId);
  const started = Date.now();
  let lastLoad = 0;
  const strip = () => document.getElementById("tunnel-progress");
  const show = opts.progress || ((text, secs) => {
    const bar = strip();
    if (!bar) return;
    bar.hidden = false;
    bar.innerHTML = `<span class="spin">${icon("refresh", 15)}</span><span>${esc(text)}</span><span class="faint small">${secs} s</span>`;
  });
  let job = null;
  try {
    for (;;) {
      try { job = await api(`/jobs/${jobId}`); } catch { /* a missed poll: keep waiting */ }
      const secs = Math.round((Date.now() - started) / 1000);
      if (job?.done) break;
      show(job?.detail || `Working on ${name}…`, secs);
      if (Date.now() - lastLoad > 2000 && document.getElementById("profiles-table")) {
        lastLoad = Date.now();
        await load(document.getElementById("page"));
      }
      if (secs > 180) { toast(`${name}: still working. Check its status in the table.`, "warn"); return null; }
      await sleep(1000);
    }
  } finally {
    following.delete(jobId);
    pending.delete(p.id);
    const bar = strip();
    if (bar) bar.hidden = true;
  }
  if (document.getElementById("profiles-table")) await load(document.getElementById("page"));
  if (opts.onDone) await opts.onDone(job);
  if (job.ok) toast(`${name}: ${job.detail}`, "success");
  else if (job.state === "superseded") { /* a newer click took over; its own result follows */ }
  else {
    await infoDialog({
      title: kind === "stop" ? `Could not stop ${name}` : `${name} did not connect`,
      body: detailHtml(job.detail),
    });
  }
  return job;
}

/* Enable: ask the server what it would do, show that, confirm, then start the tunnel.
   Returns true once the start is under way. */
async function enableProfile(root, p) {
  let info;
  try { info = await api(`/profiles/${p.id}/tunnel`); }
  catch (err) { await problem(`Could not check ${p.name}`, err); return false; }
  const plan = info.plan;
  if (UP.has(info.tunnel.state)) { toast(`${p.name} is already running.`, "info"); await load(root); return false; }
  if (!plan.available) {
    await infoDialog({
      title: "Tunnel folder not available",
      body: `<p>The console cannot write tunnel configs on this server because /etc/openvpn/client is not mounted into it.
             Set VPNCONSOLE_TUNNEL_DIR and add the mount described in deploy/README-deploy.md, then restart the console.</p>`,
    });
    return false;
  }
  if (plan.blocked) {
    await infoDialog({ title: `${p.name} cannot be enabled`, body: `<p>${esc(plan.blocked)}</p>` });
    return false;
  }
  if (plan.refused.length) {
    await infoDialog({
      title: `${p.name} cannot run as a server tunnel`,
      body: `<p>A tunnel on this server has to start without anyone typing a password or supplying a file, and
             these lines prevent that:</p>${findingList(plan.refused)}
             <p>Fix them in the config editor, then enable it again.</p>`,
    });
    return false;
  }
  const scripts = plan.needs_typed_confirm;
  const body = planBody(p, plan);
  const ok = scripts
    ? await typeConfirmDialog({ title: `Enable ${p.name} and run its scripts?`, body, phrase: p.name, confirmLabel: "Enable and run scripts" })
    : await confirmDialog({ title: `Enable ${p.name}?`, body, confirmLabel: "Enable and start tunnel" });
  if (!ok) return false;
  try {
    const data = await api(`/profiles/${p.id}`, {
      method: "PATCH",
      body: { enabled: true, confirm: true, ...(scripts ? { typed_confirm: p.name } : {}) },
    });
    pending.set(p.id, "Starting");
    await load(root);
    if (data.job_id) followTunnelJob(data.job_id, p, "start");
    else pending.delete(p.id);
    return true;
  } catch (err) {
    await problem(`Could not enable ${p.name}`, err);
    await load(root);
    return false;
  }
}

/* Disable: stop the tunnel and turn its start on boot off. Returns true once it is under way. */
async function disableProfile(root, p) {
  const live = UP.has(tunnelOf(p));
  const ok = await confirmDialog({
    title: `Disable ${p.name}?`,
    body: live
      ? `<p>Stops the tunnel${p.tunnel.ip ? ` (<span class="mono">${esc(p.tunnel.ip)}</span>)` : ""} and stops it starting on boot.
         Anything on this server that uses it loses that connection now.</p>
         <p>The profile and its config stay in the console, so you can enable it again.</p>`
      : `<p>Turns off the tunnel's start on boot and clears its failed state.
         The profile and its config stay in the console.</p>`,
    confirmLabel: live ? "Disable and stop tunnel" : "Disable",
  });
  if (!ok) return false;
  try {
    const data = await api(`/profiles/${p.id}`, { method: "PATCH", body: { enabled: false, confirm: true } });
    if (data.job_id) pending.set(p.id, "Stopping");
    await load(root);
    if (data.job_id) followTunnelJob(data.job_id, p, "stop");
    else if (data.undo_token) undoable(`${p.name} disabled.`, data.undo_token);
    return true;
  } catch (err) {
    await problem(`Could not disable ${p.name}`, err);
    await load(root);
    return false;
  }
}

function toggleProfile(root, p) {
  return LIVE.has(tunnelOf(p)) ? disableProfile(root, p) : enableProfile(root, p);
}

async function deleteProfile(root, p) {
  const left = p.tunnel && !["none", "unknown"].includes(p.tunnel.state);
  const yes = await confirmDialog({
    title: "Delete profile",
    body: `<p>Deletes <strong>${esc(p.name)}</strong> and any share links pointing at it.
           The .ovpn file is removed from the console. This cannot be undone.</p>
           ${left ? `<p><strong>Its server tunnel is not touched.</strong> <span class="mono">${esc(p.tunnel.unit)}</span>
           stays as it is and its config stays in /etc/openvpn/client. Disable the profile first if you want the tunnel stopped.</p>` : ""}`,
    confirmLabel: "Delete profile", danger: true,
  });
  if (!yes) return false;
  try {
    const out = await api(`/profiles/${p.id}`, { method: "DELETE", body: { confirm: true } });
    toast(`${p.name} deleted.${out.tunnel_left ? ` Tunnel ${out.tunnel_left} was left as it is.` : ""}`, "success");
    state.selected.delete(p.id);
    await load(root);
    return true;
  } catch (err) { toast(errorText(err), "error"); return false; }
}

async function bulkDelete(root) {
  const n = state.selected.size;
  const yes = await typeConfirmDialog({
    title: "Delete profiles",
    body: `<p>Permanently deletes <strong>${n} profiles</strong> and their share links from the console.</p>
           <p>Server tunnels they started are not stopped. Disable a profile first if its tunnel should go.</p>`,
    phrase: "DELETE", confirmLabel: `Delete ${n} profiles`,
  });
  if (!yes) return;
  try {
    const out = await api("/profiles/bulk-delete", {
      method: "POST", body: { ids: [...state.selected], typed_confirm: "DELETE" },
    });
    toast(`${out.deleted} profiles deleted.`, "success");
    state.selected.clear();
    await load(root);
  } catch (err) { toast(errorText(err), "error"); }
}

/* ---------- drawer (detail + editor) ---------- */
export async function openProfilesDrawer(root, pid) {
  let p;
  try { p = await api(`/profiles/${pid}`); }
  catch (err) { toast(errorText(err), "error"); return; }

  const scrim = h(`<div class="drawer-scrim"></div>`);
  const drawer = h(`<aside class="drawer" role="dialog" aria-modal="true" aria-label="${esc(p.name)}">
    <header>
      <h2>${esc(p.name)}</h2>
      <span data-state-chip>${stateChip(p)}</span>
      <button class="btn ghost sm" data-close aria-label="Close">${icon("x", 15)}</button>
    </header>
    <div class="body">
      <dl class="kv">
        <dt>Servers</dt><dd>${p.endpoints.map((e) =>
          `<span class="mono">${esc(`${e.host}:${e.port}${e.proto ? `/${e.proto}` : ""}`)}</span>`).join("<br>") || "—"}</dd>
        <dt>Cipher</dt><dd class="mono">${esc(p.cipher || "—")}${p.tls_version_min ? ` · TLS ≥ ${esc(p.tls_version_min)}` : ""}</dd>
        <dt>Auth</dt><dd>${p.has_auth_user_pass ? "user + password" : "certificate only"}</dd>
        <dt>Cert expiry</dt><dd>${p.cert_expires_at ? `${fmtDate(p.cert_expires_at)} <span class="faint">(${relTime(p.cert_expires_at)})</span>` : "—"}</dd>
        <dt>Size</dt><dd>${(p.size_bytes / 1024).toFixed(1)} KiB</dd>
        <dt>Updated</dt><dd>${fmtDate(p.updated_at)}</dd>
      </dl>

      <div class="field">
        <label>Server tunnel</label>
        <div class="tunnel-box" data-tunnel-box><p class="faint small" style="margin:0">Checking the server…</p></div>
        <div class="progress-line" data-tunnel-progress hidden role="status"></div>
      </div>

      <div class="field">
        <label>Tags</label>
        <div class="tag-editor" data-tags></div>
      </div>

      <div class="field">
        <label>Config <span class="faint">(edits keep the previous version)</span></label>
        <textarea class="code-editor" data-config spellcheck="false"></textarea>
        <div class="btn-row" style="margin-top:8px">
          <button class="btn primary sm" data-save>Save changes</button>
          ${p.previous_sha256 ? `<button class="btn ghost sm" data-revert>${icon("undo", 14)} Revert to previous</button>` : ""}
          <button class="btn ghost sm" data-copy>${icon("copy", 14)} Copy</button>
        </div>
        <p class="hint" data-save-hint></p>
      </div>

      <div class="field">
        <label>Sharing</label>
        <p class="muted small" style="margin:0 0 8px">Time-boxed links that download this profile without signing in. One-time links die after the first download.</p>
        <div class="btn-row" style="margin-bottom:8px">
          <button class="btn sm" data-share-create>${icon("link", 14)} Create link</button>
          <label class="checkbox small"><input type="checkbox" data-share-onetime> one-time</label>
          <select class="input" data-share-hours style="width:auto" aria-label="Link expiry">
            <option value="1">1 hour</option>
            <option value="24" selected>24 hours</option>
            <option value="168">7 days</option>
          </select>
          <button class="btn ghost sm" data-share-qr>${icon("qr", 14)} Show QR</button>
        </div>
        <div class="share-list" data-share-list></div>
      </div>
    </div>
    <footer class="btn-row" style="padding:12px 18px;border-top:1px solid var(--border)">
      <a class="btn ghost sm" href="${BASE}/api/profiles/${p.id}/download" download="${esc(p.name)}.ovpn">${icon("download", 14)} Download</a>
      <button class="btn sm" data-toggle></button>
      <button class="btn ghost sm" data-retry hidden>${icon("refresh", 14)} Try again</button>
      <div style="flex:1"></div>
      <button class="btn danger sm" data-delete>${icon("trash", 14)} Delete</button>
    </footer>
  </aside>`);

  document.body.append(scrim, drawer);
  const close = () => { scrim.remove(); drawer.remove(); };
  $("[data-close]", drawer).onclick = close;
  scrim.onclick = close;

  const tagsBox = $("[data-tags]", drawer);
  const drawTags = () => {
    tagsBox.innerHTML = p.tags.map((t, i) =>
      `<span class="chip">${esc(t)}<button data-i="${i}" aria-label="Remove ${esc(t)}">${icon("x", 11)}</button></span>`
    ).join("") + `<input class="tag-input" placeholder="add tag ↵" aria-label="Add tag">`;
    $$("button[data-i]", tagsBox).forEach((b) => (b.onclick = async () => {
      p.tags.splice(Number(b.dataset.i), 1);
      await saveTags();
    }));
  };
  const saveTags = async () => {
    try {
      const data = await api(`/profiles/${p.id}`, { method: "PATCH", body: { tags: p.tags } });
      p = { ...p, ...data.profile };
      drawTags();
      await load(root);
    } catch (err) { toast(errorText(err), "error"); }
  };
  tagsBox.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && e.target.classList.contains("tag-input")) {
      const v = e.target.value.trim();
      if (v && !p.tags.includes(v)) p.tags.push(v);
      saveTags();
    }
  });
  drawTags();

  const config = $("[data-config]", drawer);
  config.value = p.config_text;

  /* --- server tunnel: state, log, and the Enable/Disable buttons --- */
  const box = $("[data-tunnel-box]", drawer);
  const saveHint = $("[data-save-hint]", drawer);
  const toggleBtn = $("[data-toggle]", drawer);
  const retryBtn = $("[data-retry]", drawer);
  const progressEl = $("[data-tunnel-progress]", drawer);
  const setBoxProgress = (text, secs) => {
    progressEl.hidden = false;
    progressEl.innerHTML = `<span class="spin">${icon("refresh", 15)}</span><span>${esc(text)}</span><span class="faint small">${secs} s</span>`;
  };
  const drawFooter = () => {
    const v = toggleView(p);
    toggleBtn.innerHTML = `${icon(v.icon, 14)} ${esc(v.label)}`;
    toggleBtn.disabled = Boolean(v.disabled);
    retryBtn.hidden = tunnelOf(p) !== "failed";
    $("[data-state-chip]", drawer).innerHTML = stateChip(p);
    saveHint.textContent = UP.has(tunnelOf(p)) ? "Saving applies this config and restarts the running tunnel." : "";
  };
  const drawTunnel = (info) => {
    const t = info.tunnel;
    if (t.state === "none") {
      box.innerHTML = `<p class="muted small" style="margin:0">No tunnel yet. Enable starts one from this server and starts it
        again after a reboot, once it has connected. It would run as <span class="mono">${esc(info.plan.unit)}</span>
        on interface <span class="mono">${esc(info.plan.iface)}</span>.</p>`;
    } else if (t.state === "unknown") {
      box.innerHTML = `<p class="muted small" style="margin:0">The server's service state cannot be read right now.</p>`;
    } else {
      const log = (info.log_tail || []).map((l) => {
        const at = new Date(Number(l.ts) / 1000);
        const when = Number.isNaN(at.getTime()) ? "" : `${at.toLocaleTimeString()}  `;
        return `${when}${l.msg}`;
      }).join("\n");
      box.innerHTML = `<div class="tunnel-state">${stateChip({ ...p, tunnel: t })}
          ${t.ip ? `<span class="mono small">${esc(t.ip)}</span>` : ""}
          ${t.since ? `<span class="faint small">since ${esc(t.since)}</span>` : ""}</div>
        <dl class="kv compact">
          <dt>Service</dt><dd class="mono">${esc(t.unit)}</dd>
          <dt>Interface</dt><dd class="mono">${esc(t.iface)}</dd>
          <dt>After a reboot</dt><dd>${t.boot ? "Reconnects by itself" : "Stays off"}</dd>
        </dl>
        ${log ? `<pre class="log-tail" tabindex="0">${esc(log)}</pre>` : ""}`;
    }
  };
  const refreshTunnel = async () => {
    try {
      const info = await api(`/profiles/${p.id}/tunnel`);
      p = { ...p, tunnel: info.tunnel };
      drawTunnel(info);
      drawFooter();
    } catch (err) { box.innerHTML = `<p class="faint small" style="margin:0">${esc(errorText(err))}</p>`; }
  };
  drawFooter();
  refreshTunnel();

  /* A running tunnel is restarted by a save or a revert, so those ask first (the server insists too). */
  const confirmed = async (send, spec) => {
    if (UP.has(tunnelOf(p))) {
      if (!(await confirmDialog(spec))) return null;
      return send({ confirm: true });
    }
    try { return await send({}); }
    catch (err) {
      if (err.code !== "confirm_required") throw err;
      if (!(await confirmDialog(spec))) return null;
      return send({ confirm: true });
    }
  };
  const restartSpec = (verb) => ({
    title: `${verb} and restart ${p.name}?`,
    body: `<p>The tunnel for <strong>${esc(p.name)}</strong> is running. This applies the config to the server and restarts it,
           so traffic over the tunnel stops for a few seconds.</p>
           <p>If the restarted tunnel does not connect, undo the change or revert to the previous version.</p>`,
    confirmLabel: `${verb} and restart`,
  });
  /* What happened on the server after a save, an undo or a revert. */
  const afterSync = async (data) => {
    const sync = data.tunnel_sync;
    if (data.notices?.length) toast(data.notices.join(" "), "info");
    if (sync && sync.applied === false) {
      await infoDialog({ title: "Saved, but not applied to the server", body: `<p>${esc(sync.reason)}</p>` });
    }
    if (data.job_id) {
      followTunnelJob(data.job_id, p, "restart", {
        progress: setBoxProgress,
        onDone: () => { progressEl.hidden = true; return refreshTunnel(); },
      });
    } else {
      refreshTunnel();
    }
  };

  $("[data-save]", drawer).onclick = async () => {
    if (config.value === p.config_text) { toast("No changes to save.", "info"); return; }
    try {
      const data = await confirmed(
        (extra) => api(`/profiles/${p.id}`, { method: "PATCH", body: { config_text: config.value, ...extra } }),
        restartSpec("Save"));
      if (!data) return;
      p = { ...p, ...data.profile };
      const restarting = data.tunnel_sync?.restarted;
      const msg = `Config saved. The previous version is kept.${restarting ? " The tunnel is restarting." : ""}`;
      if (data.undo_token) undoable(msg, data.undo_token); else toast(msg, "success");
      $("[data-revert]", drawer)?.remove();
      const footerBtns = $(".btn-row", drawer);
      if (!footerBtns.querySelector("[data-revert]")) {
        const b = h(`<button class="btn ghost sm" data-revert>${icon("undo", 14)} Revert to previous</button>`);
        b.onclick = doRevert;
        footerBtns.prepend(b);
      }
      await load(root);
      await afterSync(data);
    } catch (err) { await problem("Could not save the config", err); }
  };
  const doRevert = async () => {
    try {
      const data = await confirmed(
        (extra) => api(`/profiles/${p.id}/revert`, { method: "POST", body: extra }),
        restartSpec("Revert"));
      if (!data) return;
      p = { ...p, ...data.profile };
      config.value = p.config_text;
      toast("Reverted to the previous version.", "success");
      await load(root);
      await afterSync(data);
    } catch (err) { await problem("Could not revert the config", err); }
  };
  const revertBtn = $("[data-revert]", drawer);
  if (revertBtn) revertBtn.onclick = doRevert;
  $("[data-copy]", drawer).onclick = () => copyText(config.value, "Config copied");

  toggleBtn.onclick = async () => { if (await toggleProfile(root, p)) close(); };
  retryBtn.onclick = async () => { if (await enableProfile(root, p)) close(); };
  $("[data-delete]", drawer).onclick = async () => { if (await deleteProfile(root, p)) close(); };

  /* --- sharing (US3) --- */
  const shareList = $("[data-share-list]", drawer);
  const SHARE_STATUS = { active: "ok", expired: "off", used: "warn", revoked: "off" };
  const drawShares = async () => {
    try {
      const { links } = await api(`/profiles/${p.id}/shares`);
      shareList.innerHTML = links.length ? links.map((l) => `
        <div class="share-row">
          ${status(SHARE_STATUS[l.status] || "off", l.status)}
          <span class="small mono" title="${esc(l.token)}">…${esc(l.token.slice(-6))}</span>
          <span class="faint small">${l.one_time ? "one-time · " : ""}${l.status === "active" ? `expires ${relTime(l.expires_at)}` : l.status}</span>
          <span style="flex:1"></span>
          ${l.status === "active" ? `<button class="btn ghost sm" data-copy-link="${esc(l.url)}">${icon("copy", 13)} Copy</button>` : ""}
          ${l.status === "active" ? `<button class="btn ghost sm" data-revoke="${esc(l.token)}">${icon("x", 13)} Revoke</button>` : ""}
        </div>`).join("")
        : `<p class="faint small" style="margin:4px 0">No links yet.</p>`;
      $$("[data-copy-link]", shareList).forEach((b) => {
        b.onclick = () => copyText(`${location.origin}${BASE}${b.dataset.copyLink}`, "Link copied");
      });
      $$("[data-revoke]", shareList).forEach((b) => {
        b.onclick = async () => {
          try {
            await api(`/shares/${b.dataset.revoke}`, { method: "DELETE" });
            toast("Link revoked.", "success");
            drawShares();
          } catch (err) { toast(errorText(err), "error"); }
        };
      });
    } catch (err) { shareList.innerHTML = `<p class="faint small">${esc(errorText(err))}</p>`; }
  };
  drawShares();

  $("[data-share-create]", drawer).onclick = async () => {
    try {
      const link = await api(`/profiles/${p.id}/share`, {
        method: "POST",
        body: {
          expires_hours: Number($("[data-share-hours]", drawer).value),
          one_time: $("[data-share-onetime]", drawer).checked,
        },
      });
      await copyText(`${location.origin}${BASE}${link.url}`, "Link created and copied");
      drawShares();
    } catch (err) { toast(errorText(err), "error"); }
  };

  $("[data-share-qr]", drawer).onclick = () => openQrModal(p.id);
}

/* QR modal: url mode default, embed-config fallback toggle (FR-023). */
export function openQrModal(pid) {
  const scrim = h(`<div class="dialog-scrim" role="dialog" aria-modal="true">
    <div class="dialog" style="text-align:center">
      <h2>Scan to download</h2>
      <div class="qr-box"><img alt="Profile QR code" src="${BASE}/api/profiles/${pid}/qr"></div>
      <div class="btn-row" style="justify-content:center">
        <button class="btn ghost sm" data-mode="url">URL</button>
        <button class="btn ghost sm" data-mode="embed">Embed config</button>
      </div>
      <p class="muted small">URL mode encodes a share link. Embed mode puts the whole config in the code, so scan it from a large screen.</p>
      <div class="btn-row"><button class="btn ghost" data-close>Close</button></div>
    </div>
  </div>`);
  document.body.appendChild(scrim);
  const img = $("img", scrim);
  $$("[data-mode]", scrim).forEach((b) => {
    b.onclick = () => { img.src = `${BASE}/api/profiles/${pid}/qr?mode=${b.dataset.mode}`; };
  });
  $("[data-close]", scrim).onclick = () => scrim.remove();
  scrim.onclick = (e) => { if (e.target === scrim) scrim.remove(); };
}

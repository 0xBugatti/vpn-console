/* Profiles page (US2): import (drag-drop + parse chips + duplicate resolve),
   filterable table, detail drawer with raw editor / revert / undo tier. */
import {
  api, toast, errorText, esc, h, $, $$, status, relTime, fmtDate,
  confirmDialog, typeConfirmDialog, icon, copyText,
} from "../app.js";

const STATUS_KIND = {
  Valid: "ok", Expiring: "warn", Expired: "err", Disabled: "off", "Parse error": "err",
};

const state = { q: "", rows: [], selected: new Set() };

/* ---------- page ---------- */
export async function renderProfiles(root) {
  state.selected.clear();
  root.innerHTML = `
  <div class="page-head">
    <h1>Profiles</h1>
    <button class="btn ghost sm" id="scan-btn">${icon("search", 15)} Scan system</button>
    <button class="btn primary sm" id="import-btn">${icon("upload", 15)} Import</button>
  </div>
  <p class="page-sub">OpenVPN client profiles. Status comes from the embedded certificate — expired profiles are flagged before your users hit them.</p>

  <div class="card" id="import-zone">
    <div class="dropzone" id="dropzone" tabindex="0" role="button"
         aria-label="Import .ovpn files — drop them here or click to browse">
      ${icon("upload", 20)}
      <div><strong>Drop .ovpn files here</strong> or click to browse</div>
      <div class="muted small">Multiple files welcome · parsed locally · 1 MiB per file</div>
      <input type="file" id="file-input" accept=".ovpn,.conf,text/plain" multiple hidden>
    </div>
    <div class="import-chips" id="import-chips" hidden></div>
  </div>

  <div class="filterbar">
    <label class="search">${icon("search", 15)}
      <input id="profile-q" placeholder='Filter — try tag:office status:expired cipher:AES-256-GCM' value="${esc(state.q)}">
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
      : `<p>No profiles yet — import your .ovpn files to get started.</p><button class="btn primary sm" id="empty-import">${icon("upload", 14)} Import profiles</button>`;
    if (state.q) $("#clear-q", empty).onclick = () => { state.q = ""; load(root); };
    else $("#empty-import", empty).onclick = () => $("#file-input", root).click();
  } else {
    empty.hidden = true;
    tbody.innerHTML = rows.map((p) => {
      const ep = p.endpoints[0];
      const server = ep ? `${ep.host}:${ep.port}${ep.proto ? `/${ep.proto}` : ""}` : "—";
      return `<tr data-id="${p.id}">
        <td><input type="checkbox" data-sel aria-label="Select ${esc(p.name)}" ${state.selected.has(p.id) ? "checked" : ""}></td>
        <td>${status(STATUS_KIND[p.status] || "off", p.status)}</td>
        <td>
          <strong>${esc(p.name)}</strong>${p.name_shared ? ' <span class="badge warn">duplicate name</span>' : ""}
          <div class="tagline">${p.tags.map((t) => `<span class="chip">${esc(t)}</span>`).join("")}</div>
        </td>
        <td class="mono small">${esc(server)}${p.endpoints.length > 1 ? ` <span class="faint">+${p.endpoints.length - 1}</span>` : ""}</td>
        <td class="mono small">${esc(p.cipher || "—")}</td>
        <td>${p.cert_expires_at
          ? `<span class="small">${fmtDate(p.cert_expires_at)}</span> <span class="faint small">${relTime(p.cert_expires_at)}</span>`
          : '<span class="faint">—</span>'}</td>
        <td class="faint small">${relTime(p.updated_at)}</td>
        <td class="row-actions">
          <button data-act="download" title="Download">${icon("download", 15)}</button>
          <button data-act="qr" title="QR code">${icon("qr", 15)}</button>
          <button data-act="edit" title="Open">${icon("pencil", 15)}</button>
          <button data-act="toggle" title="${p.enabled ? "Disable" : "Enable"}">${icon(p.enabled ? "pause" : "play", 15)}</button>
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
    if (act === "download") { window.location.href = `/api/profiles/${p.id}/download`; return; }
    if (act === "qr") { openQrModal(p.id); return; }
    if (act === "toggle") return void toggleProfile(root, p);
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
    `<span class="import-chip pending" data-name="${esc(f.name)}">${icon("refresh", 13)} ${esc(f.name)} — uploading…</span>`
  ).join("");

  for (const file of files) {
    const chip = chipsBox.querySelector(`[data-name="${CSS.escape(file.name)}"]`);
    try {
      const fd = new FormData();
      fd.append("files", file, file.name);
      const res = await fetch("/api/profiles/import", {
        method: "POST", body: fd, credentials: "same-origin",
      });
      if (res.status === 401) { location.hash = "#/login"; return; }
      const body = (await res.json()).results?.[0];
      drawImportChip(chipsBox, chip, body);
    } catch (err) {
      chip.className = "import-chip error";
      chip.innerHTML = `${icon("x", 13)} ${esc(file.name)} — ${esc(errorText(err))}`;
    }
  }
  await load(document.getElementById("page"));
}

function drawImportChip(chipsBox, chip, body) {
  if (!body) { chip.className = "import-chip error"; chip.innerHTML = `${icon("x", 13)} upload failed`; return; }
  if (body.status === "error") {
    chip.className = "import-chip error";
    chip.innerHTML = `${icon("x", 13)} ${esc(body.name)} — ${esc(body.message || "rejected")}`;
  } else if (body.status === "duplicate") {
    chip.className = "import-chip dup";
    chip.innerHTML = `${icon("copy", 13)} ${esc(body.name)} — already exists
      <span class="muted small">same content</span>
      <button class="btn sm" data-res="replace">Replace</button>
      <button class="btn ghost sm" data-res="keep">Keep both</button>`;
    chip.querySelector('[data-res="replace"]').onclick = () => resolveDuplicate(chip, body, "replace");
    chip.querySelector('[data-res="keep"]').onclick = () => resolveDuplicate(chip, body, "keep_both");
  } else if (body.parse_error) {
    chip.className = "import-chip warn";
    chip.innerHTML = `${icon("alert", 13)} ${esc(body.name)} — imported, but ${esc(body.parse_error)}`;
  } else {
    chip.className = "import-chip ok";
    chip.innerHTML = `${icon("check", 13)} ${esc(body.name)} — parsed`;
  }
}

async function resolveDuplicate(chip, body, action) {
  try {
    await api("/profiles/import/confirm", {
      method: "POST",
      body: { stash: body.stash, action, target: action === "replace" ? body.duplicate_of : undefined },
    });
    chip.className = "import-chip ok";
    chip.innerHTML = `${icon("check", 13)} ${esc(body.name)} — ${action === "replace" ? "replaced existing" : "kept both"}`;
    await load(document.getElementById("page"));
  } catch (err) {
    chip.className = "import-chip error";
    chip.innerHTML = `${icon("x", 13)} ${esc(body.name)} — ${esc(errorText(err))}`;
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

async function toggleProfile(root, p) {
  try {
    const data = await api(`/profiles/${p.id}`, {
      method: "PATCH", body: { enabled: !p.enabled },
    });
    undoable(`${data.profile.name} ${data.profile.enabled ? "enabled" : "disabled"}.`, data.undo_token);
    await load(root);
  } catch (err) { toast(errorText(err), "error"); }
}

async function deleteProfile(root, p) {
  const yes = await confirmDialog({
    title: "Delete profile",
    body: `Deletes <strong>${esc(p.name)}</strong> and any share links pointing at it.
           The .ovpn file is removed from the server. This cannot be undone.`,
    confirmLabel: "Delete profile", danger: true,
  });
  if (!yes) return;
  try {
    await api(`/profiles/${p.id}`, { method: "DELETE", body: { confirm: true } });
    toast(`${p.name} deleted.`, "success");
    state.selected.delete(p.id);
    await load(root);
  } catch (err) { toast(errorText(err), "error"); }
}

async function bulkDelete(root) {
  const n = state.selected.size;
  const yes = await typeConfirmDialog({
    title: "Delete profiles",
    body: `Permanently deletes <strong>${n} profiles</strong> and their share links.`,
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
      ${status(STATUS_KIND[p.status] || "off", p.status)}
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
      <a class="btn ghost sm" href="/api/profiles/${p.id}/download" download="${esc(p.name)}.ovpn">${icon("download", 14)} Download</a>
      <button class="btn sm" data-toggle>${p.enabled ? `${icon("pause", 14)} Disable` : `${icon("play", 14)} Enable`}</button>
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
  $("[data-save]", drawer).onclick = async () => {
    try {
      const data = await api(`/profiles/${p.id}`, {
        method: "PATCH", body: { config_text: config.value },
      });
      p = { ...p, ...data.profile };
      undoable("Config saved — previous version kept.", data.undo_token);
      $("[data-revert]", drawer)?.remove();
      const footerBtns = $(".btn-row", drawer);
      if (!footerBtns.querySelector("[data-revert]")) {
        const b = h(`<button class="btn ghost sm" data-revert>${icon("undo", 14)} Revert to previous</button>`);
        b.onclick = doRevert;
        footerBtns.prepend(b);
      }
      await load(root);
    } catch (err) { toast(errorText(err), "error"); }
  };
  const doRevert = async () => {
    try {
      const data = await api(`/profiles/${p.id}/revert`, { method: "POST" });
      p = { ...p, ...data.profile };
      config.value = p.config_text;
      toast("Reverted to the previous version.", "success");
      await load(root);
    } catch (err) { toast(errorText(err), "error"); }
  };
  const revertBtn = $("[data-revert]", drawer);
  if (revertBtn) revertBtn.onclick = doRevert;
  $("[data-copy]", drawer).onclick = () => copyText(config.value, "Config copied");

  $("[data-toggle]", drawer).onclick = async () => {
    await toggleProfile(root, p);
    close();
  };
  $("[data-delete]", drawer).onclick = async () => {
    await deleteProfile(root, p);
    close();
  };

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
        b.onclick = () => copyText(`${location.origin}${b.dataset.copyLink}`, "Link copied");
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
      await copyText(`${location.origin}${link.url}`, "Link created and copied");
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
      <div class="qr-box"><img alt="Profile QR code" src="/api/profiles/${pid}/qr"></div>
      <div class="btn-row" style="justify-content:center">
        <button class="btn ghost sm" data-mode="url">URL</button>
        <button class="btn ghost sm" data-mode="embed">Embed config</button>
      </div>
      <p class="muted small">URL mode encodes a share link. Embed mode puts the whole config in the code — use only on large screens.</p>
      <div class="btn-row"><button class="btn ghost" data-close>Close</button></div>
    </div>
  </div>`);
  document.body.appendChild(scrim);
  const img = $("img", scrim);
  $$("[data-mode]", scrim).forEach((b) => {
    b.onclick = () => { img.src = `/api/profiles/${pid}/qr?mode=${b.dataset.mode}`; };
  });
  $("[data-close]", scrim).onclick = () => scrim.remove();
  scrim.onclick = (e) => { if (e.target === scrim) scrim.remove(); };
}

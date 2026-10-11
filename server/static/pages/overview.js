/* Overview page (US6): attention queue → five stat tiles → quick actions →
   recent activity. Answers "is anything wrong?" in one glance (FR-030..032). */
import {
  api, toast, errorText, esc, h, $, $$, status, relTime, fmtDate,
  healthBanner, icon, copyText, every,
} from "../app.js";

const SEV = { red: ["err", "Broken"], amber: ["warn", "Due"] };

const OUTCOME_KIND = { ok: "ok", failed: "err", undone: "info", duplicate: "warn" };

export async function renderOverview(root) {
  root.innerHTML = `
  <div class="page-head">
    <h1>Overview</h1>
    <div class="qa-row" id="qa-row"></div>
  </div>
  <p class="page-sub">Everything that needs you, in one place — the rest can wait.</p>
  <div id="ov-banner"></div>

  <section class="card" id="attention-card">
    <h2>Needs attention</h2>
    <div id="attention-list" aria-live="polite"></div>
  </section>

  <div class="stat-row" id="tiles"></div>

  <section class="card" id="ips-card" hidden>
    <h2>Server addresses</h2>
    <div id="ips-rows" class="ip-rows"></div>
  </section>

  <section class="card">
    <h2>Recent activity</h2>
    <div class="table-wrap">
      <table class="table" id="recent-table">
        <thead><tr><th>When</th><th>Action</th><th>Target</th><th>Result</th></tr></thead>
        <tbody></tbody>
      </table>
    </div>
  </section>`;

  drawQuickActions();
  await loadOverview(root);
  every(15000, () => loadOverview(root, true));
}

async function loadOverview(root, silent = false) {
  let data;
  try { data = await api("/overview"); }
  catch (err) { if (!silent) toast(errorText(err), "error"); return; }

  $("#ov-banner", root).innerHTML = worstBanner(data);
  drawAttention(data.attention);
  drawTiles(data.tiles, data.attention, data.vpn_services);
  drawIps(data.ips);
  drawRecent(data.recent);
}

/* ---------- server addresses ---------- */
function drawIps(ips) {
  const rows = [
    ["Public IPv4", ips?.public],
    ["Tailscale IP", ips?.tailscale],
  ].filter(([, v]) => v);
  if (!rows.length) return;
  const card = $("#ips-card");
  card.hidden = false;
  $("#ips-rows", card).innerHTML = rows.map(([label, value]) => `
    <div class="ip-row">
      <span class="label">${esc(label)}</span>
      <code class="mono">${esc(value)}</code>
      <button class="btn ghost sm" data-copy="${esc(value)}" title="Copy ${esc(label)}">${icon("copy", 13)} Copy</button>
    </div>`).join("");
  $$("button[data-copy]", card).forEach((b) => {
    b.onclick = () => copyText(b.dataset.copy, "Address copied");
  });
}

function worstBanner(data) {
  const subs = Object.entries(data._health || {}).filter(([, s]) => s.state !== "ok");
  if (!subs.length) return "";
  const [name, s] = subs[0];
  return healthBanner({ state: s.state, detail: `${name}: ${s.detail || ""}`, age_seconds: 0, data: null });
}

/* ---------- attention queue (FR-031, FR-054) ---------- */
function drawAttention(items) {
  const host = $("#attention-list");
  if (!items.length) {
    host.innerHTML = `<div class="all-clear">
      <p>All clear — nothing needs your attention right now.</p>
      <a class="btn primary sm" href="#/profiles">${icon("upload", 15)} Import profiles</a>
    </div>`;
    return;
  }
  host.innerHTML = items.map((it, i) => {
    const [kind, label] = SEV[it.severity] || ["warn", "Due"];
    const a = it.inline_action || {};
    const actionBtn = a.method === "POST"
      ? `<button class="btn ghost sm" data-inline="${i}">${esc(a.label)}</button>`
      : `<a class="btn ghost sm" href="${esc(a.href || it.target_href)}">${esc(a.label)}</a>`;
    return `<div class="attention-item ${it.severity}">
      ${status(kind, label)}
      <span class="msg">${esc(it.message)}</span>
      <a class="target" href="${esc(it.target_href)}">${esc(it.target_label)}</a>
      ${actionBtn}
    </div>`;
  }).join("");

  $$("button[data-inline]", host).forEach((btn) => {
    btn.onclick = async () => {
      const a = items[Number(btn.dataset.inline)].inline_action;
      btn.disabled = true;
      try {
        await api(a.path.replace(/^\/api/, ""), { method: a.method, body: a.body || undefined });
        toast(`${a.label}: done.`, "success");
        await loadOverview(root, true);
      } catch (err) { toast(errorText(err), "error"); btn.disabled = false; }
    };
  });
}

/* ---------- five stat tiles (FR-030, FR-032) ---------- */
const UNIT_SEV = {
  active: ["ok", "Running"], running: ["ok", "Running"], exited: ["ok", "Active (exited)"],
  inactive: ["warn", "Inactive"], failed: ["err", "Failed"],
  "not-found": ["err", "Missing"], unknown: ["warn", "Unknown"],
};
const TUNNEL_SEV = { up: ["ok", "Tunnel up"], down: ["warn", "Tunnel down"],
  "not-installed": ["off", "Not installed as service"] };

function drawTiles(tiles, attention, vpn) {
  const sevFor = (prefix) => {
    const hits = attention.filter((a) => a.code.startsWith(prefix));
    return hits.some((a) => a.severity === "red") ? "err"
      : hits.length ? "warn" : "";
  };
  const nodeState = tiles.node.state;

  // VPN services tile: explicit Tailscale + OpenVPN rows, then tunnels
  const rows = [];
  let vpnCls = "";
  if (vpn) {
    for (const row of [vpn.tailscale, vpn.openvpn].filter(Boolean)) {
      // a oneshot unit reports active/exited — show that distinctly
      const key = row.state === "active" && row.sub_state === "exited" ? "exited" : row.state;
      const [kind, label] = UNIT_SEV[key] || UNIT_SEV.unknown;
      if (kind === "err") vpnCls = "err"; else if (kind === "warn" && vpnCls !== "err") vpnCls = "warn";
      rows.push(`<div class="tile-row"><span class="tr-name">${row.unit.startsWith("tailscaled") ? "Tailscale" : "OpenVPN"}</span> ${status(kind, label)}</div>`);
    }
    for (const t of vpn.tunnels || []) {
      const [kind, label] = TUNNEL_SEV[t.state] || TUNNEL_SEV["not-installed"];
      rows.push(`<div class="tile-row"><span class="tr-name" title="${esc(t.name)}">${esc(t.name)}</span> ${status(kind, label)}</div>`);
    }
  }

  const t = [
    { icon: "node", label: "Local node", value: nodeState,
      cls: nodeState === "Running" ? "ok" : "err", sub: "tailscaled on this host" },
    { icon: "devices", label: "Devices", value: `${tiles.devices.online} / ${tiles.devices.total}`,
      cls: sevFor("device."), sub: "online / total" },
    { icon: "profiles", label: "Profiles", value: `${tiles.profiles.enabled} / ${tiles.profiles.total}`,
      cls: sevFor("profile."), sub: "enabled / total" },
    { icon: "globe", label: "Exposures",
      value: `${tiles.exposures.tailnet} <span class="${tiles.exposures.public_alert ? "public-accent" : ""}">/ ${tiles.exposures.public} public</span>`,
      cls: tiles.exposures.public_alert ? "err" : sevFor("exposure."), sub: "tailnet / public" },
    { icon: "services", label: "VPN services", value: `${tiles.services.running} of ${tiles.services.total}`,
      cls: vpnCls || sevFor("service."), sub: "running", rows },
  ];
  $("#tiles").innerHTML = t.map((x) => `
    <div class="stat-tile ${x.cls}" ${x.cls === "err" ? 'data-sev="red"' : x.cls === "warn" ? 'data-sev="amber"' : ""}>
      <span class="label">${icon(x.icon, 14)} ${esc(x.label)}</span>
      <span class="value">${x.value}</span>
      <span class="sub">${esc(x.sub)}</span>
      ${(x.rows || []).join("")}
    </div>`).join("");
}

/* ---------- quick actions ---------- */
function drawQuickActions() {
  const host = $("#qa-row");
  host.innerHTML = `
    <a class="btn ghost sm" href="#/profiles">${icon("upload", 15)} Import profiles</a>
    <button class="btn ghost sm" id="qa-connect">${icon("plus", 15)} Connect a device</button>
    <button class="btn ghost sm" id="qa-download">${icon("download", 15)} Download last profile</button>`;

  $("#qa-connect", host).onclick = openConnectDialog;
  $("#qa-download", host).onclick = async () => {
    try {
      const data = await api("/profiles");
      const rows = data.profiles || [];
      if (!rows.length) { toast("No profiles yet — import one first.", "info"); return; }
      location.href = `/api/profiles/${rows[0].id}/download`;
    } catch (err) { toast(errorText(err), "error"); }
  };
}

function openConnectDialog() {
  const scrim = h(`<div class="dialog-scrim" role="dialog" aria-modal="true">
    <div class="dialog">
      <h2>Connect a device</h2>
      <div class="body">
        <div class="field">
          <label for="cd-os">Device OS</label>
          <select class="input" id="cd-os">
            <option value="linux">Linux</option>
            <option value="macos">macOS</option>
            <option value="windows">Windows</option>
            <option value="ios">iOS</option>
            <option value="android">Android</option>
          </select>
        </div>
        <div class="field">
          <label for="cd-kind">Device kind</label>
          <select class="input" id="cd-kind">
            <option value="user">User device</option>
            <option value="server">Server (tag:server)</option>
          </select>
        </div>
        <div id="cd-result"></div>
      </div>
      <div class="btn-row">
        <button class="btn ghost" data-close>Close</button>
        <button class="btn primary" data-mint>Create one-time key</button>
      </div>
    </div>
  </div>`);
  document.body.appendChild(scrim);
  $("[data-close]", scrim).onclick = () => scrim.remove();
  scrim.onclick = (e) => { if (e.target === scrim) scrim.remove(); };

  $("[data-mint]", scrim).onclick = async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    const out = $("#cd-result", scrim);
    try {
      const r = await api("/overview/connect-device", {
        method: "POST",
        body: { os: $("#cd-os", scrim).value, kind: $("#cd-kind", scrim).value },
      });
      const instruction = r.command
        ? r.command
        : r.hint;
      out.innerHTML = `
        <div class="key-box">
          <textarea readonly rows="3" class="input mono" id="cd-cmd">${esc(instruction)}</textarea>
          <div class="btn-row">
            <button class="btn ghost sm" data-copy-cmd>${icon("copy", 14)} Copy</button>
          </div>
          <p class="hint">${esc(r.hint)} The key works once and expires on its own.</p>
        </div>`;
      $("[data-copy-cmd]", out).onclick = () => copyText(instruction, "Instruction copied");
    } catch (err) {
      out.innerHTML = `<p class="form-error">${esc(errorText(err))}</p>`;
    }
    btn.disabled = false;
  };
}

/* ---------- recent activity ---------- */
function drawRecent(events) {
  const tbody = $("#recent-table tbody");
  if (!events.length) {
    tbody.innerHTML = `<tr><td colspan="4" class="faint">No activity yet.</td></tr>`;
    return;
  }
  tbody.innerHTML = events.map((e) => {
    const kind = OUTCOME_KIND[e.outcome] || "off";
    const label = e.outcome === "ok" ? "OK" : e.outcome;
    return `<tr>
      <td class="small faint" title="${esc(fmtDate(e.ts))}">${relTime(e.ts)}</td>
      <td class="small mono">${esc(e.action)}</td>
      <td class="small">${esc(e.target || "—")}</td>
      <td>${status(kind, label)}</td>
    </tr>`;
  }).join("");
}

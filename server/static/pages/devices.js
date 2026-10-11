/* Devices page (US4/US5): tabs, searchable inventory table, detail drawer with
   friction-tier actions. This page never pretends stale data is live (FR-053). */
import {
  api, toast, errorText, esc, h, $, $$, status, relTime, fmtDate,
  healthBanner, icon, copyText, osIcon, confirmDialog, typeConfirmDialog, every,
} from "../app.js";

const state = { tab: "all", q: "", rows: [], counts: {}, health: null };

const DEVICE_STATUS = (d) => {
  if (d.key_expiry_state === "expired") return ["err", "Expired"];
  if (!d.authorized) return ["warn", "Needs approval"];
  if (d.key_expiry_state === "expiring") return ["warn", "Expiring"];
  return d.online ? ["ok", "Online"] : ["off", "Offline"];
};

export async function renderDevices(root) {
  root.innerHTML = `
  <div class="page-head">
    <h1>Devices</h1>
    <button class="btn ghost sm" id="dev-refresh">${icon("refresh", 15)} Refresh</button>
  </div>
  <p class="page-sub">Every machine in your tailnet — user devices and servers. Click a row for detail.</p>

  <div class="tabs" id="dev-tabs">
    <button class="tab" data-tab="all">All</button>
    <button class="tab" data-tab="users">Users</button>
    <button class="tab" data-tab="servers">Servers</button>
  </div>

  <div class="filterbar">
    <label class="search">${icon("search", 15)}
      <input id="dev-q" placeholder='Filter — try is:unapproved tag:server !os:ios' value="${esc(state.q)}">
    </label>
  </div>
  <div class="active-filters" id="dev-active"></div>
  <div id="dev-banner"></div>

  <div class="card" style="padding:0">
    <div class="table-wrap">
      <table class="table" id="dev-table">
        <thead><tr>
          <th>Status</th><th>Machine</th><th>Owner</th><th>Address</th>
          <th>OS · version</th><th>Routes</th><th>Key expiry</th><th>Last seen</th>
        </tr></thead>
        <tbody></tbody>
      </table>
    </div>
    <div class="empty" id="dev-empty" hidden></div>
  </div>`;

  $$("#dev-tabs .tab", root).forEach((b) => {
    b.classList.toggle("active", b.dataset.tab === state.tab);
    b.onclick = () => {
      state.tab = b.dataset.tab;
      $$("#dev-tabs .tab", root).forEach((x) => x.classList.toggle("active", x === b));
      load(root);
    };
  });
  const qInput = $("#dev-q", root);
  qInput.onkeydown = (e) => {
    if (e.key === "Enter") { state.q = qInput.value.trim(); load(root); }
    if (e.key === "Escape") { qInput.value = ""; state.q = ""; load(root); }
  };
  $("#dev-refresh", root).onclick = () => load(root);
  $("#dev-active", root).addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-drop]");
    if (!btn) return;
    const tokens = state.q.split(/\s+/).filter(Boolean);
    tokens.splice(Number(btn.dataset.drop), 1);
    state.q = tokens.join(" ");
    load(root);
  });

  await load(root);
}

export function searchDevices(q) { state.q = q; }

async function load(root) {
  $("#dev-active", root).innerHTML = drawChips();
  let data;
  try {
    data = await api(`/devices?tab=${state.tab}${state.q ? `&q=${encodeURIComponent(state.q)}` : ""}`);
  } catch (err) { toast(errorText(err), "error"); return; }
  state.rows = data.devices;
  state.counts = data.counts;
  state.health = data._health;

  $("#dev-banner", root).innerHTML = healthBanner({
    ...data._health, data: data.devices.length ? 1 : null,
  });
  drawRows(root);
  const count = $("[data-count='devices']");
  if (count) count.textContent = data.counts.total || "";
}

function drawChips() {
  const tokens = state.q.split(/\s+/).filter(Boolean);
  if (!tokens.length) return "";
  return tokens.map((t, i) =>
    `<span class="chip">${esc(t)}<button data-drop="${i}" aria-label="Remove filter ${esc(t)}">${icon("x", 11)}</button></span>`
  ).join("") + `<button class="btn ghost sm" id="dev-clear">Clear</button>`;
}

function drawRows(root) {
  const tbody = $("#dev-table tbody", root);
  const empty = $("#dev-empty", root);

  if (!state.rows.length) {
    tbody.innerHTML = "";
    empty.hidden = false;
    empty.innerHTML = state.q
      ? `<p>No devices match this filter.</p><button class="btn ghost sm" id="dev-clear-q">Clear filter</button>`
      : (state.health?.state !== "ok"
        ? `<p>No devices to show — ${esc(state.health?.detail || "the tailnet is unreachable")}.</p>`
        : `<p>No devices to show. Craft a connect command for your first device.</p><button class="btn primary sm" id="dev-first">Connect a device</button>`);
    if (state.q) $("#dev-clear-q", empty).onclick = () => { state.q = ""; load(root); };
    else $("#dev-first", empty)?.addEventListener("click", () => { location.hash = "#/overview"; });
    return;
  }
  empty.hidden = true;

  tbody.innerHTML = state.rows.map((d) => {
    const [kind, label] = DEVICE_STATUS(d);
    const chips = [];
    if (d.exit_node) chips.push('<span class="badge err">exit node</span>');
    if (d.subnet_routes.length) chips.push(`<span class="badge info" title="${esc(d.subnet_routes.join(", "))}">routes ×${d.subnet_routes.length}</span>`);
    const expiry = d.key_expiry_state === "never"
      ? '<span class="badge info">never · rekey off</span>'
      : `${fmtDate(d.key_expiry)} <span class="faint small">${relTime(d.key_expiry)}</span>`;
    return `<tr data-id="${d.id}" class="${d.online ? "" : "dim"}">
      <td>${status(kind, label)}</td>
      <td><span class="os" title="${esc(d.os_label)}">${icon(osIcon(d.os), 16)}</span> <strong>${esc(d.hostname || d.name)}</strong>
          <div class="tagline">${d.tags.map((t) => `<span class="chip">${esc(t)}</span>`).join("")}</div></td>
      <td class="small">${esc(d.user || "—")}</td>
      <td><button class="addr" data-copy="${esc(d.addresses[0] || "")}" title="Copy address">${esc(d.addresses[0] || "—")}</button></td>
      <td class="small">${esc(d.os_label)} · ${esc(d.version)}${d.version_stale ? ' <span class="badge warn">outdated</span>' : ""}</td>
      <td>${chips.join("") || '<span class="faint">—</span>'}</td>
      <td class="small">${expiry}</td>
      <td class="faint small">${relTime(d.last_seen)}</td>
    </tr>`;
  }).join("");

  tbody.onclick = (e) => {
    const copyBtn = e.target.closest("[data-copy]");
    if (copyBtn) { e.stopPropagation(); copyText(copyBtn.dataset.copy, "Address copied"); return; }
    const tr = e.target.closest("tr[data-id]");
    if (tr) openDevicesDrawer(root, tr.dataset.id);
  };
}

/* ---------- drawer (detail + lifecycle actions, US5) ---------- */
export async function openDevicesDrawer(root, did) {
  let d;
  try { d = await api(`/devices/${did}`); }
  catch (err) { toast(errorText(err), "error"); return; }

  const scrim = h(`<div class="drawer-scrim"></div>`);
  const drawer = h(`<aside class="drawer" role="dialog" aria-modal="true" aria-label="${esc(d.hostname)}">
    <header>
      <span class="os" title="${esc(d.os_label)}">${icon(osIcon(d.os), 16)}</span>
      <h2>${esc(d.hostname || d.name)}</h2>
      ${status(...DEVICE_STATUS(d))}
      <button class="btn ghost sm" data-close aria-label="Close">${icon("x", 15)}</button>
    </header>
    <div class="body">
      <dl class="kv">
        <dt>Full name</dt><dd class="mono">${esc(d.name)}</dd>
        <dt>Owner</dt><dd>${esc(d.user || "—")}</dd>
        <dt>Addresses</dt><dd>${d.addresses.map((a) =>
          `<button class="addr" data-copy="${esc(a)}">${esc(a)}</button>`).join(" ")}</dd>
        <dt>OS · version</dt><dd>${esc(d.os_label)} · ${esc(d.version)}${d.version_stale ? ' <span class="badge warn">outdated</span>' : ""}${d.client_version && d.client_version !== d.version ? ` <span class="faint small">(client ${esc(d.client_version)})</span>` : ""}</dd>
        <dt>Tags</dt><dd class="kv-tags">${d.tags.length ? d.tags.map((t) => `<span class="chip">${esc(t)}</span>`).join(" ") : "—"}</dd>
        <dt>Key expiry</dt><dd>${d.key_expiry_state === "never"
          ? "Never — rekeying is disabled"
          : `${fmtDate(d.key_expiry)} <span class="faint">(${relTime(d.key_expiry)})</span>`}</dd>
        <dt>Last seen</dt><dd>${fmtDate(d.last_seen)} <span class="faint">(${relTime(d.last_seen)})</span></dd>
        <dt>Exit node</dt><dd>${d.exit_node ? "Yes" : d.advertised_exit ? "Advertised, not approved" : "No"}</dd>
      </dl>
      <div id="device-actions"></div>
    </div>
  </aside>`);
  document.body.append(scrim, drawer);
  const poll = every(8000, async () => {  // keep the open drawer honest (FR-053)
    try {
      const fresh = await api(`/devices/${did}`);
      const pill = $("header .status", drawer);
      if (pill) pill.outerHTML = status(...DEVICE_STATUS(fresh));
    } catch { /* drawer closed or signed out */ }
  });
  const close = () => { clearInterval(poll); scrim.remove(); drawer.remove(); };
  $("[data-close]", drawer).onclick = close;
  scrim.onclick = close;
  $$("[data-copy]", drawer).forEach((b) => { b.onclick = () => copyText(b.dataset.copy, "Address copied"); });
  buildDeviceActions($("#device-actions", drawer), root, close, d);
}

/* ---------- actions: one block per friction tier (FR-026, FR-051) ---------- */
function buildDeviceActions(host, root, close, first) {
  const render = (d) => {
    const needsApproval = !d.authorized;
    const reauth = !d.expiry_disabled; // "Require periodic re-authentication"
    const name = d.hostname || d.name;
    const down = state.health && state.health.state !== "ok";
    const lock = down ? "disabled title=\"Tailnet unreachable — mutations are blocked until it recovers.\"" : "";

    host.innerHTML = `
    ${needsApproval ? `
    <section class="action-block">
      <h3>Access</h3>
      <p class="hint">This device is waiting for approval and cannot connect yet.</p>
      <button class="btn primary" data-act="approve" ${lock}>${icon("check", 15)} Approve device</button>
    </section>` : ""}

    <section class="action-block">
      <h3>Tags</h3>
      <div class="tag-editor" data-role="tags">
        ${d.tags.map((t) => `<span class="chip">${esc(t)}<button data-untag="${esc(t)}" aria-label="Remove ${esc(t)}">${icon("x", 11)}</button></span>`).join("")}
        <input class="tag-input" placeholder="Add tag (Enter)" aria-label="Add tag">
      </div>
      <p class="hint small">Tagged <span class="mono">tag:server</span> devices are grouped under Servers.</p>
    </section>

    <section class="action-block">
      <h3>Approved subnet routes</h3>
      <p class="hint small">Advertised: <span class="mono">${esc(d.advertised_routes.join(", ")) || "none"}</span></p>
      <div class="tag-editor" data-role="routes">
        ${d.approved_routes.map((r) => `<span class="chip mono">${esc(r)}<button data-unroute="${esc(r)}" aria-label="Remove ${esc(r)}">${icon("x", 11)}</button></span>`).join("")}
        <input class="tag-input" placeholder="e.g. 192.168.1.0/24 (Enter)" aria-label="Add approved route">
      </div>
    </section>

    <section class="action-block">
      <h3>Key settings</h3>
      <label class="toggle-row">
        <input type="checkbox" data-act="reauth" ${reauth ? "checked" : ""}>
        <span>Require periodic re-authentication</span>
      </label>
      <p class="hint small">${reauth && d.key_expiry
        ? `Key expires ${fmtDate(d.key_expiry)} <span class="faint">(${relTime(d.key_expiry)})</span>.`
        : "Key never expires — the device stays trusted until removed."}</p>
      <button class="btn ghost sm" data-act="expire" ${lock}>${icon("key", 15)} Expire key now</button>
      <p class="hint small">Disconnects this device until its owner re-authenticates.</p>
    </section>

    <section class="action-block danger-zone">
      <h3>Remove</h3>
      <button class="btn danger" data-act="delete" ${lock}>${icon("trash", 15)} Delete device</button>
      <p class="hint small">Removes ${esc(name)} from the tailnet. Irreversible.</p>
    </section>`;

    const act = (sel, fn) => { const el = $(sel, host); if (el) el.onclick = fn; };
    const refresh = async (msg) => {
      try { render(await api(`/devices/${d.id}`)); } catch { /* drawer closed */ }
      if (root) load(root);
      if (msg) toast(msg, "success");
    };
    const busy = async (el, fn) => {
      el.disabled = true;
      try { await fn(); } catch (err) { toast(errorText(err), "error"); }
      el.disabled = false;
    };

    act("[data-act='approve']", (e) => busy(e.currentTarget, async () => {
      // Tier 1 — no dialog (FR-026): approving is low-blast and audit-logged.
      await api(`/devices/${d.id}/approve`, { method: "POST" });
      await refresh(`${name} approved.`);
    }));

    act("[data-act='expire']", async (e) => {
      // Tier 2 — confirm naming the device and its consequence (FR-051);
      // outcome-labeled button, focus starts on Cancel.
      const yes = await confirmDialog({
        title: "Expire key now?",
        body: `<p><strong>${esc(name)}</strong> will disconnect from the tailnet
               immediately and stay offline until its owner re-authenticates.</p>
               <p class="small muted">This cannot be undone from here.</p>`,
        confirmLabel: "Expire key",
        danger: true,
      });
      if (!yes) return;
      await busy(e.currentTarget, async () => {
        await api(`/devices/${d.id}/expire-key`, { method: "POST", body: { confirm: true } });
        await refresh(`Key expired for ${name} — it is now disconnected.`);
      });
    });

    act("[data-act='delete']", async () => {
      // Tier 3 — type the exact device name (FR-026): irreversible removal.
      const yes = await typeConfirmDialog({
        title: "Delete device",
        body: `<p>This removes <strong>${esc(name)}</strong> from your tailnet and revokes
               its access. The device must re-enroll to rejoin.</p>`,
        phrase: name,
        confirmLabel: "Delete device",
      });
      if (!yes) return;
      try {
        await api(`/devices/${d.id}`, { method: "DELETE", body: { typed_confirm: name } });
        toast(`${name} deleted.`, "success");
        close();
        if (root) load(root);
      } catch (err) { toast(errorText(err), "error"); }
    });

    act("[data-act='reauth']", async (e) => {
      // Disabling expiry is the consequential direction → short confirm;
      // enabling re-authentication applies right away.
      const target = e.currentTarget.checked;
      if (!target) {
        const yes = await confirmDialog({
          title: "Disable key expiry?",
          body: `<p>The key for <strong>${esc(name)}</strong> will never expire.
                 The device stays trusted until you remove it.</p>`,
          confirmLabel: "Disable expiry",
          danger: true,
        });
        if (!yes) { e.currentTarget.checked = true; return; }
      }
      try {
        await api(`/devices/${d.id}`, { method: "PATCH", body: { require_reauth: target } });
        await refresh(target ? "Periodic re-authentication required." : "Key expiry disabled.");
      } catch (err) {
        toast(errorText(err), "error");
        e.currentTarget.checked = !target;
      }
    });

    // tag + route editors: Enter adds a chip and PATCHes the merged list
    const chips = (box) => $$(".chip", box).map((c) => c.childNodes[0].textContent.trim());
    const editor = (sel, parse, payload) => {
      const box = $(sel, host);
      const input = $(".tag-input", box);
      input.onkeydown = (e) => {
        if (e.key !== "Enter" || !input.value.trim()) return;
        e.preventDefault();
        const value = parse(input.value.trim());
        if (!value) { toast("Not a valid entry.", "error"); return; }
        busy(input, async () => {
          await api(`/devices/${d.id}`, { method: "PATCH", body: payload([...chips(box), value]) });
          await refresh("Saved.");
        });
      };
    };
    editor("[data-role='tags']",
      (v) => (/^[\w-]+$/.test(v) ? (v.startsWith("tag:") ? v : `tag:${v}`) : null),
      (tags) => ({ tags }));
    editor("[data-role='routes']",
      (v) => (/^\d{1,3}(\.\d{1,3}){3}\/\d{1,2}$/.test(v) ? v : null),
      (routes) => ({ routes_approved: routes }));

    $$("[data-untag]", host).forEach((b) => {
      b.onclick = async () => {
        try {
          await api(`/devices/${d.id}`, { method: "PATCH", body: { tags: d.tags.filter((t) => t !== b.dataset.untag) } });
          await refresh("Tag removed.");
        } catch (err) { toast(errorText(err), "error"); }
      };
    });
    $$("[data-unroute]", host).forEach((b) => {
      b.onclick = async () => {
        try {
          await api(`/devices/${d.id}`, { method: "PATCH", body: { routes_approved: d.approved_routes.filter((r) => r !== b.dataset.unroute) } });
          await refresh("Route removed.");
        } catch (err) { toast(errorText(err), "error"); }
      };
    });
  };
  render(first);
}

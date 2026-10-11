/* Local Node page (US8, FR-041..044): tailscaled status with explicit
   freshness, connect/disconnect (tier 3 — self-lockout), exit-node
   advertise/use, advertised subnet routes with approval state. */
import {
  api, toast, errorText, esc, h, $, $$, status, healthBanner, icon,
  confirmDialog, copyText, every,
} from "../app.js";

const CIDR_RE = /^\d{1,3}(\.\d{1,3}){3}\/\d{1,2}$/;
let ROOT = null;
let NODE = null;
let EXIT_CANDIDATES = [];

export async function renderNode(root) {
  ROOT = root;
  root.innerHTML = `
  <div class="page-head">
    <h1>Local Node</h1>
    <button class="btn ghost sm" id="node-refresh">${icon("refresh", 14)} Refresh</button>
  </div>
  <p class="page-sub">Direct control of tailscaled on the host serving this console.</p>
  <div id="node-banner"></div>

  <section class="card">
    <div class="node-head" id="node-head"></div>
    <p class="freshness" id="node-fresh" aria-live="polite"></p>
    <div class="node-actions" id="node-actions"></div>
  </section>

  <section class="card">
    <h2>Exit node</h2>
    <p class="hint">An exit node lets tailnet devices route their internet traffic through this host. You can also send this host's traffic out through another node.</p>
    <div id="exit-controls"></div>
  </section>

  <section class="card">
    <h2>Subnet routes</h2>
    <p class="hint">IP ranges this host advertises into the tailnet. Routes only carry traffic once the tailnet approves them.</p>
    <div id="routes-list"></div>
  </section>`;

  $("#node-refresh", root).onclick = () => load(false);
  await load(false);
  every(8000, () => load(true));
}

async function load(silent) {
  let data;
  try { data = await api("/node"); }
  catch (err) { if (!silent) toast(errorText(err), "error"); return; }
  NODE = data;
  const bad = data._health && data._health.state !== "ok";
  $("#node-banner", ROOT).innerHTML = bad ? healthBanner({ ...data._health, data }) : "";
  drawHead(data);
  drawActions(data);
  drawExit(data);
  drawRoutes(data);
  if (!EXIT_CANDIDATES.length) loadExitCandidates();
}

async function loadExitCandidates() {
  try {
    const data = await api("/devices");
    EXIT_CANDIDATES = (data.devices || [])
      .filter((r) => r.exit_node && r.online)
      .map((r) => ({ value: r.addresses[0] || r.name, label: `${r.hostname || r.name} (${r.addresses[0] || "?"})` }));
  } catch { /* tailnet unreachable: the select simply has no peers */ }
  if (NODE) drawExit(NODE);
}

/* ---------- status card ---------- */
function drawHead(d) {
  const running = d.state === "Running";
  $("#node-head", ROOT).innerHTML = `
    ${status(running ? "ok" : d.state === "Stopped" ? "err" : "warn", d.state)}
    <span class="faint">${esc(d.hostname || "unknown host")}</span>
    <span class="mono">${esc(d.addresses[0] || "—")}</span>
    <button class="btn ghost sm" data-copy-addr title="Copy Tailscale IP">${icon("copy", 13)}</button>
    <span class="faint">tailscaled ${esc(d.version || "?")}</span>`;
  $("[data-copy-addr]", ROOT).onclick = () => copyText(d.addresses[0] || "", "Address copied");

  const hsub = d._health || {};
  $("#node-fresh", ROOT).textContent = hsub.state !== "ok"
    ? `Last good data: ${Math.round(hsub.age_seconds || 0)}s ago`
    : (hsub.age_seconds || 0) < 8 ? "Live · just now" : `As of ${Math.round(hsub.age_seconds)}s ago`;
}

function drawActions(d) {
  const host = $("#node-actions", ROOT);
  const bad = NODE._health && NODE._health.state !== "ok";
  if (d.state === "Running") {
    host.innerHTML = `<button class="btn danger sm" id="node-disconnect" ${bad ? "disabled title=\"Node unreachable. Changes are blocked until it recovers.\"" : ""}>${icon("power", 14)} Disconnect…</button>`;
    $("#node-disconnect", host).onclick = openDisconnectDialog;
  } else {
    host.innerHTML = `<button class="btn primary sm" id="node-connect" ${bad ? "disabled title=\"Node unreachable. Changes are blocked until it recovers.\"" : ""}>${icon("play", 14)} Connect</button>`;
    $("#node-connect", host).onclick = () => post("/node/connect", {}, "tailscaled is connecting…");
  }
}

async function post(path, body, okMsg) {
  try {
    await api(path, { method: "POST", body: body || {} });
    toast(okMsg, "success");
  } catch (err) {
    toast(errorText(err), "error");
  }
  await load(true);
}

/* ---------- disconnect: tier 3 — typed + LAN acknowledgement (FR-042) ---------- */
function openDisconnectDialog() {
  const d = NODE || {};
  const addr = (d.addresses || [])[0] || "its Tailscale IP";
  const scrim = h(`<div class="dialog-scrim" role="dialog" aria-modal="true">
    <div class="dialog danger-accent">
      <h2>Disconnect this host from Tailscale?</h2>
      <div class="body">
        <p>You will immediately lose access to <strong>${esc(d.hostname || "this host")}</strong>
        (<span class="mono">${esc(addr)}</span>) over Tailscale, including this console
        if you are connected through the tailnet.</p>
        <p class="form-error">Tailscale does not come back on its own. Someone with LAN or
        physical access must run <span class="mono">tailscale up</span> on the host.</p>
        <label class="check-row">
          <input type="checkbox" data-lan>
          <span>I can reach this host via LAN or a physical console.</span>
        </label>
        <div class="field">
          <label>Type <strong class="mono">DISCONNECT</strong> to confirm</label>
          <input class="input" data-phrase autocomplete="off" spellcheck="false">
        </div>
      </div>
      <div class="btn-row">
        <button class="btn ghost" data-no>Cancel</button>
        <button class="btn danger" data-yes disabled>Disconnect</button>
      </div>
    </div>
  </div>`);
  document.body.appendChild(scrim);
  const yes = $("[data-yes]", scrim);
  const ready = () =>
    $("[data-lan]", scrim).checked && $("[data-phrase]", scrim).value.trim() === "DISCONNECT";
  const upd = () => { yes.disabled = !ready(); };
  $("[data-lan]", scrim).onchange = upd;
  $("[data-phrase]", scrim).oninput = upd;
  $("[data-no]", scrim).onclick = () => scrim.remove();
  $("[data-no]", scrim).focus(); // no default focus on the destructive action
  scrim.onclick = (e) => { if (e.target === scrim) scrim.remove(); };
  yes.onclick = async () => {
    yes.disabled = true;
    try {
      await api("/node/disconnect", {
        method: "POST",
        body: { typed_confirm: "DISCONNECT", lan_ack: true },
      });
      scrim.remove();
      toast("tailscaled disconnected.", "success");
      await load(true);
    } catch (err) {
      toast(errorText(err), "error");
      yes.disabled = false;
    }
  };
}

/* ---------- exit node ---------- */
function drawExit(d) {
  const host = $("#exit-controls", ROOT);
  const ex = d.exit_node || {};
  const options = EXIT_CANDIDATES.map((c) =>
    `<option value="${esc(c.value)}" ${ex.using === c.value ? "selected" : ""}>${esc(c.label)}</option>`).join("");
  host.innerHTML = `
    <div class="toggle-row">
      <div>
        <strong>Advertise this host as an exit node</strong>
        <p class="hint">Nothing routes through it until a device selects it.</p>
      </div>
      <button class="switch ${ex.advertising ? "on" : ""}" role="switch"
        aria-checked="${ex.advertising}" data-adv aria-label="Advertise exit node"></button>
    </div>
    <div class="route-row">
      <div>
        <strong>Use an exit node</strong>
        <p class="hint">${ex.using
          ? `Internet traffic currently routes via <span class="mono">${esc(ex.using)}</span>.`
          : "Not routing through any exit node."}</p>
      </div>
      <div class="btn-row">
        <select class="input sm" data-use-select aria-label="Exit node selection">
          <option value="">None (stop using an exit node)</option>
          ${options}
        </select>
        <button class="btn ghost sm" data-use-apply>Apply</button>
      </div>
    </div>`;

  $("[data-adv]", host).onclick = async () => {
    const next = !ex.advertising;
    const ok = await confirmDialog({
      title: next ? "Advertise exit node?" : "Stop advertising exit node?",
      body: next
        ? "<p>This host's internet connection becomes available to <strong>every device in the tailnet</strong>. Nothing changes until a device selects it.</p>"
        : "<p>Devices that route internet traffic through this host will lose that path.</p>",
      confirmLabel: next ? "Advertise" : "Stop advertising",
    });
    if (ok) post("/node/exit-node", { advertise: next },
      next ? "Advertising exit node." : "Exit-node advertising stopped.");
  };

  $("[data-use-apply]", host).onclick = () => {
    const val = $("[data-use-select]", host).value;
    if (val === ex.using) return;
    if (!val) { post("/node/exit-node", { use: "" }, "Exit node cleared."); return; }
    confirmDialog({
      title: `Use ${val} as exit node?`,
      body: `<p>This host's internet traffic will route via
        <strong class="mono">${esc(val)}</strong>. If your own session rides the
        tailnet, make sure this won't cut you off.</p>`,
      confirmLabel: "Route via exit node",
    }).then((ok) => { if (ok) post("/node/exit-node", { use: val }, "Exit node selected."); });
  };
}

/* ---------- subnet routes ---------- */
function drawRoutes(d) {
  const host = $("#routes-list", ROOT);
  const routes = d.subnet_routes || [];
  const self = d.self_device;

  const rows = routes.map((r) => {
    let approval;
    if (r.approved === true) approval = status("ok", "Approved");
    else if (r.approved === false) approval = `<button class="btn ghost sm" data-approve="${esc(r.route)}">${icon("check", 13)} Approve</button>`;
    else approval = status("off", "Approval unknown");
    return `<div class="route-row" data-route="${esc(r.route)}">
      <span class="mono">${esc(r.route)}</span>
      <span class="faint">advertised</span>
      ${approval}
      <button class="btn ghost sm" data-withdraw="${esc(r.route)}" title="Stop advertising">${icon("x", 13)} Withdraw</button>
    </div>`;
  }).join("") || `<p class="faint">No subnet routes advertised.</p>`;

  host.innerHTML = `
    ${rows}
    <div class="route-row add">
      <input class="input sm mono" data-new-route placeholder="10.30.0.0/24" aria-label="New route CIDR">
      <button class="btn primary sm" data-add-route>${icon("plus", 13)} Advertise route</button>
    </div>`;

  $$("[data-approve]", host).forEach((btn) => {
    btn.onclick = async () => {
      if (!self) { toast("Tailnet view unavailable. Approve the route from the Devices page.", "error"); return; }
      btn.disabled = true;
      try {
        await api(`/devices/${self.id}`, {
          method: "PATCH",
          body: { routes_approved: [...new Set([...(self.approved_routes || []), btn.dataset.approve])] },
        });
        toast(`Approved ${btn.dataset.approve}.`, "success");
      } catch (err) { toast(errorText(err), "error"); btn.disabled = false; }
      await load(true);
    };
  });

  $$("[data-withdraw]", host).forEach((btn) => {
    btn.onclick = () => routeDelta(`-${btn.dataset.withdraw}`);
  });

  $("[data-add-route]", host).onclick = () => {
    const input = $("[data-new-route]", host);
    const cidr = input.value.trim();
    if (!CIDR_RE.test(cidr)) { toast("Enter a route as a.b.c.d/nn, for example 10.30.0.0/24.", "error"); return; }
    input.value = "";
    routeDelta(`+${cidr}`);
  };
}

async function routeDelta(token) {
  const cidr = token.slice(1);
  const inverse = token.startsWith("+") ? `-${cidr}` : `+${cidr}`;
  try {
    await api("/node/routes", { method: "POST", body: { advertise: [token] } });
    const verb = token.startsWith("+") ? "Advertising" : "Stopped advertising";
    toast(`${verb} ${cidr}.`, "success", { label: "Undo", run: () => routeDelta(inverse) });
  } catch (err) {
    toast(errorText(err), "error");
  }
  await load(true);
}

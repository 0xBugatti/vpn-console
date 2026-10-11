/* Services page (US9, FR-045): managed systemd units with state, boot toggle,
   start/stop/restart — restart/stop confirm with specific bodies, progress
   toasts while the job runs. */
import {
  api, toast, errorText, esc, $, $$, status, healthBanner, icon, confirmDialog, every,
} from "../app.js";

const STATE_KIND = {
  running: "ok", active: "ok", activating: "warn",
  inactive: "off", failed: "err", exit: "err",
};

let ROOT = null;
let UNITS = [];
let HEALTH = { state: "ok" };

export async function renderServices(root) {
  ROOT = root;
  root.innerHTML = `
  <div class="page-head">
    <h1>Services</h1>
    <button class="btn ghost sm" id="svc-refresh">${icon("refresh", 14)} Refresh</button>
  </div>
  <p class="page-sub">systemd units this console manages on the host.</p>
  <div id="svc-banner"></div>
  <section class="card"><div id="svc-list"></div></section>`;

  $("#svc-refresh", root).onclick = () => load(false);
  await load(false);
  every(10000, () => load(true));
}

async function load(silent) {
  let data;
  try { data = await api("/services"); }
  catch (err) { if (!silent) toast(errorText(err), "error"); return; }
  UNITS = data.units || [];
  HEALTH = data._health || { state: "ok" };
  $("#svc-banner", ROOT).innerHTML =
    healthBanner({ ...HEALTH, data: UNITS.length ? UNITS : null });
  draw();
}

function draw() {
  const host = $("#svc-list", ROOT);
  const down = HEALTH.state !== "ok";
  if (!UNITS.length) {
    host.innerHTML = `<p class="faint">${down
      ? "Host layer unavailable, so there is no unit list."
      : "No managed units on this host."}</p>`;
    return;
  }
  host.innerHTML = UNITS.map((u) => {
    const kind = STATE_KIND[u.state] || "warn";
    return `<div class="svc-row" data-unit="${esc(u.unit)}">
      <div class="svc-main">
        ${status(kind, u.state)}
        <div>
          <strong class="mono">${esc(u.unit)}</strong>
          <p class="faint small">since ${esc(u.since || "?")} · result ${esc(u.result || "?")}</p>
        </div>
      </div>
      <div class="svc-controls">
        <label class="boot-toggle" title="Start on boot">
          <input type="checkbox" data-boot ${u.enabled_on_boot ? "checked" : ""} ${down ? "disabled" : ""}>
          <span>on boot</span>
        </label>
        <button class="btn ghost sm" data-act="start" ${down ? "disabled" : ""}>${icon("play", 13)} Start</button>
        <button class="btn ghost sm" data-act="restart" ${down ? "disabled" : ""}>${icon("refresh", 13)} Restart</button>
        <button class="btn ghost sm danger-text" data-act="stop" ${down ? "disabled" : ""}>${icon("stop", 13)} Stop</button>
      </div>
    </div>`;
  }).join("");

  $$(".svc-row", host).forEach((row) => {
    const unit = row.dataset.unit;
    $$("[data-act]", row).forEach((btn) => {
      btn.onclick = () => act(unit, btn.dataset.act);
    });
    $("[data-boot]", row).onchange = (e) => {
      const enable = e.target.checked;
      act(unit, enable ? "enable" : "disable", () => { e.target.checked = !enable; });
    };
  });
}

async function act(unit, action, revert) {
  if (action === "stop" || action === "restart") {
    const tailscaled = unit.startsWith("tailscaled");
    const blurb = action === "restart"
      ? `Restart <strong class="mono">${esc(unit)}</strong> now? Expect a few seconds of downtime${tailscaled ? ", including tailnet connectivity. This console may drop briefly if you reach it over Tailscale" : ""}.`
      : `Stop <strong class="mono">${esc(unit)}</strong>? It stays down until someone starts it again${tailscaled ? ". Tailnet access to this host ends immediately" : ""}.`;
    const ok = await confirmDialog({
      title: `${action[0].toUpperCase() + action.slice(1)} ${unit}?`,
      body: `<p>${blurb}</p>`,
      confirmLabel: action[0].toUpperCase() + action.slice(1),
      danger: action === "stop",
    });
    if (!ok) { revert?.(); return; }
  }
  toast(`${action} ${unit}…`, "info");
  let r;
  try {
    r = await api(`/services/${encodeURIComponent(unit)}/${action}`, { method: "POST", body: {} });
  } catch (err) {
    toast(errorText(err), "error");
    revert?.();
    return;
  }
  followJob(r.job_id, unit, action);
}

function followJob(job_id, unit, action) {
  let tries = 0;
  const timer = every(1000, async () => {
    tries += 1;
    let job;
    try { job = await api(`/jobs/${job_id}`); }
    catch { return; } // transient — keep polling
    if (!job?.done && tries < 30) return;
    clearInterval(timer);
    if (job?.done && job.ok) toast(`${unit}: ${action} done.`, "success");
    else if (!job?.done) toast(`${unit}: ${action} is taking a while. Check the Logs page.`, "warn");
    else toast(`${unit}: ${action} failed: ${job.detail || "unknown error"}`, "error");
    load(true);
  });
}

/* Settings page (US12, FR-051 tier 3): password rotation, masked credential +
   reachability test, poll intervals, theme, and the type-to-confirm danger
   zone. The full credential never comes back after initial entry — the field
   here only ever writes, never displays. */
import {
  api, toast, errorText, esc, $, $$, status, icon, typeConfirmDialog, applyTheme,
} from "../app.js";

let ROOT = null;
let PROFILE_COUNT = 0;

export async function renderSettings(root) {
  ROOT = root;
  root.innerHTML = `
  <div class="page-head"><h1>Settings</h1></div>
  <p class="page-sub">Operability and credential rotation. Every change here lands in the audit log.</p>

  <section class="card">
    <h2>Appearance &amp; polling</h2>
    <div class="settings-grid">
      <div class="field">
        <label for="set-theme">Theme</label>
        <select class="input" id="set-theme">
          <option value="light">Light</option>
          <option value="dark">Dark</option>
          <option value="system">System</option>
        </select>
      </div>
      <div class="field">
        <label for="set-poll-status">Status poll (seconds)</label>
        <input class="input" id="set-poll-status" type="number" min="2" max="600">
        <p class="hint">Overview tiles + topbar health dots. Faster = fresher, louder.</p>
      </div>
      <div class="field">
        <label for="set-poll-lists">List poll (seconds)</label>
        <input class="input" id="set-poll-lists" type="number" min="10" max="3600">
        <p class="hint">Devices, profiles, services lists.</p>
      </div>
    </div>
    <div class="btn-row"><button class="btn primary sm" id="set-save">Save</button></div>
  </section>

  <section class="card">
    <h2>Admin password</h2>
    <p class="hint">Changing the password signs out every other session but keeps this one.</p>
    <div class="settings-grid">
      <div class="field">
        <label for="pw-current">Current password</label>
        <input class="input" id="pw-current" type="password" autocomplete="current-password">
      </div>
      <div class="field">
        <label for="pw-new">New password (min 8 chars)</label>
        <input class="input" id="pw-new" type="password" autocomplete="new-password">
      </div>
      <div class="field">
        <label for="pw-repeat">Repeat new password</label>
        <input class="input" id="pw-repeat" type="password" autocomplete="new-password">
      </div>
    </div>
    <p class="form-error" id="pw-err" hidden></p>
    <div class="btn-row"><button class="btn primary sm" id="pw-save">Change password</button></div>
  </section>

  <section class="card">
    <h2>Tailscale credential</h2>
    <p class="hint" id="ts-source"></p>
    <div class="settings-grid">
      <div class="field">
        <label for="ts-current">Configured credential</label>
        <input class="input mono" id="ts-current" readonly>
      </div>
      <div class="field">
        <label for="ts-new">Set a stored credential (TS_API_TOKEN env wins while present)</label>
        <input class="input mono" id="ts-new" type="password" placeholder="tskey-auth-…" autocomplete="off">
      </div>
    </div>
    <div class="btn-row">
      <button class="btn ghost sm" id="ts-save">Save credential</button>
      <button class="btn ghost sm" id="ts-test">${icon("external", 14)} Test connection</button>
      <button class="btn ghost sm" id="ts-clear">Clear stored credential</button>
    </div>
    <p class="form-error" id="ts-err" hidden></p>
    <p class="action-note" id="ts-result" hidden></p>
  </section>

  <section class="card danger-zone">
    <h2>Danger zone</h2>
    <div class="danger-item">
      <div>
        <h3>Wipe the profile store</h3>
        <p id="wipe-preview" class="muted small">Counting profiles…</p>
      </div>
      <button class="btn danger sm" id="dz-wipe">Wipe profiles</button>
    </div>
    <div class="danger-item">
      <div>
        <h3>Reset policy to last applied</h3>
        <p class="muted small">Pushes the last applied policy version back to the tailnet and discards any draft in the editor. The audit log is never wiped.</p>
      </div>
      <button class="btn danger sm" id="dz-reset">Reset policy</button>
    </div>
  </section>`;

  await load(false);

  $("#set-theme", root).onchange = (e) => {
    applyTheme(e.target.value);
    try { localStorage.setItem("vc_theme", e.target.value); } catch { /* private mode */ }
  };
  $("#set-save", root).onclick = saveGeneral;
  $("#pw-save", root).onclick = changePassword;
  $("#ts-save", root).onclick = saveToken;
  $("#ts-clear", root).onclick = clearToken;
  $("#ts-test", root).onclick = testToken;
  $("#dz-wipe", root).onclick = wipeProfiles;
  $("#dz-reset", root).onclick = resetPolicy;
}

/* ---------- load ---------- */
async function load(silent) {
  let s;
  try { s = await api("/settings"); }
  catch (err) { if (!silent) toast(errorText(err), "error"); return; }
  $("#set-theme", ROOT).value = s.theme;
  $("#set-poll-status", ROOT).value = s.poll_status_s;
  $("#set-poll-lists", ROOT).value = s.poll_lists_s;
  $("#ts-current", ROOT).value = s.ts_token || "(none configured)";
  $("#ts-source", ROOT).textContent = s.ts_token_source === "env"
    ? "The credential comes from the TS_API_TOKEN environment variable. It cannot be edited here. Remove the variable to manage the credential in the app."
    : s.ts_token_source === "stored"
      ? "A credential is stored in the console database. It is shown masked and can be replaced but never read back."
      : "No credential configured. Tailnet pages show as unavailable until you add one.";
  try {
    const list = await api("/profiles");
    PROFILE_COUNT = list.profiles.length;
  } catch { PROFILE_COUNT = 0; }
  $("#wipe-preview", ROOT).textContent = `Removes all ${PROFILE_COUNT} profile${PROFILE_COUNT === 1 ? "" : "s"}: rows, .ovpn files and every share link. The audit log is kept. This cannot be undone.`;
}

/* ---------- general ---------- */
async function saveGeneral() {
  try {
    const s = await api("/settings", {
      method: "PUT",
      body: {
        theme: $("#set-theme", ROOT).value,
        poll_status_s: Number($("#set-poll-status", ROOT).value),
        poll_lists_s: Number($("#set-poll-lists", ROOT).value),
      },
    });
    toast("Settings saved.", "success");
    try { localStorage.setItem("vc_poll_status_s", String(s.poll_status_s)); } catch { /* ignore */ }
  } catch (err) {
    toast(errorText(err), "error");
  }
}

/* ---------- password ---------- */
async function changePassword() {
  const errBox = $("#pw-err", ROOT);
  errBox.hidden = true;
  const next = $("#pw-new", ROOT).value;
  if (next !== $("#pw-repeat", ROOT).value) {
    errBox.textContent = "The new passwords do not match.";
    errBox.hidden = false;
    return;
  }
  try {
    const r = await api("/settings/password", {
      method: "POST",
      body: { current: $("#pw-current", ROOT).value, next },
    });
    toast(`Password changed. ${r.sessions_revoked} other session${r.sessions_revoked === 1 ? "" : "s"} signed out.`, "success");
    $("#pw-current", ROOT).value = "";
    $("#pw-new", ROOT).value = "";
    $("#pw-repeat", ROOT).value = "";
  } catch (err) {
    errBox.textContent = errorText(err);
    errBox.hidden = false;
  }
}

/* ---------- credential ---------- */
async function saveToken() {
  const errBox = $("#ts-err", ROOT);
  errBox.hidden = true;
  const token = $("#ts-new", ROOT).value.trim();
  if (!token) {
    errBox.textContent = "Paste the token first (it is never displayed again after saving).";
    errBox.hidden = false;
    return;
  }
  await putToken({ ts_token: token });
  $("#ts-new", ROOT).value = "";
}

async function clearToken() {
  await putToken({ ts_token: "" });
}

async function putToken(body) {
  try {
    const s = await api("/settings", { method: "PUT", body });
    toast("Credential updated. Run Test connection to verify.", "success");
    $("#ts-current", ROOT).value = s.ts_token || "(none configured)";
    await load(true);
  } catch (err) {
    const errBox = $("#ts-err", ROOT);
    errBox.textContent = errorText(err);
    errBox.hidden = false;
  }
}

async function testToken() {
  const out = $("#ts-result", ROOT);
  out.hidden = true;
  try {
    const r = await api("/settings/test-ts", { method: "POST" });
    if (r.ok) {
      out.innerHTML = `${status("ok", "Reachable")} Credential works. Tailnet
        <strong>${esc(r.tailnet)}</strong>, MagicDNS ${r.magic_dns ? "enabled" : "disabled"}
        <span class="faint">(source: ${esc(r.source || "unknown")})</span>.`;
    } else {
      out.innerHTML = `${status("err", "Unreachable")} ${esc(r.error || "The tailnet did not answer.")}`;
    }
    out.hidden = false;
  } catch (err) {
    toast(errorText(err), "error");
  }
}

/* ---------- danger zone (FR-051 tier 3) ---------- */
async function wipeProfiles() {
  const ok = await typeConfirmDialog({
    title: "Wipe the profile store?",
    body: `<p>This permanently removes <strong>all ${PROFILE_COUNT} profile${PROFILE_COUNT === 1 ? "" : "s"}</strong>:</p>
      <ul><li>every .ovpn file stored on this host</li>
      <li>every share link (distributed URLs stop working immediately)</li></ul>
      <p>The audit log is kept. <strong>There is no undo.</strong></p>`,
    phrase: "wipe-profiles",
    confirmLabel: "Wipe everything",
  });
  if (!ok) return;
  try {
    const r = await api("/settings/wipe-profiles", {
      method: "POST", body: { typed_confirm: "wipe-profiles" },
    });
    toast(`${r.profiles_removed} profile${r.profiles_removed === 1 ? "" : "s"} wiped. Audit history kept.`, "success");
    await load(true);
  } catch (err) {
    toast(errorText(err), "error");
  }
}

async function resetPolicy() {
  const ok = await typeConfirmDialog({
    title: "Reset the policy to last applied?",
    body: `<p>The <strong>last applied policy version</strong> will be pushed back to the
      tailnet, overwriting whatever is live there now, and any draft in the editor
      is discarded.</p><p><strong>There is no undo.</strong></p>`,
    phrase: "reset-policy",
    confirmLabel: "Reset policy",
  });
  if (!ok) return;
  try {
    await api("/settings/reset-policy", {
      method: "POST", body: { typed_confirm: "reset-policy" },
    });
    toast("Policy reset to the last applied version.", "success");
  } catch (err) {
    toast(errorText(err), "error");
  }
}

# Feature Specification: Unified VPN Management Console

**Feature Branch**: `001-unified-vpn-dashboard`

**Created**: 2026-10-10

**Status**: Draft

**Input**: User description: "Unified internal VPN management dashboard — single-admin, password-gated web app unifying (1) a client-side OpenVPN `.ovpn` profile library, (2) Tailscale SaaS device administration, and (3) local VPN-daemon host control (connection, routes, access policy, service exposures, host services, logs). One navigation model, one terminology glossary, friction-tiered destructive actions, attention-queue-first overview, complete audit trail."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Admin signs in through a single gate (Priority: P1)

The admin opens the dashboard and signs in with the admin password. Without signing in,
no screen, data, or action is reachable. A sign-out control ends the session on the
current browser.

**Why this priority**: Every other story sits behind this gate; nothing is demonstrable
securely without it.

**Independent Test**: Can be fully tested by attempting to open any screen while signed
out (must be blocked), signing in with the correct password (must succeed), and signing
out (must end access).

**Acceptance Scenarios**:

1. **Given** the admin is signed out, **When** any dashboard URL is opened, **Then** only
   the sign-in screen is shown and no data is retrievable.
2. **Given** the admin is signed out, **When** a wrong password is entered, **Then** access
   is denied with a clear message and repeated failures are rate-limited.
3. **Given** the admin is signed in, **When** they choose "Sign out", **Then** subsequent
   requests from that browser are unauthenticated.

---

### User Story 2 - Admin imports and organizes OpenVPN profiles (Priority: P1)

The admin drags one or more `.ovpn` files onto the Profiles page (or picks them with a
file picker). Each file is parsed and shown as a row with a status: **Valid**, **Expiring
(within 14 days)**, **Expired**, **Disabled**, or **Parse error**. Each row shows the
server address and port, protocol, cipher, client-certificate expiry date, and last-updated
time. The admin can rename profiles, assign tags/folders, search and filter the list, and
open a detail drawer showing the parsed metadata alongside the raw configuration text,
which can be edited (previous version kept, undo offered).

**Why this priority**: Managing the existing `.ovpn` profile collection is the owner's
core named need; the dashboard delivers standalone value with only this story.

**Independent Test**: Can be fully tested by importing sample `.ovpn` files (valid,
expiring, expired, malformed), verifying parse results and columns, editing one, and
filtering by tag and status.

**Acceptance Scenarios**:

1. **Given** an empty library, **When** 3 valid `.ovpn` files are dropped, **Then** 3 rows
   appear with parsed server/port/protocol/cipher/cert-expiry and status **Valid** (or
   **Expired**/**Expiring** if the certificate dates warrant), plus an "Import" success
   indication.
2. **Given** a malformed or incomplete file, **When** it is imported, **Then** it is stored
   with status **Parse error**, the failure reason is shown in the detail drawer, and the
   file is never silently discarded.
3. **Given** a file identical to an existing profile, **When** it is imported, **Then** the
   admin is asked to **Replace** the existing profile or **Keep both** — never silently
   duplicated or overwritten.
4. **Given** any profile, **When** it is renamed or tagged, **Then** the change is
   reflected immediately and an undo toast appears (no confirmation dialog). A rename is
   refused while the profile is Enabled, because its server tunnel is named after it.
4a. **Given** a profile that can run unattended, **When** the admin clicks **Enable** and
   confirms, **Then** the console installs a tunnel-only copy on this server, starts it,
   starts it again after a reboot once it has connected, and shows the tunnel address;
   **When** the admin clicks **Disable** and confirms, **Then** the tunnel stops and no
   longer starts on boot (see FR-012a to FR-012g).
5. **Given** profiles exist, **When** the admin searches free text or `key:value` tokens
   (tag, status, cipher, server), **Then** the table filters accordingly and shows the
   active-filter chips with a way to clear them.

---

### User Story 3 - Admin distributes a profile to a device (Priority: P1)

From a profile's row actions or detail drawer, the admin can: download the `.ovpn` file;
copy the configuration text; generate a QR code that encodes a **download URL** (not the
file body) so mobile VPN clients can import it by scanning; and create a temporary share
link that expires (default 24 hours) with an optional one-time-use limit. Active share
links are listed per profile and can be revoked (immediate, with undo toast while
undoable).

**Why this priority**: Getting a profile onto a phone/laptop is the library's whole
point; without distribution the library is read-only storage.

**Independent Test**: Can be fully tested by downloading a profile, scanning its QR with
a phone camera (must yield a working URL), creating a share link, using it, and revoking
it.

**Acceptance Scenarios**:

1. **Given** a stored profile, **When** "Download" is chosen, **Then** the exact current
   `.ovpn` file is delivered.
2. **Given** a stored profile, **When** "QR" is opened, **Then** the QR encodes a URL that
   resolves to the profile download, and a documented fallback mode can embed the config
   text in the QR for third-party clients.
3. **Given** a share link with default settings, **When** 24 hours pass (or the one-time
   link is used once), **Then** the link stops working and reports that it expired.
4. **Given** an active share link, **When** it is revoked, **Then** it immediately stops
   working, the revocation appears in the audit log, and an undo toast is offered while
   the previous state is retained.

---

### User Story 4 - Admin reviews the tailnet device inventory (Priority: P2)

The Devices page lists every device enrolled in the tailnet, split into two tabs —
**User Devices** and **Servers**. Each row shows: status (Online / Offline / Expired /
Needs approval / Expiring ≤14 days — always as icon + text label, never color alone),
device name with OS marker, owner, tailnet IP address (copy-on-click), tags, OS and client
version (flagged when notably stale), exit-node/subnet-route chips, key expiry date (or
"never" when expiry is disabled), and last-seen time. Clicking a row opens a detail drawer
with full identity, addresses, capabilities, and per-device actions. Search accepts
`key:value` tokens (`os:`, `tag:`, `user:`, `version:`, `is:expiring`, `is:offline`,
`is:unapproved`, `!` negation).

**Why this priority**: Safe lifecycle decisions require trustworthy visibility; inventory
precedes mutation.

**Independent Test**: Can be fully tested against a tailnet containing online, offline,
unapproved, expiring, and tagged devices — verifying tab segmentation, columns, filters,
and the detail drawer — without performing any mutation.

**Acceptance Scenarios**:

1. **Given** the tailnet contains laptops and servers, **When** the Devices page opens,
   **Then** they are separable via the User Devices / Servers tabs and each row renders
   every specified column.
2. **Given** a device with key expiry in 10 days, **When** the table renders, **Then** the
   device shows the amber **Expiring** state with the date and "in 10d" phrasing; a device
   with expiry disabled shows **"never"**.
3. **Given** the drawer of any device, **When** opened, **Then** identity, addresses,
   owner, tags, version, last seen, key-expiry control, route/capability status, and the
   action set (Approve, Expire key now, Delete) are all visible without leaving the page.
4. **Given** a filter query `is:unapproved` (or `tag:server !os:ios`), **When** entered,
   **Then** only matching devices are listed.

---

### User Story 5 - Admin manages device lifecycle with tiered friction (Priority: P2)

From the inventory or drawer, the admin can approve a pending device, expire a device key
now, toggle "Require periodic re-authentication" (labeling the consequence, not the
mechanism), edit tags, edit advertised routes (approve/decline), and delete a device.
Friction is tiered: approve/tag = immediate with feedback; expire key = confirm dialog
naming the device and its consequence; delete device = type-to-confirm naming the device,
with the button disabled until the typed text matches; disconnecting the local VPN daemon
= type-to-confirm plus a self-lockout warning and a "I am connected via LAN/physical
console" acknowledgment checkbox.

**Why this priority**: These are the highest-consequence mutations in the product; they
must exist but are dangerous enough to demand the research-backed friction.

**Independent Test**: Can be fully tested by exercising each action against a test
tailnet and verifying both the effect and the exact friction tier that gated it.

**Acceptance Scenarios**:

1. **Given** an unapproved device, **When** "Approve" is chosen, **Then** the device joins
   without a dialog and a success toast confirms it.
2. **Given** any device, **When** "Expire key now" is chosen, **Then** a confirm dialog
   states the device disconnects until re-authentication; confirming disconnects it, and
   no undo is offered (Tailscale-side mutation).
3. **Given** any device, **When** "Delete" is chosen, **Then** a dialog requires typing the
   device name; the danger button stays disabled until the text matches, and the body names
   the consequence (immediate deauthorization, re-authentication required to rejoin).
4. **Given** the "Require periodic re-authentication" toggle is switched off for a device,
   **Then** a short confirmation explains affected users will not be asked to re-login
   periodically.
5. **Given** every mutation in this story, **When** it executes, **Then** an audit entry
   with actor/action/target/outcome is recorded.

---

### User Story 6 - Admin sees what needs attention at a glance (Priority: P2)

The Overview page leads with an **attention queue**: actionable items sorted by severity
then age — expiring/expired profile certificates, expired or unapproved devices,
disconnected local daemon, failed host services, active public exposures, policy
validation errors — each with severity dot + label, message, target link, and one inline
action. When nothing is wrong it reads "All clear." Below it, five stat tiles summarize:
Local node state; Devices (N online / M total, amber/red badges); Profiles (N enabled /
M total with expiry badges); Exposures (N tailnet / M public, public count red-accented
whenever > 0); Services (N of M running). Quick actions follow: Import profiles; Connect
a new device (a command-crafting helper that emits a copy-paste enrollment instruction);
Download last-used profile. Recent activity (last 10 audit events) closes the page.

**Why this priority**: The owner's first question — "is anything wrong?" — must be
answered in seconds without visiting each subsystem.

**Independent Test**: Can be fully tested by seeding each attention condition one at a
time and verifying it appears in the queue with the right severity and inline action, and
that resolving it removes it.

**Acceptance Scenarios**:

1. **Given** one profile certificate expired yesterday and one device is unapproved,
   **When** Overview loads, **Then** both appear in the attention queue, the expired
   certificate ranked higher, each with a working target link and a single inline action.
2. **Given** a public exposure is active, **When** Overview loads, **Then** the Exposures
   tile's public count is red-accented and an attention item is present.
3. **Given** everything healthy, **When** Overview loads, **Then** the queue shows "All
   clear" and no tiles carry warning badges.
4. **Given** the Connect-a-device helper, **When** opened for a server, **Then** it emits
   a complete copy-paste enrollment instruction (one-time key or pre-authorized command)
   tailored to the chosen OS.

---

### User Story 7 - Admin edits tailnet access policy safely (Priority: P3)

The Access Control page shows the tailnet policy file in a text editor that preserves
comments and formatting, alongside a read-only **structured view** of the parsed rules
(groups, tags, hosts, grants). Editing flows: **Validate** (errors shown inline with line
references) → **diff summary** (rules added/removed versus the applied policy) → **Apply**
→ a pinned **one-click "Rollback to previous policy"** for the session. The applied file
is always the source of truth; the structured view is generated from it.

**Why this priority**: Policy mistakes can lock the admin out; validate-diff-apply-rollback
makes the riskiest text-editing surface safe. Needed after core inventory flows.

**Independent Test**: Can be fully tested by loading a policy with comments, introducing
a syntax error (validation must block apply), applying a valid change (diff must describe
it), and rolling back (file must return byte-identical).

**Acceptance Scenarios**:

1. **Given** a policy containing comments, **When** it is edited and applied, **Then**
   comments survive in the applied file.
2. **Given** an edit with a syntax or reference error, **When** "Validate" runs, **Then**
   apply is blocked and the error is shown with its location.
3. **Given** a valid edit, **When** "Apply" runs, **Then** a diff summary (added/removed
   rules) is shown before confirmation and a rollback action stays available afterward.
4. **Given** an applied change, **When** "Rollback" is chosen once, **Then** the previous
   policy is restored and the rollback is audit-logged.

---

### User Story 8 - Admin controls the local VPN node and its routes (Priority: P3)

The Local Node page shows this server's daemon state (connected/disconnected/service
stopped), its tailnet addresses, version, and a connectivity self-check summary. The admin
can connect/disconnect (with the story-5 friction for disconnect), choose whether the
server advertises itself as an **exit node**, select which exit node this server uses (if
any), and manage its **advertised subnet routes** with per-route approval state.

**Why this priority**: The server is both a managed device and a routing hub; route and
exit-node changes are routine but medium-risk.

**Independent Test**: Can be fully tested by reading current state, toggling exit-node
advertisement, selecting an exit node, and advertising/withdrawing one subnet route —
verifying each change is reflected after completion.

**Acceptance Scenarios**:

1. **Given** the daemon connected, **When** the page loads, **Then** state, addresses,
   version, and self-check results are shown with explicit data freshness.
2. **Given** exit-node advertisement off, **When** switched on, **Then** the advertisement
   takes effect and the change is visible in the route list.
3. **Given** one or more advertised subnets, **When** a route is withdrawn, **Then** it
   disappears from the advertised list and the action is audit-logged.

---

### User Story 9 - Admin manages host services and reads their logs (Priority: P3)

The Services page lists managed host services (the VPN daemon, OpenVPN client services if
present, the dashboard's own service) with running/stopped state, uptime-since, an
enable-on-boot toggle, and Start/Stop/Restart actions (Restart = confirm naming the unit
and expected downtime; progress feedback during execution). The Logs page offers a
per-unit log viewer with severity filter, text search, live-follow toggle, time range, and
download.

**Why this priority**: When something breaks, the admin needs one place to restart the
unit and read its logs without leaving the dashboard.

**Independent Test**: Can be fully tested by restarting a harmless unit, observing the
progress feedback, filtering its logs by severity and text, and downloading them.

**Acceptance Scenarios**:

1. **Given** a running unit, **When** "Restart" is confirmed, **Then** progress is shown
   and the final state is reported; "Stop" is styled as the dangerous variant.
2. **Given** any unit's logs, **When** filtered to errors containing a search term, **Then**
   only matching lines are shown, newest first, with the live-follow toggle available.
3. **Given** a stopped unit, **When** "Start" is chosen, **Then** the unit starts and its
   state dot turns running.

---

### User Story 10 - Admin reviews and controls what the server exposes (Priority: P3)

The Exposures page lists all Serve (tailnet-only), Funnel (public), and Taildrive (file
share) entries: target, protocol/port, scope badge (**Tailnet** = blue; **Public —
Funnel** = red with globe icon), DNS name, certificate status, and an enable toggle.
Creating or enabling a Funnel entry requires a red-accented confirm dialog that names the
exact public URL, states it becomes reachable from the public internet, and shows the
allowed-port constraint (443/8443/10000). A **raw ports** card lists every listening port
on the server annotated as funnel / serve / local-only / unexposed, and warns when
serve/funnel targets collide on one port.

**Why this priority**: Public exposure is the product's only internet-facing risk surface;
it needs first-class visibility, but safe defaults keep it out of the critical path.

**Independent Test**: Can be fully tested with one serve entry and one funnel entry
configured — verifying badges, the funnel confirm dialog, port-constraint enforcement,
collision warning, and the raw-ports annotations.

**Acceptance Scenarios**:

1. **Given** one serve and one funnel entry, **When** the page loads, **Then** scope badges
   distinguish them (blue vs red + label) and each shows target, port, DNS name, and cert
   status.
2. **Given** a new Funnel entry on an allowed port, **When** created, **Then** the confirm
   dialog names the public URL and the internet-reachability consequence before it goes
   live.
3. **Given** a Funnel request on a disallowed port, **When** submitted, **Then** it is
   rejected up front with the 443/8443/10000 constraint stated.
4. **Given** a serve and funnel targeting the same port, **When** both exist, **Then** a
   collision warning explains the most-recent-configuration-wins rule.
5. **Given** the raw ports card, **When** read, **Then** every listening port carries
   exactly one exposure annotation.

---

### User Story 11 - Admin inspects the full audit trail (Priority: P3)

The Audit Log page (top-level section) lists every action the dashboard performed —
including undos and failed attempts — reverse-chronologically with timestamp, action,
target, originating section, outcome, and a detail expander. Filters cover action type,
section, outcome, and date range; the log can be exported. Entries are append-only and
never editable or deletable from the UI.

**Why this priority**: Single-admin trust depends on being able to answer "what exactly
did I change, and when?" — including after mistakes.

**Independent Test**: Can be fully tested by performing one action of each tier (undoable,
confirmed, type-to-confirm, failed) and verifying each appears with correct fields and
survives filtering/export.

**Acceptance Scenarios**:

1. **Given** recent actions across profiles, devices, policy, and services, **When** the
   page loads, **Then** all appear newest-first with complete fields.
2. **Given** an undo executed within its window, **When** the log is read, **Then** both
   the original action and the undo are recorded as linked entries.
3. **Given** a failed mutation (e.g., unreachable external service), **When** the log is
   read, **Then** the failure — not only successes — is recorded with an error summary.
4. **Given** any filter combination, **When** applied, **Then** only matching entries are
   listed and the export contains exactly the filtered set.

---

### User Story 12 - Admin tunes the dashboard in Settings (Priority: P3)

Settings offers: change admin password (current password required); manage the external
VPN-service access credential (stored masked, with a "Test connection" action reporting
reachability and account/plan scope); refresh/poll intervals for status vs list data; UI
theme; and a type-to-confirm danger zone (wipe local profile store, reset policy to last
applied). Settings changes are audit-logged.

**Why this priority**: Required for operability and credential rotation, but nothing on
the page blocks the core stories.

**Independent Test**: Can be fully tested by changing the password and signing in with it,
testing the external credential, adjusting intervals, and exercising one danger-zone wipe
on a scratch instance.

**Acceptance Scenarios**:

1. **Given** the current password, **When** it is changed, **Then** future sign-ins require
   the new password and the change is audit-logged.
2. **Given** a masked external credential, **When** "Test connection" runs, **Then** a
   clear reachable/unreachable result with scope summary is returned and the credential is
   never displayed in full after initial entry.
3. **Given** a danger-zone wipe, **When** the operation name is typed and confirmed,
   **Then** the local store is emptied, a warning preview states exactly what will be
   lost, and the action is audit-logged.

---

### Edge Cases

- **Duplicate profile names**: two profiles may share a display name; the system
  disambiguates by unique identity and flags the duplicate visually.
- **Very large or multi-remote configs**: profiles with multiple `remote` lines show all
  endpoints; files beyond a documented size limit are rejected with a clear message.
- **Missing certificate block**: an `.ovpn` without an inline client cert/key shows
  **Parse error** with reason "missing certificate block" but remains downloadable.
- **Expired profiles stay downloadable**: an expired-cert profile is downloadable but
  carries the red state and an attention item; deletion is never automatic.
- **External service unreachable**: device/policy pages show a per-subsystem health
  banner, keep the last data visibly marked stale with its age, and disable mutation
  actions rather than appearing live.
- **Local daemon control interface unreachable**: Local Node, Exposures, Services, and
  Logs degrade to explicit "unavailable" states — never silent emptiness.
- **Self-lockout**: disconnecting the local daemon while the admin is connected over the
  tailnet triggers the typed confirmation + LAN acknowledgment; the warning names the
  exact loss of access.
- **Port collisions**: a serve and funnel on the same port produce a standing warning
  naming the most-recent-wins rule.
- **Share link already used/expired**: attempting to open a dead link shows a clear
  expiry message; revoked links report "revoked" in the owner's list.
- **Clock skew**: expiry-derived states tolerate minor clock differences by using the
  server's clock consistently and displaying dates alongside relative times.
- **Browser closed mid-undo**: undos expire silently with their window; the audit log
  records both the original action and that no undo occurred.
- **Empty everything**: first run shows guided empty states with exactly one primary
  action per page (import profiles / connect device / all clear).

## Requirements *(mandatory)*

### Functional Requirements

**Access & shell**

- **FR-001**: System MUST gate every screen and data request behind single-admin password
  authentication, with rate-limited failures and a sign-out control.
- **FR-002**: System MUST present a persistent left sidebar with exactly these sections in
  order: Overview, Profiles, Devices, Access Control, Local Node, Exposures, Services,
  Logs, Audit Log, Settings — each one URL-addressable.
- **FR-003**: The topbar MUST provide global search (profiles + devices, accepting
  `key:value` tokens) and a backend health indicator per subsystem (external service
  reachable, local daemon reachable, host-control reachable).
- **FR-004**: System MUST support light and dark presentation from one design system, with
  the owner's selected visual direction applied consistently on every screen.

**Profiles**

- **FR-010**: System MUST accept `.ovpn` files via drag-and-drop and file picker, in
  multi-file batches, and parse each: server endpoints, port, protocol, cipher, and
  client-certificate expiry.
- **FR-011**: System MUST assign each profile exactly one status — Valid, Expiring (≤14
  days), Expired, Disabled, Parse error — recomputed from certificate dates and enabled
  state.
- **FR-012**: System MUST offer per-profile row actions: Download, QR, Copy config, Share
  link, Edit, Disable/Enable, Delete — with Delete as a confirm dialog. Enable and Disable
  change this server's real VPN tunnel and so use confirm dialogs (FR-012a to FR-012g),
  not the undo toast.
- **FR-012a**: **Enable** MUST write a tunnel-only copy of the profile to
  `/etc/openvpn/client/<name>.conf` (root-only, marked as written by the console) and start
  `openvpn-client@<name>`; once it has connected and passed FR-012b, it MUST also be enabled
  for boot, so a profile that never connected is not retried at every reboot. **Disable**
  MUST stop it and turn boot start off. New imports and system scans start Disabled, and nothing starts or stops when
  the console itself starts.
- **FR-012b**: A console tunnel MUST use its own interface name (`vc-<profile id>`, never
  `tunN`) and MUST NOT take over the server's routing: a pushed default route and DNS are
  ignored, default-route lines in the profile are commented out of the installed copy, and
  after it connects the tunnel is stopped and disabled if any of its routes replaces the
  default route or overlaps an existing route (this server's own network, Docker,
  Tailscale, or a tunnel started by hand).
- **FR-012c**: Enable MUST refuse a profile that cannot run unattended (files outside the
  profile, expired certificate, parse error) and say which line is the reason. A profile
  that signs in with a username and password MUST keep those credentials in a root-only
  file next to the installed config (`<name>.auth`, mode 0600) that the config points at:
  an inline `<auth-user-pass>` block MUST be lifted into that file rather than left in the
  config, and a profile with no credentials anywhere MUST collect them in the Enable dialog
  (typing the profile name, because a password is landing on the server) or be refused with
  a reason the dialog can act on. Credentials set in the console take precedence over ones
  inside the profile; the stored profile is never modified; and the password MUST NOT
  appear in any API response, the config editor, or the audit log. A profile with script
  lines (`up`, `down`, `route-up`, `plugin`, `tls-verify`, `script-security 2` or higher)
  MUST list those lines and require the profile name to be typed. Lines that write files or
  open ports (`log`, `status`, `writepid`, `management`, `daemon`, `chroot`) MUST be removed
  from the installed copy with a notice.
- **FR-012d**: Enable MUST show progress while the tunnel connects (up to about 100 s) and
  report the tunnel address, or the last log lines if it did not come up. A tunnel counts
  as connected only when its interface has an address (OpenVPN tells systemd it is ready
  before it has connected). One with no address when the wait runs out MUST be stopped and
  left off for boot, so it can never connect later without the FR-012b check. Every outcome
  MUST be written to the audit log.
- **FR-012e**: Editing a profile that has a running tunnel MUST ask for confirmation,
  rewrite the installed copy and restart the tunnel; undo and revert do the same. An edit
  that cannot be applied (new script lines, a config that cannot run unattended) is saved
  but not applied, and the console says so.
- **FR-012f**: Deleting a profile removes it from the console only. Its server tunnel and
  installed config are left as they are, and the Delete dialog says so.
- **FR-012g**: Changes to a server tunnel MUST be refused while the host layer cannot be
  read, and a config the console did not write MUST never be overwritten.
- **FR-013**: System MUST keep the previous version of an edited profile config and offer
  undo (≈10 s toast) plus "revert to previous version" in the detail drawer.
- **FR-014**: System MUST generate QR codes encoding a download URL by default, with an
  explicit embed-config fallback mode.
- **FR-015**: System MUST support temporary share links with configurable expiry (default
  24 h) and optional one-time use, list active links per profile, and support immediate
  revocation (undoable while retained).
- **FR-016**: Profile files MUST be stored in plain form (owner's explicit decision;
  changing this requires a recorded owner amendment).

**Devices**

- **FR-020**: System MUST display the tailnet inventory segmented into User Devices and
  Servers tabs with the full column set: status (icon + label), name + OS marker, owner,
  tailnet IP (copy-on-click), tags, OS·version with staleness flag, exit/route chips, key
  expiry (absolute + relative, "never" when disabled), last seen.
- **FR-021**: Search/filtering MUST accept `key:value` tokens — `os:`, `tag:`, `user:`,
  `version:`, `is:expiring`, `is:offline`, `is:unapproved` — with `!` negation, applied to
  devices and profiles.
- **FR-022**: System MUST support device actions Approve, Expire key now, toggle "Require
  periodic re-authentication", Edit tags, Approve/decline advertised routes, Delete — each
  at its friction tier (immediate / confirm / type-to-confirm).
- **FR-023**: Expiry thresholds (14-day warning) MUST be shown as dates + relative time;
  expired and expiring states MUST be visually distinct from offline.

**Overview**

- **FR-030**: Overview MUST render, in order: attention queue, five stat tiles (Local
  node, Devices, Profiles, Exposures, Services), quick actions, recent activity (last 10
  audit events).
- **FR-031**: The attention queue MUST include at minimum: expiring/expired profile
  certificates; expired, unapproved, or stale devices; local daemon down; failed host
  services; active public exposures; policy validation errors — each with severity,
  message, target link, and one inline action; resolved items disappear on next refresh.
- **FR-032**: The Exposures tile MUST accent its public count in red whenever it exceeds
  zero; red MUST otherwise be reserved for broken/error states.

**Policy, node, exposures, services**

- **FR-040**: The policy editor MUST preserve comments/formatting, validate server-side
  before apply, show a rule-level diff versus the applied policy, support apply, and pin a
  one-click rollback for the session.
- **FR-041**: A read-only structured view MUST be generated from the applied policy file
  (groups, tags, hosts, grants); the file remains the single source of truth.
- **FR-042**: Local Node MUST show daemon state, addresses, version, connectivity
  self-check, and support connect/disconnect (typed confirm + self-lockout warning + LAN
  acknowledgment for disconnect), exit-node advertisement toggle, exit-node selection, and
  subnet-route advertise/withdraw with approval states.
- **FR-043**: Exposures MUST list Serve/Funnel/Taildrive entries with scope badges and
  enforce the funnel port constraint (443/8443/10000) before creation; funnel creation
  requires the red-accented public-URL confirm dialog.
- **FR-044**: A raw ports view MUST annotate every listening port as funnel / serve /
  local-only / unexposed and warn on serve/funnel port collisions.
- **FR-045**: Services MUST list managed units with state, since, enable-on-boot toggle,
  and Start/Stop/Restart (confirm + progress feedback); Logs MUST offer per-unit viewing
  with severity filter, text search, live follow, time range, and download.

**Safety, audit, hygiene**

- **FR-050**: Every mutation MUST write an append-only audit entry (timestamp, action,
  target, section, outcome, detail) including undos and failures; entries are neither
  editable nor deletable from the UI; the log is filterable and exportable.
- **FR-051**: Friction tiers MUST be: local recoverable ops → undo toast, no dialog;
  external-service mutations & service restarts → confirm dialog with specific body,
  outcome-labeled buttons, no default focus; irreversible/high-blast (delete device, bulk
  deletes, daemon disconnect, danger zone) → type-to-confirm. Confirmations MUST NOT stack.
- **FR-052**: Status MUST always be icon/dot + text label (never color alone), using only
  the semantic set: green healthy, blue informational/tailnet, amber caution, red
  error/internet-facing, gray inert/unknown.
- **FR-053**: Each subsystem's health state MUST be visible; when data cannot be refreshed
  the UI MUST mark it stale with its age and disable dependent mutations.
- **FR-054**: Empty states MUST contain one sentence of explanation and exactly one
  primary action.

### Key Entities

- **Profile**: one `.ovpn` connection file — display name, tags/folder, endpoints,
  protocol, cipher, certificate expiry, status, enabled flag, config text, prior versions,
  share links.
- **Share Link**: temporary distribution URL for a profile — expiry, one-time flag, usage
  count, revoked flag.
- **Device**: a tailnet-enrolled machine — name, owner, addresses, OS/version, tags,
  online state, last seen, key expiry (+ disabled flag), approval state, advertised
  routes/capabilities; classified as user device or server.
- **Policy File**: the tailnet access policy — applied version, draft version, comments,
  derived structured rules, last validation result, rollback target.
- **Exposure**: one Serve/Funnel/Taildrive entry — target, port/protocol, scope
  (tailnet/public/share), DNS name, certificate status, enabled flag.
- **Port Annotation**: one listening port with its exposure classification.
- **Service Unit**: one managed host service — state, since, enabled-on-boot.
- **Log Stream**: one unit's log entries with severity and timestamp.
- **Audit Event**: immutable record — timestamp, action, target, section, outcome, detail,
  linked undo event (if any).
- **Attention Item**: derived alert — severity, message, target reference, suggested
  action, resolved condition.
- **Settings**: admin password (hashed), external credential (masked), poll intervals,
  theme, tailnet label.

**Terminology (binding for all UI copy)**: *Profile* = a library item; *config* = its raw
text. *Device* (never "node"/"peer"/"machine" in user-facing copy; technical views may
quote the vendor term). *Cert expiry* (profile X.509) and *key expiry* (device enrollment)
are distinct concepts and never interchangeable. *Funnel* = public exposure (never just
"share"); *Serve* = tailnet-only exposure; *Taildrive* = file share. *Local node* = this
server's own daemon instance.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A signed-out visitor cannot retrieve any screen or data (verified by
  attempting each section unauthenticated).
- **SC-002**: Importing 10 valid `.ovpn` files and reaching a scannable QR for one takes
  under 60 seconds end-to-end.
- **SC-003**: "Is anything wrong?" is answerable from Overview within 5 seconds: every
  seeded problem condition appears in the attention queue within one refresh cycle
  (≤15 s of occurring).
- **SC-004**: 100% of state-changing actions appear in the audit log immediately,
  including undos and failures (verified by an action-matrix test).
- **SC-005**: 100% of destructive operations enforce their friction tier per FR-051
  (verified by a dialog-matrix test across every mutating action).
- **SC-006**: Every status display passes the no-color-alone check (icon + label present)
  and red appears only on error/internet-facing states.
- **SC-007**: Expiring a device key takes ≤3 interactions from the device list; publishing
  and unpublishing a service exposure each take ≤4 interactions.
- **SC-008**: An ACL edit containing a syntax error can never be applied (validation
  blocks it), and a valid applied change can be rolled back in one interaction.
- **SC-009**: Lists remain responsive (visible rendering, no errors) at 250 devices and
  200 profiles; interactions feel immediate at these sizes.
- **SC-010**: When any subsystem is unreachable, its screens show the stale/unavailable
  state with data age within one refresh cycle — never presenting stale data as live.

## Assumptions

- **Single admin, English UI.** No roles, tenants, or localization in this feature.
- **Desktop-first**, tablet-acceptable; phone use is limited to reading status and
  scanning QRs (full management on phones is out of scope for v1).
- **Scale**: one tailnet, up to ~250 devices; profile library up to ~200 files; a single
  dashboard instance.
- **Deployment**: the dashboard runs on the same host as the VPN daemon with access to its
  local control interface and to the Tailscale cloud service via an owner-provided
  credential; it is reachable only on the internal network (any public exposure of the
  dashboard itself is an explicit, separately-confirmed act).
- **Plan features**: Serve/Funnel/Taildrive availability follows the owner's Tailscale
  plan; if a mechanism is unavailable the page states why instead of hiding it.
- **Audit retention**: entries are retained indefinitely until the danger-zone wipe; no
  automatic pruning in v1.
- **Share links default to 24 h expiry**, one-time use optional; QR encodes a URL by
  default (mobile-client compatibility), embed-config is a labeled fallback.
- **Refresh cadence defaults**: status/health ≈10–15 s; list data ≈60 s; both adjustable
  in Settings.
- **Expiry warning threshold: 14 days** for both profile certificates and device keys
  (matches research recommendation; adjustable later).
- The owner has selected the visual direction from the 20-proposal gallery before
  implementation of UI screens begins (constitution gate); this spec is direction-neutral.

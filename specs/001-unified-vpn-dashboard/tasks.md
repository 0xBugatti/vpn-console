---
description: "Task list for feature 001-unified-vpn-dashboard"
---

# Tasks: Unified VPN Management Console

**Input**: Design documents from `/specs/001-unified-vpn-dashboard/`

**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅, quickstart.md ✅

**Tests**: INCLUDED — Constitution Principle VI (Testable Control Layer) mandates
interface/adapter/integration tests against mocks; no live credentials (research D9).
Tests are listed FIRST in each story phase and must FAIL before their implementation.

**Organization**: Tasks grouped by user story (US1–US12 per spec.md priorities).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1…US12)

## Path Conventions

Single Python service per plan.md (NOT the generic backend/frontend split):
`server/` (FastAPI app + adapters + `server/static/` SPA), `tests/`, `deploy/`.
The SPA is hand-written static files — there is no frontend build tree (Principle I).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization, dependencies, fixtures, fonts

- [X] T001 Create project skeleton per plan.md structure: `server/`, `server/api/`, `server/adapters/`, `server/static/`, `tests/unit/`, `tests/contract/`, `tests/integration/`, `tests/fixtures/`, `deploy/` (empty `__init__.py` where packages)
- [X] T002 [P] Initialize Python project: `pyproject.toml` + `uv.lock` with runtime deps fastapi, uvicorn, httpx, cryptography, segno and dev dep pytest (research D-dependencies; nothing else — Principle I)
- [X] T003 [P] Vendor webfonts into `server/static/fonts/` (Manrope, Inter, Geist Mono woff2, OFL) + `@font-face` in `server/static/styles.css` — zero runtime CDN (research D6)
- [X] T004 [P] Create test fixtures: `tests/fixtures/ovpn/` (valid.ovpn, expiring.ovpn cert ≤14d, expired.ovpn, no-cert.ovpn, multi-remote.ovpn, oversize.ovpn >1_048_576 bytes), `tests/fixtures/tailscale/` (devices.json, acl.json, users.json, tailnet.json, error-429.json), `tests/fixtures/cli/` (serve-status.json, drive-status.json, ss-tulpen.txt, systemctl-show.json, journal.json)
- [X] T005 [P] Create `tests/conftest.py`: FastAPI TestClient fixture, tmp-path SQLite, fake adapters wired via `VPNCONSOLE_ADAPTERS=fake`, signed-in client helper

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure every story depends on — health envelope, audit, DB,
shell, fakes, filter language

**⚠️ CRITICAL**: No user story work until this phase is complete

- [X] T006 Implement SQLite layer in `server/db.py`: connection mgmt, schema for profiles, share_links, policy_versions, settings, audit; **append-only triggers on audit** (`AFTER UPDATE/DELETE RAISE(ABORT)` — research D8)
- [X] T007 [P] Implement `server/adapters/base.py`: `Health` + `Result` dataclasses exactly per contracts/adapters.md (state ok|degraded|unavailable, detail, last_ok, age_seconds)
- [X] T008 Implement append-only audit repository in `server/audit.py`: `insert()` + `query()` ONLY; filters action/section/outcome/from/to/cursor per contracts/api.md; never exposes update/delete (FR-050)
- [X] T009 [P] Implement fakes in `tests/fakes.py`: FakeCloud/FakeLocal/FakeHost per contracts/adapters.md with mutable scenario state (unapproved device, expiring key, failed unit, public exposure) and `break(subsystem)` switch
- [X] T010 Implement app wiring in `server/app.py`: FastAPI instance, adapter selection via `VPNCONSOLE_ADAPTERS=real|fake` env, static mount at `/`, JSON error envelope `{error:{code,message,detail}}`, router registration hooks
- [X] T011 Implement auth framework in `server/auth.py`: HMAC-SHA256-signed session cookie (HttpOnly, SameSite=Lax, 7-day TTL), `require_admin` dependency, in-memory login rate limiter (5 failures/min/remote-addr → 429) (research D7)
- [X] T012 Implement env/config in `server/settings.py`: ADMIN_PASSWORD, TS_API_TOKEN, TS_TAILNET (env-preferred, never logged or returned), poll TTLs (status 10 s, lists 60 s — research D10/D12)
- [X] T013 Implement SPA shell in `server/static/index.html` + `server/static/app.js` + `server/static/styles.css`: hash router, sidebar with exactly the 10 sections in FR-002 order, topbar with global search + 3 subsystem health dots (FR-003), token CSS from design-system/MASTER.md (light + dark, FR-004), api client, poll loop skeleton, toasts, dialogs (3 friction tiers FR-051), ⌘K palette stub
- [X] T014 [P] Create `server/static/icons.js`: inlined Lucide SVG paths (nav, status dots, OS markers, actions, globe for Funnel) — every status renders icon+label (FR-052)
- [X] T015 [P] Implement shared key:value filter engine in `server/searchlang.py`: tokens `os:` `tag:` `user:` `version:` `is:expiring|offline|unapproved` `status:` `cipher:` `server:` with `!` negation, shared by profiles + devices (FR-021, contracts/api.md)
- [X] T016 Implement per-subsystem TTL cache in `server/adapters/base.py` (status 10 s / lists 60 s) + `GET /api/health` in `server/api/overview.py` returning all three HealthStates (research D10); integration test `tests/integration/test_health.py`: `break("tscloud")` → payload carries stale `_health` with age and mutations return 409 subsystem_unavailable (SC-010)

**Checkpoint**: Foundation ready — user story implementation can begin

---

## Phase 3: User Story 1 — Admin signs in through a single gate (P1) 🎯 MVP

**Goal**: Password gate blocks everything; sign-in/sign-out work; failures rate-limited

**Independent Test**: Open any URL signed out → blocked; wrong password → denied; correct → in; sign-out → locked out again (spec US1)

### Tests for User Story 1

- [X] T017 [P] [US1] Integration tests in `tests/integration/test_auth.py`: unauthenticated request to EVERY section → 401 (SC-001); wrong password → 401 + message; 6th failure within a minute → 429; logout invalidates cookie; every attempt (ok/failed) audit-logged

### Implementation for User Story 1

- [X] T018 [US1] Implement scrypt password hash/verify + first-run bootstrap from ADMIN_PASSWORD env in `server/settings.py` (research D7; hash never leaves the process)
- [X] T019 [US1] Implement `server/api/auth.py`: POST /api/auth/login (verify → cookie → audit `auth.login`), POST /api/auth/logout, GET /api/auth/me; failed logins audited with outcome `failed` (FR-001)
- [X] T020 [US1] Create sign-in screen (`#/login` route in `server/static/app.js` + markup in `server/static/index.html` + form styles in `server/static/styles.css`): password field, inline error, rate-limit notice, no default focus per MASTER friction spec
- [X] T021 [US1] Add Sign out control to shell topbar in `server/static/app.js` (ends session → `#/login`)

**Checkpoint**: Gate fully functional — every other section unreachable signed out

---

## Phase 4: User Story 2 — Admin imports and organizes OpenVPN profiles (P1)

**Goal**: Drag-drop `.ovpn` import with parse chips, full table, tags/search, edit with undo

**Independent Test**: Import valid/expiring/expired/malformed samples → rows with correct status/columns; duplicate → Replace-or-Keep-both; rename/tag/disable work; search filters (spec US2)

### Tests for User Story 2

- [X] T022 [P] [US2] Unit tests in `tests/unit/test_ovpn.py` against all `tests/fixtures/ovpn/`: multi-endpoint parsing, cipher/data-ciphers, cert `notAfter` via cryptography, "missing certificate block" reason, 1_048_576-byte cap rejection, multi-remote shows ALL endpoints (research D4, spec edge cases)
- [X] T023 [P] [US2] Integration tests in `tests/integration/test_profiles.py`: multi-file import → rows; duplicate sha256 → `duplicate_of` flag + replace/keep_both second call; PATCH name/tags/enabled/config_text keeps `previous_text` + returns `undo_token`; DELETE without `{confirm:true}` → 409; bulk-delete without `typed_confirm:"DELETE"` → 409; search tokens `tag:` `status:` `cipher:` `server:` + `!`; oversize → clear rejection message

### Implementation for User Story 2

- [X] T024 [US2] Implement `.ovpn` parser in `server/ovpn.py`: strict line parser (`remote`, `proto`, `cipher`/`data-ciphers`, `tls-version`, `auth-user-pass`, inline `<ca>/<cert>/<key>/<tls-auth>` blocks) + X.509 expiry via `cryptography` (`not_valid_after_utc`); name ≤120 chars; pure function (research D4)
- [X] T025 [US2] Implement profiles read/import in `server/api/profiles.py`: POST /api/profiles/import (multipart multi-file → per-file `{name,status,parse_error?,duplicate_of?}`), GET /api/profiles (q/tag/status via searchlang, status recomputed on read per data-model state machine), GET /api/profiles/{id}; `_health` not needed (local store)
- [X] T026 [US2] Implement profiles mutations in `server/api/profiles.py`: PATCH (config edit stores previous_text, FR-013), DELETE (confirm tier), POST /api/profiles/bulk-delete (typed tier); audit every mutation incl. failures (FR-050)
- [X] T027 [US2] Implement undo store + endpoint: `server/undo.py` (in-memory, 10 s window per FR-013/FR-051) + `POST /api/undo/{undo_token}` in `server/api/undo.py`; undo writes linked audit entry (`undoes_event_id`, outcome `undone` — data-model AuditEvent)
- [X] T028 [US2] Build Profiles UI in `server/static/`: drag-drop + picker import zone with per-file parse chips (ok / missing cert block / duplicate → Replace-or-Keep-both dialog), table per FR-011/FR-012 (status dot+label: Valid/Expiring/Expired/Disabled/Parse error; endpoints; cipher; cert expiry; updated), row actions, active-filter chips with clear, empty state (one sentence + one primary action, FR-054)
- [X] T029 [US2] Build profile detail drawer UI: parsed metadata + raw config editor with "Revert to previous version" + disable/enable toggle → undo toast (tier 1, no dialog) + Delete → confirm dialog (tier 2) naming the profile with outcome-labeled button (FR-012/FR-013/FR-051)

**Checkpoint**: Library is fully usable standalone — the owner's core named need works

---

## Phase 5: User Story 3 — Admin distributes a profile to a device (P1)

**Goal**: Download, copy, QR (URL-first), temporary share links with revocation

**Independent Test**: Download returns exact file; QR resolves to working URL; share link expires/one-time/revokes correctly (spec US3)

### Tests for User Story 3

- [X] T030 [P] [US3] Integration tests in `tests/integration/test_share.py`: download returns exact current bytes + `X-Profile-Status` header for expired/disabled (spec edge case); QR url mode = `/s/{token}` and embed mode = config; default expiry +24 h; one-time → second fetch 410 `used`; expired → 410 `expired`; revoked → 410 `revoked` + undo restores; `GET /s/{token}` works UNauthenticated (documented exception) and is audit-logged on use

### Implementation for User Story 3

- [X] T031 [US3] Implement share links in `server/sharelinks.py`: 22-char urlsafe token, expires_at (default 24 h), one_time flag + used_count, revoked_at with 10 s retained prior state for undo (research D5, data-model state machine)
- [X] T032 [US3] Implement endpoints in `server/api/profiles.py` + new `server/api/share.py`: GET download, GET qr (segno SVG, `mode=url|embed`, FR-014), POST/GET links, DELETE /api/links/{token} (undo_token), GET /s/{token} → 302, GET /api/share/{token}/download (410 reasons); audit `link.create`/`link.revoke`/`link.use`
- [X] T033 [US3] Build distribution UI: row actions Download/Copy/QR/Share link, QR modal with mode toggle (URL default + labeled embed fallback) and size, share-link dialog (expiry selector, one-time checkbox), active-links list with revoke → undo toast (FR-015)

**Checkpoint**: P1 trio complete — full profile lifecycle works end-to-end (SC-002 reachable)

---

## Phase 6: User Story 4 — Admin reviews the tailnet device inventory (P2)

**Goal**: Devices page with User Devices/Servers tabs, full columns, token search, drawer

**Independent Test**: Read-only against fixtures: tabs split correctly, all columns render, filters match, drawer shows identity + action set (spec US4)

### Tests for User Story 4

- [X] T034 [P] [US4] Contract test in `tests/contract/test_tscloud.py` via `httpx.MockTransport` + `tests/fixtures/tailscale/*.json`: list_devices maps every field; `is_server` = has server-class tag OR owner null (data-model rule); staleness = ≥2 minor versions behind tailnet max; 429/error fixture → health `degraded` with detail (research D3)
- [X] T035 [P] [US4] Integration tests in `tests/integration/test_devices.py`: tab query param; row fields incl. expiry "never" when expiry_disabled, relative "in 10d"; filters `is:expiring` `is:offline` `is:unapproved` `tag:server !os:ios`; drawer payload complete; unreachable fake → stale payload + disabled mutations (FR-053)

### Implementation for User Story 4

- [X] T036 [US4] Implement TailscaleCloud adapter in `server/adapters/tscloud.py`: injected `httpx.Client` (10 s timeout), bearer token from settings, all methods per contracts/adapters.md, error mapping (429/5xx/timeout → degraded, connection errors → unavailable) (research D3)
- [X] T037 [US4] Implement `server/api/devices.py`: GET /api/devices (tab=users|servers, q via searchlang), GET /api/devices/{id}; every payload carries `_health`
- [X] T038 [US4] Build Devices UI: tabs, table per FR-020 (status icon+label Online/Offline/Expired/Needs approval/Expiring; name+OS marker; owner; 100.x copy-on-click; tag chips; OS·version with amber stale flag; exit/route chips; key expiry absolute+relative; last seen), detail drawer shell, search box with token chips (FR-021), stale banner with data age + disabled actions (FR-053)

**Checkpoint**: Inventory is trustworthy and read-complete

---

## Phase 7: User Story 5 — Admin manages device lifecycle with tiered friction (P2)

**Goal**: Approve / expire key / reauth toggle / tags / routes / delete at exact friction tiers

**Independent Test**: Exercise each action against fakes; verify effect AND the tier that gated it (spec US5)

### Tests for User Story 5

- [X] T039 [P] [US5] Integration tests in `tests/integration/test_device_actions.py` — the friction matrix (SC-005): approve succeeds with no confirm; expire-key without `{confirm:true}` → 409 `confirm_required`; delete without typed name → 409 `typed_confirm_required`; 100% of mutations (incl. a forced failure) audit-logged with outcome ok|failed (SC-004)

### Implementation for User Story 5

- [X] T040 [US5] Implement actions in `server/api/devices.py` + `server/adapters/tscloud.py`: POST approve, POST expire-key, PATCH tags/require_reauth/routes_approved, DELETE; enforce confirm codes per contracts/api.md; failures → audit outcome `failed` with error summary
- [X] T041 [US5] Build drawer actions UI: Approve immediate + success toast; Expire key now → confirm dialog naming device + "disconnects until re-authentication", no undo offered, outcome-labeled button, no default focus; Delete → type-to-confirm disabled until exact device name; "Require periodic re-authentication" off-toggle → short consequence confirm; tags/routes editors (FR-022, FR-051 tiers)

**Checkpoint**: Highest-consequence mutations are live with research-backed friction

---

## Phase 8: User Story 6 — Admin sees what needs attention at a glance (P2)

**Goal**: Attention-queue-first Overview, 5 stat tiles, quick actions, recent activity

**Independent Test**: Seed each condition one at a time → appears with right severity + inline action; resolve → disappears (spec US6)

### Tests for User Story 6

- [X] T042 [P] [US6] Unit tests in `tests/unit/test_attention.py`: every condition (expiring/expired certs, expired/unapproved/stale devices, daemon down, failed services, public exposure, policy errors) → item with severity+message+target+inline action; ordering severity→age; empty → all-clear (FR-031, data-model AttentionItem)
- [X] T043 [P] [US6] Integration tests in `tests/integration/test_overview.py`: tile counts incl. Exposures public>0 accent flag (FR-032); recent = last 10 audit events; connect-device helper returns OS-tailored one-time-key instruction for server (US6 scenario 4)

### Implementation for User Story 6

- [X] T044 [US6] Implement attention derivation in `server/attention.py`: pure functions over profiles/devices/local/services/exposures/policy drafts; 14-day constants server-side (research D11)
- [X] T045 [US6] Implement GET /api/overview in `server/api/overview.py` (attention + tiles + recent) + POST /api/settings/test-ts stays US12; implement connect-a-device helper (creates one-time auth key via `create_auth_key`, emits copy-paste `tailscale up --auth-key=…` instruction per OS)
- [X] T046 [US6] Build Overview UI: attention queue (severity dot + label, message, target link, exactly one inline action each, "All clear" empty state FR-054), 5 stat tiles per FR-030 (public count red-accented when >0), quick actions (Import / Connect a device helper dialog / Download last profile), recent-activity table (FR-030/032)

**Checkpoint**: "Is anything wrong?" answerable in ≤5 s (SC-003)

---

## Phase 9: User Story 7 — Admin edits tailnet access policy safely (P3)

**Goal**: HuJSON editor preserving comments + structured view + Validate → diff → Apply → Rollback

**Independent Test**: Load commented policy, break syntax → apply blocked with line error; valid change → diff describes it; rollback → byte-identical (spec US7, SC-008)

### Tests for User Story 7

- [X] T047 [P] [US7] Contract test in `tests/contract/test_tscloud.py` (extend): `get_acl_text` → `put_acl_text` round-trip preserves bytes incl. comments (research D14)
- [X] T048 [P] [US7] Integration tests in `tests/integration/test_acl.py`: draft with syntax/reference error → `{valid:false, errors:[{line,message}]}` and apply → 409 `validation_failed`; valid edit → diff added/removed; apply without confirm → 409; rollback restores byte-identical text + audit `acl.rollback`

### Implementation for User Story 7

- [X] T049 [US7] Implement `server/acl.py`: server-side HuJSON parse/validate (grants/acls/groups/tagOwners/hosts/nodeAttrs) with `{line,message}` errors, rule-level set diff, applied text is canonical — never re-serialized (research D14, FR-040)
- [X] T050 [US7] Implement `server/api/acl.py`: GET (applied_text + structured + draft), PUT draft, GET diff, POST apply (confirm tier, stores PolicyVersion, pins session rollback), POST rollback; audit `acl.apply`/`acl.rollback`
- [X] T051 [US7] Build ACL UI: editor preserving formatting, read-only structured view generated from file (FR-041), Validate → inline errors with line refs → diff panel → Apply confirm → pinned one-click "Rollback to previous policy" (FR-040)

**Checkpoint**: Riskiest text surface is safe (SC-008)

---

## Phase 10: User Story 8 — Admin controls the local VPN node and its routes (P3)

**Goal**: Local Node page: state, connect/disconnect, exit-node, subnet routes

**Independent Test**: Read state, toggle exit-node advertisement, select exit node, advertise/withdraw a route (spec US8)

### Tests for User Story 8

- [X] T052 [P] [US8] Contract test in `tests/contract/test_tslocal.py` vs `tests/fixtures/cli/*.json`: status/prefs/serve/drive JSON mapping; missing socket → `unavailable` with hint (research D1/D2)
- [X] T053 [P] [US8] Integration tests in `tests/integration/test_node.py`: disconnect without `typed_confirm:"DISCONNECT"` → 409; without `lan_ack:true` → 409 with self-lockout detail; exit-node toggle + route advertise/withdraw reflected + audit-logged

### Implementation for User Story 8

- [X] T054 [US8] Implement TailscaleLocal adapter in `server/adapters/tslocal.py`: HTTP over `/var/run/tailscale/tailscaled.socket` (`/localapi/v0/status`, `/localapi/v0/prefs`) + CLI subprocess with `--socket=` injection for serve/funnel/drive JSON (research D1)
- [X] T055 [US8] Implement `server/api/node.py`: GET state, POST connect, POST disconnect (typed + lan_ack), POST exit-node, POST routes (per contracts/api.md); audit all
- [X] T056 [US8] Build Local Node UI: status card with explicit freshness, connect/disconnect (type-to-confirm "DISCONNECT" + self-lockout warning naming exact loss of access + "I am connected via LAN/physical console" checkbox), exit-node advertise/use controls, subnet-route list with per-route approval state (FR-042)

**Checkpoint**: The server is controllable as a routing hub

---

## Phase 11: User Story 9 — Admin manages host services and reads their logs (P3)

**Goal**: Services page (start/stop/restart/enable + progress) and Logs page (filters, live follow, download)

**Independent Test**: Restart harmless unit with progress; filter logs by severity+text; download (spec US9)

### Tests for User Story 9

- [X] T057 [P] [US9] Contract test in `tests/contract/test_host.py` vs fixtures: systemctl show mapping, journal severity mapping (priority 0–3 → err+), ss -tulpen → PortAnnotation parse (research D2, data-model)
- [X] T058 [P] [US9] Integration tests in `tests/integration/test_services_logs.py`: unit allow-list enforced; stop/restart without confirm → 409; job lifecycle via GET /api/jobs/{id}; log filters severity/q/after cursor + limit ≤500; download endpoint; mounts-absent → `unavailable` state (not empty)

### Implementation for User Story 9

- [X] T059 [US9] Implement HostControl adapter in `server/adapters/host.py`: systemctl/journalctl against mounted host socket (allow-list: tailscaled, openvpn@*, vpn-console), `ss -tulpen` port parse, absent mounts → `unavailable` + deploy hint (research D2)
- [X] T060 [US9] Implement `server/api/services.py` (units, actions → in-memory job ids, GET /api/jobs/{id}) + `server/api/logs.py` (units, lines with severity/q/after/limit, cursor per research D13, download)
- [X] T061 [US9] Build Services UI (state/since/enable-on-boot toggle, Start/Stop/Restart — Restart confirm names unit + expected downtime, progress toasts, Stop styled dangerous) + Logs UI (unit picker, severity filter, text search, live-follow polling 2–3 s, time range, download button) (FR-045)

**Checkpoint**: Break-fix loop (restart + read logs) closed inside the dashboard

---

## Phase 12: User Story 10 — Admin reviews and controls what the server exposes (P3)

**Goal**: Exposures page: Serve/Funnel/Taildrive with scope badges, funnel constraints, raw ports

**Independent Test**: One serve + one funnel entry: badges, funnel confirm, port constraint, collision warning, port annotations (spec US10)

### Tests for User Story 10

- [X] T062 [P] [US10] Integration tests in `tests/integration/test_exposures.py`: funnel on disallowed port → 400 `port_not_allowed` (443/8443/10000 only); funnel create/enable without confirm → 409; entries carry scope tailnet|public|share; ports annotated exactly one of funnel|serve|local_only|unexposed per listening port; same-port serve+funnel → collision warning (FR-043/044)

### Implementation for User Story 10

- [X] T063 [US10] Implement `server/api/exposures.py`: GET (entries from tslocal serve/funnel/drive + PortAnnotation join from host + computed collisions), POST (funnel port constraint BEFORE friction), PATCH enable, DELETE; funnel ops are confirm-tier (research D1, contracts/api.md)
- [X] T064 [US10] Build Exposures UI: table with scope badges (Tailnet = blue; Public — Funnel = red + globe icon, FR-052), red-accented funnel confirm dialog naming exact public URL + internet-reachability consequence + allowed-port note, enable toggles, raw ports card with collision warning naming most-recent-wins rule

**Checkpoint**: The only internet-facing surface is first-class and guarded

---

## Phase 13: User Story 11 — Admin inspects the full audit trail (P3)

**Goal**: Audit Log page: filterable, exportable, append-only, undo-linked

**Independent Test**: One action of each tier + a failure → all present with fields; filters + export exact (spec US11, SC-004)

### Tests for User Story 11

- [X] T065 [P] [US11] Integration tests in `tests/integration/test_audit.py`: action matrix (undoable + undone link, confirmed, typed, failed) all present newest-first with complete fields; filter combos; export JSON contains EXACTLY the filtered set; UPDATE/DELETE against audit table raises (trigger, T006)

### Implementation for User Story 11

- [X] T066 [US11] Implement `server/api/audit.py`: GET with action/section/outcome/from/to/cursor pagination, GET export (filtered set → JSON attachment per contracts/api.md)
- [X] T067 [US11] Build Audit Log UI: reverse-chron table (timestamp, action, target, section, outcome, detail expander), filters, export button, no edit/delete affordances anywhere (FR-050)

**Checkpoint**: "What exactly did I change, and when?" is answerable incl. mistakes

---

## Phase 14: User Story 12 — Admin tunes the dashboard in Settings (P3)

**Goal**: Password change, masked credential + test, poll intervals, theme, danger zone

**Independent Test**: Change password → old fails/new works; test connection reports scope; danger-zone wipe on scratch instance (spec US12)

### Tests for User Story 12

- [X] T068 [P] [US12] Integration tests in `tests/integration/test_settings.py`: password change requires current + audits + invalidates other sessions; GET never returns full token (masked `••••1234`, data-model Settings); POST test-ts → `{ok,tailnet,magic_dns}` via fake; danger zone without typed_confirm=operation name → 409; wipe empties profile store + audits

### Implementation for User Story 12

- [X] T069 [US12] Implement `server/api/settings.py`: GET (masked), PUT, POST password (scrypt re-hash, keep current session), POST test-ts (via tscloud `test()`), POST wipe-profiles + reset-policy (typed tier, danger zone)
- [X] T070 [US12] Build Settings UI: password form (current+new), masked credential field + "Test connection" button with scope result, poll interval inputs (status/list), theme selector (light/dark/system), danger zone with warning preview stating exactly what is lost + type-to-confirm (FR-051 tier 3)

**Checkpoint**: Operability + credential rotation complete

---

## Phase 15: Polish & Cross-Cutting Concerns

**Purpose**: Cross-story correctness and deployment

- [X] T071 Implement ⌘K command palette in `server/static/app.js`: sections + quick actions + search handoff (MASTER.md component; stub from T013 completed)
- [X] T072 [P] Stale-data sweep: every mutating UI control checks `_health` of its subsystem before enabling; stale banners show data age everywhere data renders (FR-053, SC-010)
- [X] T073 [P] Empty-state audit across all 10 pages: one sentence + exactly one primary action (FR-054)
- [X] T074 [P] Responsive + accessibility pass per MASTER.md shell spec + accessibility checklist (sidebar collapse breakpoints, focus order, contrast both themes)
- [X] T075 Create `deploy/Dockerfile` (python:3.12-slim + tailscale CLI + non-root), `deploy/compose.yaml` (`network_mode: host`, mounts: tailscaled socket, `/run/systemd/private`, `/run/dbus/system_bus_socket`, `/var/log/journal` + `/run/log/journal` ro, `data/` volume; env ADMIN_PASSWORD/TS_API_TOKEN/TS_TAILNET), `deploy/README-deploy.md` (host prep, first run, quadlet alternative — research D2/D12)
- [X] T076 [P] Create `README.md`: what it is, run tests, fake-mode walkthrough, deploy pointer
- [X] T077 Run `quickstart.md` validation end-to-end (full pytest + fake-mode walkthrough per acceptance scenarios) and fix all findings

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (1)** → **Foundational (2)** → all stories. Foundational is the only hard gate.
- **US1 (gate)** must precede any manual UI testing of other stories, but code-wise stories 2–12 depend only on Phase 2.
- Natural build order (P1 → P3): US1 → US2 → US3 → US4 → US5 → US6 → US7 → US8 → US9 → US10 → US11 → US12.
- Adapter stories pair contract-test-first: US4 (tscloud) before US5 (cloud actions); US8 (tslocal) before US10 (exposures consume both tslocal + host); US9 (host) before US10's ports join.
- **Polish (15)** after all stories; T077 (quickstart validation) is the final gate.

### User Story Dependencies

- **US2**: needs T006/T008/T015 only — independent of all other stories
- **US3**: needs US2's store (profiles must exist to distribute)
- **US4/US5**: need T007/T009/T016 + T036; US5 needs US4's adapter
- **US6**: reads from US2 (profiles), US4/US5 (devices), US8–US10 subsystems where present — degrades gracefully per story (missing subsystems simply yield no attention items); implement after US5 for full coverage, re-verified after US10
- **US7**: needs tscloud ACL methods (extends T036/T047)
- **US8**: independent (tslocal); **US9**: independent (host); **US10**: needs US8 + US9
- **US11**: reads audit written by every story — testable from Phase 3 onward, page build any time after Phase 2
- **US12**: independent; danger-zone wipe touches US2's store

### Parallel Opportunities

- Within Setup: T002/T003/T004/T005 all [P]
- Within Foundational: T007/T009/T014/T015 [P]
- All test tasks marked [P] can be written alongside their story's implementation start
- Story-level: after Phase 2, {US2→US3}, {US4→US5}, US8, US9, US11, US12 are mutually independent lines
- T072/T073/T074/T076 all [P] in Polish

---

## Parallel Example: User Story 2

```bash
# Tests first (parallel, different files):
Task: "Unit tests for parser in tests/unit/test_ovpn.py"        # T022
Task: "Integration tests in tests/integration/test_profiles.py" # T023
# Then implementation in dependency order:
Task: "server/ovpn.py parser"                                   # T024
Task: "server/api/profiles.py read/import"                      # T025
Task: "server/api/profiles.py mutations"                        # T026
Task: "server/undo.py + server/api/undo.py"                     # T027
Task: "Profiles UI"                                             # T028, T029
```

---

## Implementation Strategy

### MVP First (P1 trio — Phases 1–5)

1. Complete Setup + Foundational
2. US1 → validate gate (SC-001)
3. US2 → validate import/organize independently
4. US3 → validate distribution (SC-002)
5. **STOP**: the dashboard already delivers the owner's core named need safely

### Incremental Delivery

- +US4/US5 → tailnet visibility and safe lifecycle
- +US6 → glanceable operations
- +US7/US8/US9/US10 → full control surfaces
- +US11/US12 → trust and operability
- Polish → deployable artifact (T075) validated by quickstart (T077)

### Notes

- Every story's UI conforms to design-system/MASTER.md; page-specific choices go in
  `design-system/overrides/<page>.md`, never by redefining tokens/status/friction
- No live Tailscale/systemd at any point in Phases 1–14 (fakes only) — Constitution VI
- Commit after each task or logical group; stop at any checkpoint to validate the story

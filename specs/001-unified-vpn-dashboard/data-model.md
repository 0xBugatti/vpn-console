# Phase 1 Data Model — vpn-console

Entities from spec "Key Entities", with fields, validation, and state machines.
Types: SQLite storage on the left of `:`; API shape mirrors `api/schemas.py`.

## Profile

One `.ovpn` file in the library. Stored: DB row + plain file on the volume.

| Field | Type | Rules |
|---|---|---|
| id | TEXT | `p_` + 12-char urlsafe |
| name | TEXT | display name, editable, duplicates allowed (spec edge), ≤ 120 chars |
| tags | TEXT (JSON array) | user-assigned, chips in UI |
| file_path | TEXT | relative to volume store |
| size_bytes | INT | ≤ 1_048_576 (1 MiB cap) |
| endpoints | TEXT (JSON) | parsed `[{host, port, proto}]` from `remote` lines (all of them) |
| cipher | TEXT | `cipher`/`data-ciphers` head, else `null` → "N/A" chip |
| tls_version_min | TEXT | optional |
| has_auth_user_pass | INT | bool |
| cert_expires_at | TEXT (ISO) / NULL | client-cert `notAfter` via cryptography; NULL = parse issue/no inline cert |
| parse_error | TEXT / NULL | human reason ("missing certificate block") |
| status | TEXT | derived, see state machine |
| enabled | INT | user toggle; default 1 |
| config_text | TEXT | current config bytes (also on disk) |
| previous_text | TEXT / NULL | last version kept for undo/revert (FR-013) |
| updated_at | TEXT (ISO) | import/edit time |

**Status state machine** (recomputed on read; server-authoritative):
`Valid` ⇄ `Expiring(≤14d)` → `Expired` — driven by `cert_expires_at` vs server clock;
`Disabled` overlays any state when `enabled=0`; `Parse error` when `parse_error` set
(file still downloadable). Transitions are pure functions of (cert date, enabled) —
no stored transitions.

## ShareLink

| Field | Type | Rules |
|---|---|---|
| token | TEXT | 22-char urlsafe secret |
| profile_id | TEXT | FK → Profile (cascade delete) |
| created_at | TEXT | |
| expires_at | TEXT | default +24 h, configurable at creation |
| one_time | INT | default 0 |
| used_count | INT | |
| revoked_at | TEXT / NULL | |

State machine: `active` → `expired` (clock) | `used` (one_time ∧ download) | `revoked`
(undoable while `previous state` retained 10 s window server-side → audit-logged either
way). Terminal states reject download with 410 + reason (`expired|used|revoked`).

## Device (view model — never stored)

Projected from the Tailscale cloud API + (for the local node itself) the local adapter.
Classification rule: `is_server` = has `tag:server`-class tag OR owner is null/tagged —
drives the User Devices / Servers tab split (spec FR-020).

Identity: `id, name (MagicDNS), dns_name, os, version, owner, addresses[100.x],
tags[], online (last_seen < 5 min), last_seen, key_expiry (ISO|"never"),
expiry_disabled, approval_state (pending|approved), advertised_routes[{route, approved}],
exit_node_candidate, serve_funnel_active[]`. Version staleness: `is_stale` = device
version ≥ 2 minor behind tailnet max (amber chip).

## PolicyVersion

| Field | Type | Rules |
|---|---|---|
| id | INT autoincrement | |
| text | TEXT | applied HuJSON bytes — canonical, never re-serialized (D14) |
| applied_at | TEXT | |
| note | TEXT | audit link / diff summary |

Draft is session-scoped in memory: `{text, validated: bool, errors[]}`. Transitions:
`applied → (edit) draft → validate ok → (diff shown) → applied'` with previous `applied`
row retained; `rollback` = re-apply previous row (one click, session-pinned, audit-logged).
Validation errors: `{line, message}` from server-side HuJSON parse (grants/acls, groups,
tagOwners, hosts, nodeAttrs).

## Exposure

Projected from `tailscale serve|funnel|drive status --json` (D1): `{kind:
serve|funnel|taildrive, target, port, proto, scope: tailnet|public|share, dns_name,
cert_status, enabled}`. Scope `public` ⇒ red semantics (MASTER §3). Creation constraints:
funnel port ∈ {443, 8443, 10000}; serve/funnel same-port collision → warning record
(most-recent-wins, spec FR-044).

## PortAnnotation

From `ss -tulpen`: `{proto, local_addr, port, process, annotation:
funnel|serve|local_only|unexposed}` — joined against current Exposures.

## ServiceUnit

`{name (allow-listed), state: running|stopped|failed, since, enabled_on_boot}` — from
`systemctl show` (D2). Actions: start/stop/restart/enable/disable; restart returns
progress via pollable job id (in-memory, single instance).

## LogStream

Projected from `journalctl -o json -u {unit} --since/--until`; cursor = ISO timestamp +
boot id. Query params: `severity` (map priority 0–3 err+), `q` (text), `after` (cursor),
`limit ≤ 500`. No log storage — read-only passthrough.

## AuditEvent (append-only; trigger blocks UPDATE/DELETE — D8)

| Field | Type |
|---|---|
| id | INT (ordered) |
| ts | TEXT ISO UTC |
| action | TEXT (`profile.import`, `profile.delete`, `device.expire_key`, `acl.apply`, `node.disconnect`, `service.restart`, `link.create`, `undo.*`, `auth.login`, …) |
| section | TEXT (`profiles|devices|acl|node|exposures|services|logs|audit|settings|auth`) |
| target | TEXT (id/name) |
| outcome | TEXT (`ok|undone|failed|denied`) |
| detail | TEXT (JSON) — error summaries, diff summaries, actor IP |

`undoes_event_id` links undo → original.

## AttentionItem (derived — never stored)

Computed per Overview request from: profiles (cert expiry), devices (expired keys,
pending approval, stale last-seen > 7 d), local node (down while expected up), services
(failed), exposures (`scope=public` active), policy (draft validation errors). Fields:
`{severity: red|amber, code, message, target_href, target_label, inline_action,
age}` — sorted severity→age (spec FR-031, SC-003).

## Settings (singleton row + key/value)

`password_scrypt {salt, hash}`, `ts_token` (env-preferred; if stored, masked in API
responses — never returned in full after initial entry), `tailnet_name`, `poll_status_s
(default 12)`, `poll_lists_s (60)`, `theme (light|dark|system)`. Danger-zone actions
(wipe profiles DB, reset policy) are endpoints, not fields.

## HealthState (per subsystem)

`{subsystem: tscloud|tslocal|host, state: ok|degraded|unavailable, detail, last_ok,
age_seconds}` — carried on every list payload (`_health` key) and aggregated at
`/api/health` (D10).

## Relationships

Profile 1—* ShareLink · Profile *—* Tag · PolicyVersion self-history (rollback target =
previous applied) · Exposure/PortAnnotation/ServiceUnit/Device are projections (no FKs) ·
AuditEvent standalone (targets by string reference, survives target deletion) ·
AttentionItem derives from all of the above at read time.

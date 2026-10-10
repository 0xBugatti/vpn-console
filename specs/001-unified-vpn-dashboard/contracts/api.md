# HTTP API Contract — vpn-console

Base: `/api` · JSON bodies · Session cookie auth (D7) on everything except
`POST /api/auth/login` and `GET /s/{token}` (documented exception).
Every list/detail payload carries `_health: HealthState` (D10).
Errors: `{error: {code, message, detail?}}` — 400 validation, 401 unauth, 403 denied,
404 missing, 409 conflict (`confirm_required`, `typed_confirm_required`,
`subsystem_unavailable`, `validation_failed`), 410 dead share link, 429 rate-limited.
Mutating endpoints REQUIRE the friction evidence inline (Principle III):

- Simple mutations: direct call → audit + undo-able response `{..., undo_token}`
  (undo: `POST /api/undo/{token}` within 10 s window).
- Confirm-tier: `{confirm: true}` in body, else 409 `confirm_required`.
- Typed-tier: `{typed_confirm: "<device name | DELETE | DISCONNECT>"}` matching exactly,
  else 409 `typed_confirm_required`. (tailscaled disconnect additionally requires
  `lan_ack: true` — else 409 `confirm_required` with that detail.)

## Auth
- `POST /api/auth/login` `{password}` → `200 {ok: true}` + cookie · 429 after 5 fails/min/IP
- `POST /api/auth/logout` → 204 · `GET /api/auth/me` → `{admin: true}`

## Overview & health
- `GET /api/overview` → `{attention: AttentionItem[], tiles: {node, devices,
  profiles, exposures, services}, recent: AuditEvent[≤10]}` (spec FR-030/031)
- `GET /api/health` → `{subsystems: {tscloud, tslocal, host: HealthState}}`

## Profiles
- `GET /api/profiles?q=&tag=&status=` → list (columns per FR-010/011; `q` supports
  `tag:` `status:` `cipher:` `server:` tokens)
- `POST /api/profiles/import` multipart multi-file → per-file
  `{name, status, parse_error?, duplicate_of?}` (duplicate → 200 with flag; caller
  chooses `replace|keep_both` in a second call)
- `GET /api/profiles/{id}` → detail incl. parsed metadata + config_text
- `PATCH /api/profiles/{id}` `{name?|tags?|enabled?|config_text?}` → edit; config edit
  keeps previous_text (FR-013); `enabled` toggle → undo_token
- `DELETE /api/profiles/{id}` `{confirm: true}` → audit + delete
- `POST /api/profiles/bulk-delete` `{ids[], typed_confirm: "DELETE"}`
- `GET /api/profiles/{id}/download` → `text/x-openvpn-profile` attachment (disabled
  profiles download with `X-Profile-Status: expired|disabled` header — spec edge case)
- `GET /api/profiles/{id}/qr?mode=url|embed&size=` → `image/svg+xml`
- `POST /api/profiles/{id}/share` `{expires_hours?, one_time?: false}` → `{token, url, expires_at, one_time, status}`
- `GET /api/profiles/{id}/shares` · `DELETE /api/shares/{token}` (returns undo_token)

## Share route (no auth — D7)
- `GET /s/{token}` → landing HTML (name + status warning + one Download button)
- `GET /s/{token}/download` → profile file attachment; consuming a one-time link;
  gone (expired/used/revoked) → 410 HTML with the reason

## Devices (Tailscale cloud)
- `GET /api/devices?tab=users|servers&q=` (`os:` `tag:` `user:` `version:` `is:expiring`
  `is:offline` `is:unapproved` `!` negation — shared filter engine with profiles)
- `GET /api/devices/{id}` → full detail (FR-020)
- `POST /api/devices/{id}/approve` → ok (no dialog tier)
- `POST /api/devices/{id}/expire-key` `{confirm: true}`
- `PATCH /api/devices/{id}` `{tags?|require_reauth?|routes_approved?[]}`
- `DELETE /api/devices/{id}` `{typed_confirm: "<device name>"}`

## Access control
- `GET /api/acl` → `{applied_text, structured[], draft?}`
- `PUT /api/acl/draft` `{text}` → `{valid, errors[{line,message}]?}` (D14)
- `GET /api/acl/diff` → `{added[], removed[]}` rule-level
- `POST /api/acl/apply` `{confirm: true}` → applied + rollback pinned (session)
- `POST /api/acl/rollback` → re-apply previous (audit-logged)

## Local node
- `GET /api/node` → `{state, addresses, version, netcheck, exit_node: {advertising,
  using}, subnet_routes: [{route, advertised, approved}]}` (tslocal adapter)
- `POST /api/node/connect` · `POST /api/node/disconnect`
  `{typed_confirm: "DISCONNECT", lan_ack: true}`
- `POST /api/node/exit-node` `{advertise?: bool, use?: id|null}`
- `POST /api/node/routes` `{advertise: [+cidr, -cidr]}`

## Exposures
- `GET /api/exposures` → `{entries: Exposure[], ports: PortAnnotation[],
  collisions: [port]}` (FR-043/044)
- `POST /api/exposures` `{kind, target, port, scope}` — funnel: port constraint check →
  400 `port_not_allowed` unless 443/8443/10000; creation of funnel is confirm-tier
- `PATCH /api/exposures/{id}` `{enabled}` (funnel enable = confirm-tier)
- `DELETE /api/exposures/{id}` `{confirm: true}`

## Services & logs (host adapter)
- `GET /api/services` → ServiceUnit[] (allow-list) · `POST /api/services/{unit}/{action}`
  action ∈ start|stop|restart|enable|disable; stop/restart = confirm-tier → `{job_id}`
  pollable via `GET /api/jobs/{id}` → `{done, ok, detail}`
- `GET /api/logs?units=` → units+facets · `GET /api/logs/{unit}?severity=&q=&after=&limit=`
  → `{lines[{ts, prio, msg}], next_cursor}` (poll 2–3 s while open — D13)

## Audit & settings
- `GET /api/audit?action=&section=&outcome=&from=&to=&limit&cursor` → page + next_cursor
- `GET /api/audit/export?same filters` → JSON attachment (filtered set — SC-004)
- `GET /api/settings` → masked (`ts_token: "••••1234"`) · `PUT /api/settings` (audit)
- `POST /api/settings/test-ts` → `{ok, tailnet, magic_dns, plan_note?}` (D3 reachability)
- `POST /api/settings/password` `{current, next}` (audit; sessions except current kept)
- Danger zone (typed_confirm = operation name): `POST /api/settings/wipe-profiles` ·
  `POST /api/settings/reset-policy`

## Undo
- `POST /api/undo/{undo_token}` → restores prior state where retained (profile
  disable/edit, link revoke); records `outcome: undone` on the original event (SC-004).

## Adapter contracts — see [adapters.md](adapters.md)

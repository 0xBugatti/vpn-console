# Phase 0 Research — vpn-console

All spec-level unknowns were resolved during owner Q&A (see spec Assumptions). This file
records the remaining technical decisions. Format: Decision / Rationale / Alternatives.

**D1 — Local tailscaled control: HTTP over the Unix socket first, CLI second.**
The daemon exposes a local API on `/var/run/tailscale/tailscaled.socket` (status, prefs,
exit-node selection, route advertisement). Serve/Funnel/Taildrive status is most complete
via `tailscale serve status --json` / `tailscale drive status --json` CLI calls against
the same socket. Decision: `tslocal` adapter = socket HTTP (`/localapi/v0/status`,
`/localapi/v0/prefs`) + CLI subprocess (JSON flags) for serve/funnel/drive; every
invocation injects `--socket=`. Rationale: stable JSON, no screen-scraping; CLI stays for
the gaps. Alternatives: CLI-only (brittle text parsing), embedding tsnet (heavy, second
node identity — rejected).

**D2 — systemd/journal from inside the container: bind mounts, no privileges.**
Mount host `/run/systemd/private` (and `/run/dbus/system_bus_socket`) into the container;
ship `systemctl`+`journalctl` in the image; mount `/var/log/journal` + `/run/log/journal`
read-only for logs. The `host` adapter calls `systemctl --no-pager` / `journalctl -o json`
scoped to an allow-list of units (tailscaled, openvpn@*, the console's own unit).
Alternatives: privileged container (broader blast radius than the feature needs —
rejected); SSH to host (extra credential + moving part — rejected). If mounts are absent
the adapter reports `unavailable` (Principle VII) and the deploy README shows the compose
lines. Listening-port view: parse `ss -tulpen` output (mounted `/proc` gives container
visibility; run with `host` network namespace via compose `network_mode: host` — also the
correct mode for a tailscale-adjacent console).

**D3 — Tailscale cloud API: `https://api.tailscale.com/api/v2`, bearer token.**
Token (owner-provided API token or OAuth client secret) lives in env/`TS_API_TOKEN`,
never in the DB or repo. Endpoints used: `GET /tailnet/{t}/devices`, `POST
/device/{id}/approved-routes`, `POST /device/{id}/tags|key-expiry`, `DELETE /device/{id}`,
`GET/PUT /tailnet/{t}/acl`, `GET /tailnet/{t}/users`, auth keys `POST /tailnet/{t}/keys`.
Adapter takes an injected `httpx.Client` → tests run `httpx.MockTransport` with recorded
JSON fixtures. 10 s timeout; 429/5xx → `degraded` health with retry-after respected.

**D4 — `.ovpn` parsing: strict line parser + `cryptography` for X.509.**
Parse `remote host port proto` (multiple), `proto`, `cipher`/`data-ciphers`, `tls-version`,
`auth-user-pass` presence, inline `<ca>/<cert>/<key>/<tls-auth>` blocks. Cert expiry =
`x509.load_pem_x509_certificate(...).not_valid_after_utc` via `cryptography`. Status
recompute happens server-side on read (import/edit/cron) — one source of truth.
Alternatives: `ssl._test_decode_cert` (private API — rejected), `openssl` subprocess
(extra process per import — rejected). File cap 1 MiB (spec edge case).

**D5 — QR + share links: `segno` (pure Python) → SVG.**
QR encodes `GET /s/{token}` (spec FR-014: URL first), with explicit `embed=1` fallback
mode that renders the config itself (documented per OpenVPN Connect behavior). Share
tokens: 22-char `secrets.token_urlstring`, stored hashed? — no: tokens are already
unguessable secrets at rest in the owner's own DB; store plaintext for revocation list
display, scope: single-admin instance. One-time links flip to `used` on first download.

**D6 — Frontend: vanilla ES modules, hash router, token CSS, zero runtime CDN.**
Internal network may lack internet: all assets vendored — Manrope/Inter/Geist Mono woff2
(OFL) in `static/fonts/`, Lucide icon paths inlined in `icons.js`. Hash routing
(`#/devices`, `#/devices/{id}` drawer state) keeps the server a pure API + static host.
Alternatives: Tailwind CDN (runtime internet + utility sprawl vs MASTER tokens —
rejected), any framework/build (violates Principle I — rejected).

**D7 — Auth: password → signed session cookie; share links are the documented exception.**
Password hashed with `hashlib.scrypt` (stdlib) from `ADMIN_PASSWORD` env or
`deploy/admin-password.txt` (chmod 600) on first run. Session = HMAC-SHA256-signed token
(stdlib) in HttpOnly SameSite=Lax cookie, 7-day TTL, server-side revocation list in
memory (single instance). Login rate limit 5/min/remote-addr. Everything under `/api/*`
requires it except `POST /api/auth/login`. `GET /s/{token}` intentionally bypasses the
gate (it exists to hand profiles to devices) — expiration/one-time/revocation are its
controls; banner-documented in Settings.

**D8 — Audit: SQLite append-only, enforced by trigger.**
`audit` table has an `AFTER UPDATE/DELETE RAISE(ABORT)` trigger — even a bug cannot
rewrite history. Repository exposes `insert()` + `query()` only. Undo events link via
`undoes_event_id`. Export = filtered SELECT → JSON download.

**D9 — Testing: pytest, three layers, no live systems.**
Unit: parser, share-link state machine, attention derivation. Contract: each adapter vs
recorded fixtures (`fixtures/tailscale/*.json`, `fixtures/cli/*.json`, sample `.ovpn`s
incl. expiring/expired/malformed/oversize). Integration: FastAPI `TestClient` with fake
adapters wired in `conftest.py`; covers friction tiers (409 when confirm/typed-confirm
missing), audit completeness, health degradation (fake adapter raises → envelope shows
stale + mutations 409).

**D10 — Health/staleness envelope: `{state, data, age_seconds, error}`.**
Every adapter response carries state `ok|degraded|unavailable` + data age. `GET
/api/health` aggregates per subsystem. Server caches successful fetches per subsystem
(TTL 10 s status / 60 s lists) and serves cache with age on failure — never silently
(SPEC FR-053). Mutations to a degraded subsystem return 409 `subsystem_unavailable`.

**D11 — Time: UTC internally, server-authoritative; client renders relative ("in 6d")**
plus absolute on hover/detail. Expiry thresholds (14 d) server-side constants in
`attention.py`.

**D12 — Deployment: compose on the tailscaled host, `network_mode: host`.**
Image = `python:3.12-slim` + `tailscale` CLI + non-root user; bind mounts per D2 +
tailscaled socket (read-write — control ops need it); env: `ADMIN_PASSWORD`,
`TS_API_TOKEN`, `TS_TAILNET` ( `-` for default), volumes: `data/` (SQLite + `.ovpn`
store). The console's own unit name is `vpn-console.service` (quadlet or compose
`restart: unless-stopped` + systemd unit on the host — README-deploy covers both).
Internal-only exposure by default; Serve/Funnel of the console itself is an explicit
in-app act (spec Constraints).

**D13 — Live log tail: polling, not SSE.** `GET /api/logs/{unit}?after=<id>&severity=`
returns lines + next-cursor; the Logs page polls 2–3 s while open. Single admin, light
payload; SSE rejected as an extra mechanism for marginal gain (Principle I).

**D14 — HuJSON policy handling: text is canonical.** GET returns the applied file text +
parsed structured view (generated server-side); validate = server-side parse of the draft
(errors with line numbers); diff = rule-level set comparison; apply = PUT of draft text;
rollback = stored previous applied text. Comments preserved because the file is moved as
bytes, never re-serialized.

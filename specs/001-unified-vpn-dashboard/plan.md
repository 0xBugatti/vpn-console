# Implementation Plan: Unified VPN Management Console

**Branch**: `001-unified-vpn-dashboard` | **Date**: 2026-10-10 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/001-unified-vpn-dashboard/spec.md`

## Summary

Single-admin internal web console unifying three domains: a client-side OpenVPN `.ovpn`
profile library (import/parse/organize/distribute/edit), Tailscale SaaS device
administration (inventory + lifecycle + ACL policy), and local host control (tailscaled
connect/routes, Serve/Funnel/Taildrive exposures, systemd services, logs) — plus an
attention-queue-first Overview, complete append-only audit, and settings. Technical
approach: one Docker container on the tailscaled host running a Python FastAPI thin API
that serves a hand-written vanilla-JS SPA (no Node build step), talking to three external
systems through tested adapters (Tailscale cloud REST, local tailscaled socket/CLI,
systemd/journal). Design system: `design-system/MASTER.md` (Quiet Cloud HQ, light+dark).

## Technical Context

**Language/Version**: Python 3.12 (3.13-compatible); frontend = vanilla ES2022 modules

**Primary Dependencies**: FastAPI + uvicorn; httpx (Tailscale cloud client); `cryptography`
(PEM X.509 expiry — the one heavyweight, justified by FR-010 cert parsing); `segno`
(pure-Python QR, no Pillow). Dev: pytest. Frontend: zero runtime dependencies (vendored
OFL woff2 fonts, inlined Lucide SVG sprite).

**Storage**: single SQLite file (profiles, versions, share links, audit, settings) +
plain `.ovpn` files on the volume (owner decision — Principle II)

**Testing**: pytest — unit (parser, share links, friction rules), contract (adapter
interfaces against recorded JSON fixtures via httpx.MockTransport), integration (API +
faked adapters, no live credentials — Principle VI)

**Target Platform**: single Docker container (python:3.12-slim + tailscale CLI) deployed
ON the tailscaled host with bind mounts: tailscaled socket, systemd private socket,
journal dirs; reachable on the internal network only

**Project Type**: self-hosted web service + static SPA (one container serves both)

**Performance Goals**: list rendering ≤ 250 devices / 200 profiles with immediate
interaction (SC-009); status polling 10–15 s, lists 60 s (assumption); API p95 < 200 ms
excluding external-call time

**Constraints**: no runtime internet dependency (fonts/assets vendored); no public
exposure by default; adapters MUST degrade to explicit health states (Principle VII);
audit append-only; single instance; `.ovpn` ≤ 1 MiB per file

**Scale/Scope**: 1 admin · 1 tailnet (~250 devices) · ~200 profiles · 10 pages + auth +
command palette

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | How this plan satisfies it | Status |
|---|---|---|
| I. Radical Lightness | One Python service + one static SPA; 5 runtime deps total, each justified above; no build step, no framework, no DB server | ✅ |
| II. Single-Admin Simplicity | One scrypt-hashed password gate; no accounts/RBAC; `.ovpn` plain on disk (explicit) | ✅ |
| III. Safety on Mutation | Friction tiers enforced in API contract (confirm-token / typed-confirm params) + audit on every mutation incl. undo/failure | ✅ |
| IV. One Product, One Language | One SPA shell, one sidebar, glossary binding in contract naming (`device`, `profile`, `funnel`) | ✅ |
| V. Design-Gated UI | Gate cleared (owner picked 12); MASTER.md is normative; overrides pattern defined | ✅ |
| VI. Testable Control Layer | Adapters behind interfaces (contracts/adapters.md); Tailscale cloud via injected httpx.MockTransport + recorded fixtures; local CLI/socket and systemd faked in tests | ✅ |
| VII. Fail Loud | Every adapter returns `{state, data, age}` health envelope; UI marks stale + disables mutations (FR-053, MASTER §4) | ✅ |

Post-Phase-1 re-check: no violations introduced (contracts and data model keep the
envelope, audit, and friction-tier obligations explicit). Complexity Tracking stays empty.

## Project Structure

### Documentation (this feature)

```text
specs/001-unified-vpn-dashboard/
├── plan.md              # This file
├── research.md          # Phase 0: decisions D1–D12
├── data-model.md        # Phase 1: entities, SQLite schema, state machines
├── quickstart.md        # Phase 1: runnable validation scenarios
├── contracts/
│   ├── api.md           # HTTP API contract (all endpoints)
│   └── adapters.md      # Adapter interfaces + health envelope
└── tasks.md             # Phase 2 output (/speckit-tasks) — not yet created
```

### Source Code (repository root)

```text
server/
├── app.py                # FastAPI wiring, static mount, lifespan
├── settings.py           # env/config, password hash, TS token
├── auth.py               # login/logout, session cookies, rate limit
├── db.py                 # SQLite connection, migrations, triggers
├── audit.py              # append-only audit repository
├── ovpn.py               # .ovpn parse/serialize, PEM cert expiry
├── sharelinks.py         # token links, one-time/expiry logic
├── attention.py          # derived attention items (overview queue)
├── adapters/
│   ├── base.py           # interfaces + Health envelope + state
│   ├── tscloud.py        # Tailscale cloud REST (httpx, injectable client)
│   ├── tslocal.py        # tailscaled socket (localapi) + CLI subprocess
│   └── host.py           # systemctl / journalctl / listening ports
└── api/
    ├── auth.py  overview.py  profiles.py  devices.py  acl.py
    ├── node.py  exposures.py  services.py  logs.py
    ├── audit.py  settings.py  share.py
    └── schemas.py        # pydantic response models
server/static/
├── index.html            # shell + templates per page
├── app.js                # router, state, poll loop, api client
├── styles.css            # MASTER.md tokens + components
├── fonts/                # vendored Manrope/Inter/Geist Mono woff2
└── icons.js              # inlined Lucide SVG paths
tests/
├── unit/                 # ovpn parser, share links, attention derivation
├── contract/             # adapters vs recorded fixtures (ts api, cli json, hujson)
├── integration/          # API flows with faked adapters (friction, audit, health)
└── fixtures/             # recorded tailscale JSON, sample .ovpn files, cli outputs
deploy/
├── Dockerfile            # python:3.12-slim + tailscale CLI + non-root
├── compose.yaml          # bind mounts: tailscaled socket, /run/systemd/private, journals
└── README-deploy.md      # host prep, env vars, first-run
design-system/            # MASTER.md (ratified) + overrides/
```

**Structure Decision**: single Python package serving both API and SPA (Option 1 shape,
web-flavored): no `frontend/` build tree because the SPA is hand-written static files
(Principle I). Adapters are the seam that keeps live systems out of tests (Principle VI).

## Complexity Tracking

> No constitution violations to justify.

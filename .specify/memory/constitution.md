<!-- Sync Impact Report
Version change: (none — first adoption) → 1.0.0
Modified principles: none (initial)
Added sections: Core Principles I–VII; Constraints & Security; Development Workflow; Governance
Removed sections: none
Follow-up TODOs: none — all placeholders resolved
-->

# vpn-console Constitution

## Core Principles

### I. Radical Lightness

The product MUST ship as one static SPA (no Node build step; hand-written HTML/CSS/JS
or CDN-loaded libraries only) plus one Python FastAPI thin API, packaged as a single
Docker container. A dependency, abstraction, or service MAY be added only when a
committed feature cannot ship without it (YAGNI enforced at every task).

### II. Single-Admin Simplicity

Exactly one authentication gate (admin password → session/bearer token) protects the
whole application. There MUST be no user accounts, roles, tenants, or per-user state.
`.ovpn` profile files are stored in plain form on the server disk — an explicit owner
decision recorded here so later contributors do not "fix" it silently.

### III. Safety on Mutation

Every state-changing operation (delete/disable a profile, expire/revoke a device key,
save ACL policy, service stop/restart, enable Funnel/public exposure) MUST require an
explicit user confirmation; irreversible operations MUST additionally use
type-to-confirm. Every mutation MUST be recorded in an append-only in-app audit log
(what, when, via which API call, outcome). Read-only browsing MUST NOT require
confirmation.

### IV. One Product, One Language

OpenVPN profiles, Tailscale devices, service control, and exposures are one product
with one navigation model and one terminology glossary. The UI MUST NOT present
separate "OpenVPN panel" and "Tailscale panel" identities; shared concepts (status,
expiry, identity) MUST use identical vocabulary, colors, and components everywhere.

### V. Design-Gated UI

No production UI code MAY be written before the owner selects one visual direction
from the 20 proposed mockups (same screen, 20 styles). The selected direction MUST be
formalized as a ui-ux-pro-max design system (`design-system/<project>/MASTER.md` plus
per-page overrides), and every screen MUST conform to it; deviations require a
recorded override file, not inline one-offs.

### VI. Testable Control Layer

Every external integration (Tailscale cloud REST API, local Tailscale
socket/CLI, systemd) MUST sit behind an interface/adapter. The FastAPI layer MUST be
integration-tested against recorded or mocked adapter responses; live credentials,
tokens, or a live tailscaled instance are never required to run the test suite.

### VII. Fail Loud, Degrade Gracefully

Each subsystem (Tailscale cloud API, local socket/CLI, systemd, profile store) MUST
expose an explicit health state in the UI. When a subsystem is unreachable, its
panels MUST visibly mark data as stale/unavailable; the dashboard MUST NEVER present
cached data as live and MUST surface error detail sufficient to diagnose (status
code, endpoint, hint) without opening server logs.

## Constraints & Security

- Deployment: one Docker container running ON the tailscaled host, with the
  Tailscale daemon socket mounted in; the API talks to the local socket/CLI and to
  the Tailscale cloud REST API using an owner-provided API token.
- Network exposure: the dashboard is for one admin on an internal network; it MUST
  NOT be exposed publicly by default. If the owner later exposes it via Tailscale
  Serve/Funnel, that is an explicit deployment decision, not a default.
- Secrets: the Tailscale API token and admin password hash live only in container
  environment/config on the host; they MUST NOT be committed to the repository or
  written into the profile store.
- Scope boundary: the dashboard manages client-side `.ovpn` profile files only; it
  MUST NOT attempt OpenVPN server/PKI administration.
- Single instance: no horizontal scaling, clustering, or distributed state; SQLite
  or flat files on the container volume are the storage ceiling.

## Development Workflow

- Spec-driven: features follow the spec-kit flow (constitution → specify → clarify
  → plan → tasks → implement → converge); `tasks.md` is the single source of
  implementation order.
- Research-informed: UX/IA decisions cite the research reports under
  `/root/Work/projects/research/` (comparable-dashboard UX and design-trend
  findings) rather than ad-hoc taste.
- Mockup gate: the 20-direction mockup gallery is a deliverable; the owner's pick
  is recorded in the design system MASTER.md and referenced by all UI tasks.
- Quality gates before any UI implementation: API adapters tested per Principle VI;
  destructive-op flows implemented with confirmation + audit per Principle III.

## Governance

- This constitution supersedes any conflicting practice, plan, or task.
- Amendments: propose in a task or PR description, update this file, increment the
  version (MAJOR: principle removed/redefined incompatibly; MINOR: new principle or
  material expansion; PATCH: wording/clarification), and note the change in the Sync
  Impact Report.
- Compliance: every `/speckit-plan` and `/speckit-implement` pass MUST check tasks
  against Core Principles; a task that cannot satisfy a principle MUST be flagged
  rather than silently worked around.
- Plain-storage note (Principle II) and the single-admin gate are owner decisions;
  changing either requires a MINOR amendment with the owner's explicit approval.

**Version**: 1.0.0 | **Ratified**: 2026-10-10 | **Last Amended**: 2026-10-10

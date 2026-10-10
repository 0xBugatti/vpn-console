# vpn-console

A single-admin web console that puts three things you'd otherwise manage in
three different places into one interface:

1. **Profiles** — your OpenVPN client `.ovpn` library: import with drag & drop,
   parse chips (valid / expiring / expired / parse-error), download, QR codes,
   edit-with-undo, expiring share links.
2. **Devices & ACL** — your tailnet through the Tailscale cloud API: inventory
   with token search (`is:unapproved tag:server !os:ios`), approval / key
   expiry / deletion with friction tiers, HuJSON ACL editor with
   validate → diff → apply → rollback.
3. **Host** — the machine `tailscaled` runs on: connect/disconnect, exit-node
   and subnet routes, serve/funnel/taildrive exposures with port-collision
   warnings, systemd services, journald logs.

Every mutation lands in an **append-only audit log** (undo included, nothing
can ever be edited or deleted), and every subsystem reports honest health —
when tailscaled, the Tailscale API, or systemd is unreachable you get a banner
and blocked controls, never stale data presented as live.

Built for one admin on one host. No user accounts, no RBAC, no Node build
step — a static SPA served by a Python FastAPI thin API in one container.

## Run the tests

```sh
uv sync --dev && uv run pytest          # 150+ tests, no live systems needed
# or plain pip:
pip install "fastapi>=0.115" "uvicorn>=0.30" "httpx>=0.27" \
            "cryptography>=43.0" "segno>=1.6" "python-multipart>=0.0.32" pytest
python -m pytest
```

Adapters (Tailscale cloud, local socket/CLI, systemd) are interfaced and
tested against recorded/mocked responses — tests never touch your tailnet.

## Try it in fake mode

A seeded fake scenario (expired cert, unapproved device, failed unit, public
exposure) runs the whole UI with zero live systems:

```sh
VPNCONSOLE_ADAPTERS=fake ADMIN_PASSWORD=dev uvicorn server.app:app --port 8337
# open http://localhost:8337 → sign in with `dev`
```

Walkthrough: import `tests/fixtures/ovpn/*.ovpn` · craft a connect command ·
approve/expire/delete a device through the friction ladder · edit + apply +
rollback the ACL · funnel-port constraint on Exposures · restart a service ·
tail the logs · filter and export the audit log · change the password. Full
script: [specs/001-unified-vpn-dashboard/quickstart.md](specs/001-unified-vpn-dashboard/quickstart.md).

## Deploy

One container **on the tailscaled host**, host daemons reached through
bind-mounted sockets — see [deploy/README-deploy.md](deploy/README-deploy.md)
(compose + quadlet, permissions, backup).

## Configuration (env)

| Variable | Meaning |
|---|---|
| `ADMIN_PASSWORD` (or `ADMIN_PASSWORD_FILE`) | the single gate; required |
| `TS_API_TOKEN` | Tailscale cloud API token — env wins over one stored in Settings; never logged |
| `TS_TAILNET` | tailnet name, `-` for default |
| `VPNCONSOLE_DATA` | data dir (SQLite + plain `.ovpn` store + audit log), default `./data` |
| `VPNCONSOLE_SESSION_SECRET` | pin session signing across restarts |
| `VPNCONSOLE_ADAPTERS` | `real` (default) or `fake` |
| `VPNCONSOLE_POLL_STATUS_S` / `VPNCONSOLE_POLL_LISTS_S` | UI poll intervals |

`.ovpn` files are stored **plain** — an explicit owner decision; the data dir
and its backups should be treated accordingly.

## Layout

```
server/            FastAPI app + adapters (tscloud / tslocal / host) + audit
server/static/     hand-written SPA (ES modules, no build step)
tests/             unit + contract + integration (fake adapters)
deploy/            Dockerfile, compose.yaml, deploy guide
specs/             spec-kit feature: spec, plan, research, tasks, quickstart
design-system/     MASTER.md — the design language every screen follows
```

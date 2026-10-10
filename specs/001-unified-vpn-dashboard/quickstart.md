# Quickstart — validating vpn-console

Prerequisites: Python 3.12+, `uv` (or pip), no live Tailscale/systemd needed (fake
adapters, D9/D12).

## 1. Run the test suite (proves Principles III/VI/VII behavior)

```bash
cd /root/Work/projects/vpn-console
uv run pytest -q            # or: python -m pytest -q
```

Expected: unit + contract + integration green. Key scenarios covered:
- friction tiers: mutations without `confirm`/`typed_confirm`/`lan_ack` → 409
- audit: every mutation (incl. undo + failure) appended; trigger blocks UPDATE/DELETE
- health: `break("tscloud")` → payloads carry stale `_health`, mutations → 409
- parser: valid / expiring / expired / missing-cert / >1 MiB sample `.ovpn` files
- share links: expiry, one-time, revocation → 410 with reason

## 2. Run the app in fake mode (full UI walkthrough, zero live systems)

```bash
VPNCONSOLE_ADAPTERS=fake ADMIN_PASSWORD=dev uvicorn server.app:app --port 8337
# open http://localhost:8337  → sign in with `dev`
```

Walk the spec's acceptance scenarios: Overview attention queue (fake scenario seeds an
expired cert, unapproved device, failed unit, public exposure) · import
`tests/fixtures/ovpn/*.ovpn` (drag & drop, duplicate choice) · QR modal (URL mode) ·
share link lifecycle · Devices tabs + `is:unapproved` search · approve/expire/delete
friction ladder · ACL validate→diff→apply→rollback (comments preserved) · Local Node
disconnect typed-confirm with LAN checkbox · Exposures funnel port constraint · Services
restart progress · Logs filter + live poll · Audit filters + JSON export · Settings
password change + danger zone.

## 3. Run against real systems (on the tailscaled host)

Follow `deploy/README-deploy.md`: compose with the D2 bind mounts + `TS_API_TOKEN`,
then verify `GET /api/health` shows all three subsystems `ok` and Settings → Test
connection reports the tailnet.

## Notes

- Fake mode never touches the network; fonts/icons are vendored (works air-gapped).
- Contracts: [contracts/api.md](contracts/api.md) · data: [data-model.md](data-model.md)
- UI must conform to `design-system/MASTER.md` (both themes) — checklist in MASTER §6.

# Adapter Interfaces — vpn-console

Principle VI: every external system sits behind one of these interfaces; tests inject
fakes — live credentials/sockets are never needed. Principle VII: every method returns
the health envelope; adapters raise nothing across the boundary.

## Health envelope

```python
@dataclass
class Health:
    state: str            # "ok" | "degraded" | "unavailable"
    detail: str = ""      # human hint incl. status code/endpoint where relevant
    last_ok: float = 0.0  # epoch of last successful call
    age_seconds: float = 0.0
```

Every adapter result is `Result(data: T | None, health: Health)`. Server-side caches
(D10) serve last-good data with age when state ≠ ok.

## TailscaleCloud (tscloud.py) — HTTP api.tailscale.com/api/v2 (D3)

```
tailnet() -> Tailnet{name, magic_dns}
list_devices() -> list[Device]
approve_device(id) / delete_device(id)
expire_key(id) / set_key_expiry_disabled(id, disabled: bool)   # = require_reauth toggle
set_tags(id, tags[]) / set_approved_routes(id, routes[])
get_acl_text() -> str           # raw bytes — never re-serialized (D14)
put_acl_text(text)
list_users() -> list[User]
create_auth_key(cfg) -> AuthKey # for the connect-a-device helper
test() -> Tailnet               # Settings "Test connection"
```

Transport: injected `httpx.Client` (10 s timeout). Tests: `httpx.MockTransport` +
recorded fixtures (`tests/fixtures/tailscale/*.json`). Maps 429/5xx/timeouts →
`degraded`, DNS/connection errors → `unavailable`.

## TailscaleLocal (tslocal.py) — socket HTTP + CLI JSON (D1)

```
status() -> LocalNode{state, addresses, version, online}
prefs() -> Prefs{exit_node_advertise, exit_node_using, advertised_routes}
set_prefs(...)                  # connect/disconnect, exit-node use/advertise, routes
serve_status() -> list[Exposure]
funnel_enable/disable(entry) / serve_create/remove(entry)   # confirm enforced by API layer
drive_status() -> list[Exposure]
netcheck() -> Netcheck{udp, ipv4, relay, latency}
```

Socket: HTTP/1.1 over `/var/run/tailscale/tailscaled.socket` (`/localapi/v0/…`); CLI
subprocess (`tailscale --socket=<path> serve status --json` etc.) only where localapi has
no coverage. Faked in tests with canned JSON (`fixtures/cli/*.json`).

## HostControl (host.py) — systemd/journal/ss (D2)

```
units() -> list[ServiceUnit]                 # allow-list: tailscaled, openvpn@*, vpn-console
unit_action(unit, action) -> job_id          # start|stop|restart|enable|disable
job(job_id) -> Job{done, ok, detail}
journal(unit, since, severity, q, limit) -> (lines, next_cursor)
listening_ports() -> list[PortAnnotation]    # ss -tulpen parse
```

Runs `systemctl`/`journalctl` against the mounted host socket; `network_mode: host` +
`ss`. If mounts are missing → `unavailable` with the deploy hint in `detail`.

## Fakes (tests + local dev)

`tests/fakes.py` provides `FakeCloud`, `FakeLocal`, `FakeHost` with mutable scenario
state (unapproved device, expiring keys, failing unit, public exposure) and a
`break(subsystem)` switch to exercise stale/unavailable paths (SC-010, D10). `app.py`
selects real or fake adapters via env (`VPNCONSOLE_ADAPTERS=real|fake`) — fake mode is
also the maintainer's local dev mode.

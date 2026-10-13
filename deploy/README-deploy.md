# Deploying vpn-console on the tailscaled host

One container, no daemons of its own. The console controls the host's
tailscaled, systemd, and journal over **bind-mounted sockets** (research
**D2**) and ships as compose with `network_mode: host` (**D12**). It never
runs its own tailscaled — the `tailscale` CLI inside the image talks to the
host daemon through the mounted socket.

## Host prep

1. **A Linux host running `tailscaled`** (the machine whose exposures,
   services, and logs you want to manage). Confirm the socket exists:

   ```sh
   ls -l /var/run/tailscale/tailscaled.socket   # default path
   ```

   Running it inside a Tailscale container or LXC? The socket must be the
   host's real one — mount or bind it to `/var/run/tailscale/tailscaled.socket`
   in the VM/container first.

2. **Docker Engine** (or Podman — `podman compose` reads the same file) with
   the compose plugin.

3. Nothing else. No database, no reverse proxy, no Node — the SPA is served
   by the same process.

## First run

```sh
cd deploy
cat > .env <<'EOF'
ADMIN_PASSWORD=<choose-a-long-password>
# Optional — a Tailscale API token here wins over one entered in Settings:
#TS_API_TOKEN=tskey-api-...
# Optional — pin session signing so logins survive container replacement
# (otherwise a new secret is generated per instance):
#VPNCONSOLE_SESSION_SECRET=<openssl rand -hex 32>
# Optional — uvicorn port (8090 default; host network, so no mapping needed):
#VPNCONSOLE_PORT=8090
#VPNCONSOLE_BIND=127.0.0.1   # local only (default); 0.0.0.0 = all interfaces
#VPNCONSOLE_TUNNEL_DIR=/host-openvpn-client   # where Enable installs tunnel configs (mount of /etc/openvpn/client)
EOF
chmod 600 .env
docker compose up -d --build
```

Open `http://<host>:8090` **from a machine on your tailnet** and sign in with
`ADMIN_PASSWORD`. The Overview page shows per-subsystem health immediately —
if a socket mount is missing, that subsystem shows `unavailable` instead of
pretending (Fail Loud, Principle VII).

**Keep the port tailnet-internal.** `network_mode: host` means the chosen
port binds on every host interface; firewall it to the tailnet (100.64.0.0/10
plus LAN) if the host has public interfaces. Serving the console itself over
Funnel is possible but is an explicit in-app act — don't do it by accident.

## What each mount is for

| Mount | Mode | Backs |
|---|---|---|
| `/var/run/tailscale/tailscaled.socket` | rw | Local Node page, Exposures (serve/funnel/drive), connect ops |
| `/run/systemd/private` | rw | Services page (systemctl start/stop/restart/enable) |
| `/run/dbus/system_bus_socket` | rw | systemd fallback bus for the same |
| `/var/log/journal` (+`/run/log/journal`) | ro | Logs page (journalctl; persistent + volatile stores) |
| `data` volume → `/data` | rw | SQLite DB, plain `.ovpn` files, share links, audit log |

If a host keeps its journal only in `/run/log/journal` (volatile), mount that
one; both are provided because most distros persist to `/var/log/journal`.

## Permissions

The image runs as user `console` (uid 1000). Host sockets decide how far that
gets you:

- **Journal reads** need membership in the host's `systemd-journal` group.
  Find its GID on the host (`getent group systemd-journal`) and add to the
  compose service:

  ```yaml
      group_add:
        - "102"   # host systemd-journal GID
  ```

- **tailscaled / systemd sockets** are root-restricted on some distros. If a
  subsystem reports `unavailable` with a permission error and you accept the
  trade-off, run the container as root:

  ```yaml
      user: "0:0"
  ```

  This widens the blast radius (research D2 rejected it as the default) — try
  `group_add` first. `docker compose exec console id` and a peek at
  `ls -l /var/run/tailscale/` on the host tell you which case you're in.

- **systemd peer policy (root alone isn't enough on modern systemd ≥ 253)**:
  PID 1 admits `systemctl` clients by cgroup membership, so a container with
  its own cgroup namespace gets `Failed to connect to system scope bus …
  No data available` even as root with `/run/systemd/private` mounted. The
  fix is in compose.yaml already:

  ```yaml
      pid: "host"
      cgroup: host
  ```

  `pid: host` has a second benefit: the Exposures listening-ports card gets
  real process names from `ss -tulpen` instead of container-namespace ones.
  `journalctl` additionally needs `/run/systemd/system` (sd_booted check) and
  the host's `/etc/machine-id` to find the right journal store — both are
  mounted in compose.yaml.

- **Modern Tailscale socket path**: newer tailscaled units place the localapi
  socket at `/run/tailscale/tailscaled.socket` (not the classic
  `/var/run/tailscale/tailscaled.socket`). Check yours with
  `ls /run/tailscale/ /var/run/tailscale/` and set `TAILSCALE_SOCKET` in
  `deploy/.env` if it differs from the default compose expects.

## The console's own unit: quadlet alternative

compose's `restart: unless-stopped` is enough on Docker hosts. If you manage
the host with systemd and run **Podman ≥ 4.4**, a quadlet makes the console a
first-class `vpn-console.service` unit instead:

```sh
# Build once (or reuse the compose-built image):
podman build -f deploy/Dockerfile -t vpn-console:latest .

# /etc/containers/systemd/vpn-console.container
cat > /etc/containers/systemd/vpn-console.container <<'EOF'
[Unit]
Description=VPN console (OpenVPN profiles + Tailscale admin + host control)
After=network-online.target tailscaled.service
Wants=network-online.target

[Container]
Image=localhost/vpn-console:latest
ContainerName=vpn-console
Network=host
EnvironmentFile=/etc/vpn-console/env
Volume=/var/run/tailscale/tailscaled.socket:/var/run/tailscale/tailscaled.socket
Volume=/run/systemd/private:/run/systemd/private
Volume=/run/dbus/system_bus_socket:/run/dbus/system_bus_socket
Volume=/var/log/journal:/var/log/journal:ro
Volume=/run/log/journal:/run/log/journal:ro
Volume=vpn-console-data:/data
Exec=uvicorn server.app:app --host 127.0.0.1 --port 8090

[Service]
Restart=unless-stopped

[Install]
WantedBy=multi-user.target
EOF

install -D -m 600 /dev/null /etc/vpn-console/env   # then add ADMIN_PASSWORD=...
systemctl daemon-reload
systemctl enable --now vpn-console.service
```

`EnvironmentFile` lines are `KEY=value` — same variables as `deploy/.env`.
Logs land in the host journal, so the console's own unit appears on its own
Logs page.

## Upgrades & backup

```sh
git pull && docker compose up -d --build     # data volume survives
docker run --rm -v vpn-console_data:/data -v "$PWD:/b" alpine \
  tar czf /b/vpn-console-data.tgz -C /data .  # DB + .ovpn files + audit log
```

`.ovpn` files are stored **plain** by explicit owner decision — treat the
data volume backup like the real secrets it contains.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Local Node / Exposures banner: `unavailable` | tailscaled socket mount missing or permission-denied — see Permissions |
| Services page: `unavailable` with `No data available` | systemd peer policy — `pid: "host"` + `cgroup: host` missing (see Permissions) |
| Services page: `unavailable` | `/run/systemd/private` not mounted (or root-only socket → Permissions) |
| Logs page empty: `journal unavailable` | journal dirs not mounted, or journal GID not granted |
| Devices/ACL banner: `degraded`/`down` | Tailscale cloud API unreachable or token invalid — Settings → Test connection |
| Port already in use | another service owns 8090 — set `VPNCONSOLE_PORT` in `.env` |

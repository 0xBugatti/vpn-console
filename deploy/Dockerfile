# vpn-console image — one container on the tailscaled host (research D2/D12).
#
# Build from the REPO ROOT so the server package is in context:
#   docker build -f deploy/Dockerfile -t vpn-console .
#
# The container never runs tailscaled, journald, or systemd itself — it talks
# to the host's daemons over bind-mounted sockets (deploy/compose.yaml).
FROM python:3.12-slim

# tailscale CLI      — local node control; talks to the HOST tailscaled over
#                      the mounted socket (--socket is injected per call).
# systemd            — provides systemctl + journalctl for unit control/logs.
# iproute2           — `ss -tulpen` backs the listening-ports card.
# ca-certificates    — TLS to the Tailscale cloud API.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl gnupg iproute2 systemd \
 && CODENAME=$(. /etc/os-release && echo "$VERSION_CODENAME") \
 && curl -fsSL "https://pkgs.tailscale.com/stable/debian/${CODENAME}.noarmor.gpg" \
      -o /usr/share/keyrings/tailscale-archive-keyring.gpg \
 && echo "deb [signed-by=/usr/share/keyrings/tailscale-archive-keyring.gpg] https://pkgs.tailscale.com/stable/debian ${CODENAME} main" \
      > /etc/apt/sources.list.d/tailscale.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends tailscale \
 && apt-get purge -y curl gnupg \
 && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

# Runtime deps straight from pyproject.toml (no build step, no packaging
# metadata needed — Radical Lightness).
RUN pip install --no-cache-dir \
      "fastapi>=0.115" "uvicorn>=0.30" "httpx>=0.27" \
      "cryptography>=43.0" "segno>=1.6" "python-multipart>=0.0.32"

# Non-root. Socket permissions on the host decide how much this buys you —
# see "Permissions" in deploy/README-deploy.md for the journal-group knob.
RUN useradd --uid 1000 --user-group --create-home console \
 && mkdir -p /data \
 && chown console:console /data
USER console
WORKDIR /app
COPY --chown=console:console server/ ./server/

ENV VPNCONSOLE_DATA=/data \
    PYTHONUNBUFFERED=1
EXPOSE 8090

# Liveness probe: the SPA shell is served without auth (unlike /api/*).
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"VPNCONSOLE_PORT\", \"8090\")}/', timeout=4)"

CMD ["uvicorn", "server.app:app", "--host", "127.0.0.1", "--port", "8090"]

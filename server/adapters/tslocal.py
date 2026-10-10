"""Local tailscaled control: HTTP over the Unix socket + CLI JSON (research D1).

Socket localapi covers status/prefs; `tailscale set` / `serve` / `drive` CLI
subprocesses (with explicit --socket) cover the gaps. Raises internally; the
API layer's SubsystemCache converts failures to Health states.
"""
from __future__ import annotations

import json
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Any

SOCKET_CANDIDATES = [
    "/var/run/tailscale/tailscaled.socket",
    "/run/tailscale/tailscaled.socket",
]


def find_socket() -> str | None:
    for candidate in SOCKET_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return None


class TailscaleLocal:
    def __init__(self, socket_path: str | None = None, cli: str | None = None) -> None:
        self.socket_path = socket_path or find_socket()
        self.cli = cli or shutil.which("tailscale") or "tailscale"

    # --- transport ---------------------------------------------------------

    def _socket_http(self, method: str, path: str, body: dict | None = None) -> dict:
        """Minimal HTTP/1.1 over the tailscaled unix socket (no httpx UDS dep)."""
        if not self.socket_path:
            raise FileNotFoundError("tailscaled socket not found")
        payload = b""
        # Host MUST be local-tailscaled.sock: modern tailscaled gates localapi
        # on this dial-name and answers anything else 403 Forbidden.
        headers = [f"{method} {path} HTTP/1.1",
                   "Host: local-tailscaled.sock", "Connection: close"]
        if body is not None:
            payload = json.dumps(body).encode()
            headers += ["Content-Type: application/json", f"Content-Length: {len(payload)}"]
        raw = "\r\n".join(headers).encode() + b"\r\n\r\n" + payload

        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(10.0)
            s.connect(self.socket_path)
            s.sendall(raw)
            chunks: list[bytes] = []
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
        response = b"".join(chunks)
        head, _, rest = response.partition(b"\r\n\r\n")
        status_line = head.split(b"\r\n")[0].decode(errors="replace")
        if " 200 " not in status_line + " ":
            raise ConnectionError(f"localapi {path}: {status_line}")
        # handle chunked minimally: try json parse, else dechunk
        text = rest
        try:
            return json.loads(text) if text else {}
        except ValueError:
            return self._dechunk(text)

    @staticmethod
    def _dechunk(data: bytes) -> dict:
        out = b""
        while data:
            line, _, data = data.partition(b"\r\n")
            try:
                size = int(line, 16)
            except ValueError:
                break
            if size == 0:
                break
            out += data[:size]
            data = data[size + 2:]
        return json.loads(out) if out else {}

    def _cli(self, *args: str, check: bool = True) -> str:
        cmd = [self.cli, f"--socket={self.socket_path}" if self.socket_path else "", *args]
        cmd = [c for c in cmd if c]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)  # noqa: S603
        if check and proc.returncode != 0:
            raise RuntimeError(f"tailscale {' '.join(args)}: {proc.stderr.strip()[:300]}")
        return proc.stdout

    def _cli_json(self, *args: str) -> dict:
        out = self._cli(*args)
        return json.loads(out) if out.strip() else {}

    # --- reads ---------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        return self._socket_http("GET", "/localapi/v0/status")

    def prefs(self) -> dict[str, Any]:
        return self._socket_http("GET", "/localapi/v0/prefs")

    def serve_status(self) -> dict[str, Any]:
        return self._cli_json("serve", "status", "--json")

    def drive_status(self) -> dict[str, Any]:
        try:
            return self._cli_json("drive", "status", "--json")
        except RuntimeError:
            return {}  # Taildrive may not be compiled in — explicit empty, not a lie

    # --- mutations (friction enforced at API layer) ---------------------------

    def connect(self) -> None:
        self._cli("up")

    def disconnect(self) -> None:
        self._cli("down")

    def set_exit_node(self, use: str | None, advertise_exit: bool | None = None) -> None:
        args = ["set"]
        if use is not None:  # empty string clears exit-node selection
            args.append(f"--exit-node={use}")
        if advertise_exit is not None:
            args.append(f"--advertise-exit-node={'true' if advertise_exit else 'false'}")
        self._cli(*args)

    def set_advertised_routes(self, routes: list[str]) -> None:
        self._cli("set", f"--advertise-routes={','.join(routes)}")

    def serve_add(self, port: int, target: str, scheme: str = "https",
                  funnel: bool = False) -> None:
        cmd = "funnel" if funnel else "serve"
        self._cli(cmd, "--bg", f"--{scheme}={port}", target)

    def serve_off(self, port: int, scheme: str = "https", funnel: bool = False) -> None:
        cmd = "funnel" if funnel else "serve"
        self._cli(cmd, "--bg", f"--{scheme}={port}", "off")

    def drive_remove(self, path: str) -> None:
        self._cli("drive", "share", "remove", path)

    def drive_shares(self) -> list[dict[str, Any]]:
        data = self.drive_status()
        return [
            {"path": path, **(info or {})}
            for path, info in (data.get("Config", {}).get("Shares") or {}).items()
        ]

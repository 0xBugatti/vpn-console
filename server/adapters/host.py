"""Host control: systemctl / journalctl / ss via bind-mounted host paths (D2).

Runs inside the console container against the mounted host systemd socket and
journal dirs. Missing mounts → FileNotFoundError, which the API layer surfaces
as an explicit `unavailable` health state — never silent emptiness (FR-053).
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

ALLOWED_UNITS = ("tailscaled.service", "openvpn.service", "openvpn@*.service",
                 "openvpn-client@*.service", "vpn-console.service")

SYSTEMD_SOCKET = "/run/systemd/private"
JOURNAL_DIRS = ["/var/log/journal", "/run/log/journal"]


def _mount_ok() -> bool:
    if not Path(SYSTEMD_SOCKET).exists():
        return False
    return any(Path(d).exists() for d in JOURNAL_DIRS)


def unit_allowed(unit: str) -> bool:
    for pattern in ALLOWED_UNITS:
        if "*" in pattern:
            if unit.startswith(pattern.split("*")[0]):
                return True
        elif unit == pattern:
            return True
    return False


class HostControl:
    def __init__(self, systemctl: str | None = None, journalctl: str | None = None,
                 ss: str | None = None) -> None:
        self.systemctl = systemctl or shutil.which("systemctl") or "systemctl"
        self.journalctl = journalctl or shutil.which("journalctl") or "journalctl"
        self.ss = ss or shutil.which("ss") or "ss"

    def _run(self, cmd: list[str], timeout: int = 30) -> str:
        if not _mount_ok():
            raise FileNotFoundError(
                "systemd socket/journal not mounted — see deploy/README-deploy.md"
            )
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)  # noqa: S603
        if proc.returncode != 0:
            raise RuntimeError(f"{' '.join(cmd[:2])}: {proc.stderr.strip()[:300]}")
        return proc.stdout

    # --- units ---------------------------------------------------------------

    def unit_state(self, unit: str) -> dict[str, Any]:
        out = self._run(
            [self.systemctl, "--no-pager", "show", unit,
             "--property=Id,Description,ActiveState,SubState,UnitFileState,"
             "ExecMainStartTimestamp,Result"]
        )
        props = {}
        for line in out.splitlines():
            key, _, value = line.partition("=")
            if key:
                props[key] = value
        return {
            "unit": props.get("Id", unit),
            "description": props.get("Description", ""),
            "state": props.get("ActiveState", "unknown"),
            "sub_state": props.get("SubState", ""),
            "enabled_on_boot": props.get("UnitFileState", "") == "enabled",
            "since": props.get("ExecMainStartTimestamp", ""),
            "result": props.get("Result", ""),
        }

    def units(self) -> list[dict[str, Any]]:
        found: list[dict[str, Any]] = []
        list_out = self._run([self.systemctl, "--no-pager", "list-units", "--all",
                              "--plain", "--no-legend", "tailscaled.service",
                              "openvpn.service", "openvpn@*.service",
                              "openvpn-client@*.service", "vpn-console.service"])
        known = {line.split()[0] for line in list_out.splitlines() if line.strip()}
        for unit in sorted(known) or ["tailscaled.service"]:
            found.append(self.unit_state(unit))
        return found

    def unit_action(self, unit: str, action: str) -> str:
        if action not in ("start", "stop", "restart", "enable", "disable"):
            raise ValueError(f"unsupported action {action}")
        if not unit_allowed(unit):
            raise PermissionError(f"unit {unit} is not managed by the console")
        self._run([self.systemctl, action, unit], timeout=60)
        return f"{action}:{unit}"

    # --- journal ---------------------------------------------------------------

    def journal(self, unit: str, since: str = "", severity: int | None = None,
                text: str = "", limit: int = 200, after_cursor: str = "") -> list[dict[str, Any]]:
        cmd = [self.journalctl, "-o", "json", "-u", unit, "--no-pager",
               f"--lines={min(limit, 500)}"]
        if since:
            cmd.append(f"--since={since}")
        if after_cursor:
            cmd.append(f"--after-cursor={after_cursor}")
        if severity is not None:
            cmd.append(f"--priority=0..{severity}")  # err+ = emerg..err (0–3)
        lines_out = self._run(cmd)
        entries = []
        for line in lines_out.splitlines():
            if not line.strip():
                continue
            try:
                import json
                entry = json.loads(line)
            except ValueError:
                continue
            msg = entry.get("MESSAGE", "")
            if text and text.lower() not in msg.lower():
                continue
            entries.append({
                "ts": entry.get("__REALTIME_TIMESTAMP", ""),
                "prio": int(entry.get("PRIORITY", 6)),
                "msg": msg,
                "cursor": entry.get("__CURSOR", ""),
            })
        return entries

    # --- listening ports ---------------------------------------------------------

    def listening_ports(self) -> list[dict[str, Any]]:
        out = self._run([self.ss, "-tulpen"])
        ports: list[dict[str, Any]] = []
        seen: set[tuple[str, int]] = set()
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) < 5:
                continue
            proto, state, local = parts[0], parts[1], parts[4]
            m = re.search(r":(\d+)$", local)
            if not m:
                continue
            port = int(m.group(1))
            pm = re.search(r'users:\(\("([^"]+)"', line)
            process = pm.group(1) if pm else ""
            key = (proto, port)
            if key in seen:
                continue
            seen.add(key)
            ports.append({
                "proto": proto,
                "local_addr": local,
                "port": port,
                "process": process,
                "annotation": "unexposed",  # joined with exposures at the API layer
            })
        return ports

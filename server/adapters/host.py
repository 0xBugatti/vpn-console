"""Host control: systemctl / journalctl / ss via bind-mounted host paths (D2).

Runs inside the console container against the mounted host systemd socket and
journal dirs. Missing mounts → FileNotFoundError, which the API layer surfaces
as an explicit `unavailable` health state — never silent emptiness (FR-053).
"""
from __future__ import annotations

import fcntl
import os
import re
import shutil
import socket
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .. import tunnels
from ..settings import CONFIG

ALLOWED_UNITS = ("tailscaled.service", "openvpn.service", "openvpn@*.service",
                 "openvpn-client@*.service", "vpn-console.service")

NET_CLASS_DIR = Path("/sys/class/net")
_TUNNEL_PREFIXES = ("tun", "tap", "wg", tunnels.IFACE_PREFIX)
_INSTANCE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,39}")

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

    def unit_action(self, unit: str, action: str, now: bool = False) -> str:
        if action not in ("start", "stop", "restart", "enable", "disable"):
            raise ValueError(f"unsupported action {action}")
        if not unit_allowed(unit):
            raise PermissionError(f"unit {unit} is not managed by the console")
        flags = ["--now"] if now and action in ("enable", "disable") else []
        self._run([self.systemctl, action, *flags, unit], timeout=60)
        return f"{action}:{unit}"

    def unit_queue(self, unit: str, action: str = "start") -> None:
        """Queue a start or restart and return at once. A Type=notify tunnel only becomes
        active when the VPN is really up (up to ~90 s), so the caller polls unit_state."""
        if action not in ("start", "restart"):
            raise ValueError(f"unsupported action {action}")
        if not unit_allowed(unit):
            raise PermissionError(f"unit {unit} is not managed by the console")
        self._run([self.systemctl, action, "--no-block", unit], timeout=20)

    # --- tunnel configs: the host's /etc/openvpn/client, mounted read-write ---------------

    @staticmethod
    def _tunnel_dir() -> Path | None:
        return Path(CONFIG.tunnel_dir) if CONFIG.tunnel_dir else None

    def tunnel_available(self) -> bool:
        folder = self._tunnel_dir()
        return bool(folder and folder.is_dir() and os.access(folder, os.W_OK))

    def _conf_path(self, instance: str) -> Path:
        folder = self._tunnel_dir()
        if folder is None:
            raise FileNotFoundError("the tunnel folder is not mounted (VPNCONSOLE_TUNNEL_DIR)")
        if not _INSTANCE_RE.fullmatch(instance):
            raise ValueError("unsafe tunnel name")
        return folder / f"{instance}.conf"

    def tunnel_conf_owner(self, instance: str) -> str | None:
        """None = no config yet; "" = a config the console did not write; otherwise the id
        of the profile whose installed copy it is."""
        path = self._conf_path(instance)
        if path.is_symlink():
            return ""
        if not path.exists():
            return None
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                return tunnels.owner_of(fh.readline()) or ""
        except OSError:
            return ""

    def tunnel_read(self, instance: str) -> str | None:
        path = self._conf_path(instance)
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None

    def tunnel_write(self, instance: str, text: str) -> None:
        """Atomically write an installed copy (root only, 0600)."""
        path = self._conf_path(instance)
        if path.is_symlink():
            raise PermissionError(f"{path.name} is a symlink; refusing to write through it")
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".vpnconsole-", suffix=".tmp")
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def routes(self) -> list[dict[str, str]]:
        """Main-table routes. The container shares the host's network namespace, so
        /proc/net is the host's."""
        found = tunnels.parse_proc_net_route(Path("/proc/net/route").read_text())
        try:
            found += tunnels.parse_proc_net_ipv6_route(Path("/proc/net/ipv6_route").read_text())
        except OSError:
            pass
        return [r.as_dict() for r in found]

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

    # --- tunnel interfaces -------------------------------------------------------

    def interfaces(self) -> list[dict[str, Any]]:
        """IPv4s of live tunnel interfaces (tun*/tap*/wg*) — the OpenVPN
        client's `ifconfig` address. The container is network_mode: host, so
        the kernel view here IS the host's. Needs no systemd mounts."""
        out: list[dict[str, Any]] = []
        try:
            names = sorted(p.name for p in NET_CLASS_DIR.iterdir())
        except OSError:
            return out
        for name in names:
            if not name.startswith(_TUNNEL_PREFIXES):
                continue
            addr = _interface_ipv4(name)
            if addr:
                out.append({"iface": name, "addr": addr})
        return out


def _interface_ipv4(ifname: str) -> str:
    """IPv4 of a live interface via SIOCGIFADDR — no subprocess, no netlink."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            packed = fcntl.ioctl(
                s.fileno(), 0x8915, struct.pack("256s", ifname[:15].encode())
            )
        except OSError:
            return ""
    return socket.inet_ntoa(packed[20:24])

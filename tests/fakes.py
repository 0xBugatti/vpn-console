"""Fake adapters for tests and local dev (research D9, contracts/adapters.md).

Same surface as the real adapters, backed by mutable scenario state. A
`break(subsystem)` switch simulates outages so stale/unavailable paths are
exercisable without live systems (SC-010).
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).parent / "fixtures"


def _load(rel: str) -> Any:
    return json.loads((FIXTURES / rel).read_text())


class FakeCloud:
    """Scenario: 6 devices from devices.json + dynamic expiry helpers."""

    def __init__(self) -> None:
        self.reset()

    # -- test controls ------------------------------------------------------
    def reset(self) -> None:
        """Restore pristine scenario state (adapters are process singletons)."""
        self.devices: list[dict[str, Any]] = _load("tailscale/devices.json")["devices"]
        self.users: list[dict[str, Any]] = _load("tailscale/users.json")["users"]
        self.acl_text: str = (FIXTURES / "tailscale/acl.hujson").read_text()
        self.created_keys: list[dict[str, Any]] = []
        self._broken = False
        self.fail_next = False

    def break_(self) -> None:
        self._broken = True

    def repair(self) -> None:
        self._broken = False

    def _check(self) -> None:
        if self.fail_next:
            self.fail_next = False
            raise ConnectionError("forced failure (fake)")
        if self._broken:
            raise ConnectionError("fake cloud unreachable")

    # -- reads ----------------------------------------------------------------
    def dns_preferences(self) -> dict[str, Any]:
        self._check()
        return {"magicDNS": True}

    def list_devices(self) -> list[dict[str, Any]]:
        self._check()
        return self.devices

    def list_users(self) -> list[dict[str, Any]]:
        self._check()
        return self.users

    def get_acl_text(self) -> str:
        self._check()
        return self.acl_text

    # -- mutations ----------------------------------------------------------------
    def approve_device(self, device_id: str) -> None:
        self._check()
        self._get(device_id)["authorized"] = True

    def delete_device(self, device_id: str) -> None:
        self._check()
        self.devices = [d for d in self.devices if d["id"] != device_id]

    def expire_key(self, device_id: str) -> None:
        self._check()
        self._get(device_id)["keyExpiry"] = "1970-01-01T00:00:00Z"

    def set_key_expiry_disabled(self, device_id: str, disabled: bool) -> None:
        self._check()
        device = self._get(device_id)
        device["expiryDisabled"] = disabled
        if disabled:
            device["keyExpiry"] = "0001-01-01T00:00:00Z"
        else:
            device["keyExpiry"] = (
                dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=180)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")

    def set_tags(self, device_id: str, tags: list[str]) -> None:
        self._check()
        self._get(device_id)["tags"] = tags

    def set_approved_routes(self, device_id: str, routes: list[str]) -> None:
        self._check()
        self._get(device_id)["approvedRoutes"] = routes

    def put_acl_text(self, text: str) -> None:
        self._check()
        self.acl_text = text

    def create_auth_key(self, reusable: bool = False, expiry_seconds: int = 600,
                        ephemeral: bool = False, tags: list[str] | None = None) -> str:
        self._check()
        self.created_keys.append({"reusable": reusable, "tags": tags})
        return f"tskey-auth-abc123DEF456gHIj{'k' * 20}"

    def _get(self, device_id: str) -> dict[str, Any]:
        for device in self.devices:
            if device["id"] == device_id:
                return device
        raise KeyError(device_id)


class FakeLocal:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._broken = False
        self.running = True
        self.advertise_exit = False
        self.using_exit = ""
        self.advertised_routes: list[str] = ["10.20.0.0/16"]
        self.serve_config: dict[str, Any] = _load("cli/serve-status.json")["Config"]
        self.drive_shares_data: dict[str, Any] = _load("cli/drive-status.json")["Config"]["Shares"]

    def break_(self) -> None:
        self._broken = True

    def repair(self) -> None:
        self._broken = False

    def _check(self) -> None:
        if self._broken:
            raise FileNotFoundError("tailscaled socket not reachable (fake)")

    def status(self) -> dict[str, Any]:
        self._check()
        return {
            "BackendState": "Running" if self.running else "Stopped",
            "Version": "1.86.1-tc88f2a10d",
            "TailscaleIPs": ["100.84.12.1", "fd7a:115c:a1e0::1"],
            "MagicDNSSuffix": "fangorn.example.com",
            "Self": {"Online": self.running, "HostName": "build-server"},
        }

    def prefs(self) -> dict[str, Any]:
        self._check()
        return {
            "RouteAll": bool(self.advertised_routes),
            "AdvertiseRoutes": self.advertised_routes,
            "AdvertiseTags": [],
            "ExitNodeIP": self.using_exit or "",
            "ExitNodeID": self.using_exit or "",
            "AllowExitNodeLANAccess": False,
        }

    def serve_status(self) -> dict[str, Any]:
        self._check()
        return {"Version": "3", "Config": self.serve_config}

    def drive_status(self) -> dict[str, Any]:
        self._check()
        return {"Version": "1", "Config": {"Shares": self.drive_shares_data}}

    def connect(self) -> None:
        self._check()
        self.running = True

    def disconnect(self) -> None:
        self._check()
        self.running = False

    def set_exit_node(self, use: str | None, advertise_exit: bool | None = None) -> None:
        self._check()
        if use is not None:
            self.using_exit = use
        if advertise_exit is not None:
            self.advertise_exit = advertise_exit
            if advertise_exit and "0.0.0.0/0" not in self.advertised_routes:
                self.advertised_routes.append("0.0.0.0/0")  # CLI adds the route
            if not advertise_exit and "0.0.0.0/0" in self.advertised_routes:
                self.advertised_routes.remove("0.0.0.0/0")

    def set_advertised_routes(self, routes: list[str]) -> None:
        self._check()
        self.advertised_routes = routes

    # --- exposures (US10) -----------------------------------------------------

    @property
    def dns_name(self) -> str:
        for tcp in self.serve_config.get("TCP", {}).values():
            host = (tcp.get("ServeURL") or "").split("//")[-1]
            if host:
                return host.split(":")[0]
        return "build.fangorn.example.com"

    def serve_add(self, port: int, target: str, scheme: str = "https",
                  funnel: bool = False) -> None:
        self._check()
        cfg = self.serve_config
        key = str(port)
        url = f"{scheme}://{self.dns_name}" + (f":{port}" if scheme == "http" else "")
        cfg["TCP"][key] = {"MustAcceptTLS": scheme == "https", "ServeURL": url}
        cfg.setdefault("Web", {})[f"{self.dns_name}:{key}"] = {
            "Handlers": {"/": {"Proxy": target}}
        }
        allow = cfg.setdefault("AllowFunnel", {})
        if funnel:
            allow[f"{self.dns_name}:{key}"] = True
        else:
            allow.pop(f"{self.dns_name}:{key}", None)

    def serve_off(self, port: int, scheme: str = "https", funnel: bool = False) -> None:
        self._check()
        cfg = self.serve_config
        key = str(port)
        cfg.get("TCP", {}).pop(key, None)
        cfg.get("Web", {}).pop(f"{self.dns_name}:{key}", None)
        if funnel:
            cfg.get("AllowFunnel", {}).pop(f"{self.dns_name}:{key}", None)

    def drive_add(self, name: str, path: str) -> None:
        self._check()
        self.drive_shares_data[path] = {"access": "readonly", "share_name": name}

    def drive_remove(self, path: str) -> None:
        self._check()
        self.drive_shares_data.pop(path, None)


class FakeHost:
    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self._broken = False
        self.interfaces_data: list[dict[str, Any]] = [
            {"iface": "tun0", "addr": "10.233.2.74"},
        ]
        self.units_data: dict[str, dict[str, Any]] = {
            "tailscaled.service": {
                "unit": "tailscaled.service",
                "description": "Tailscale node agent",
                "state": "running", "sub_state": "running",
                "enabled_on_boot": True,
                "since": "Mon 2026-09-28 04:12:33 UTC", "result": "success",
            },
            "openvpn.service": {
                "unit": "openvpn.service",
                "description": "OpenVPN service",
                "state": "inactive", "sub_state": "dead",
                "enabled_on_boot": True,
                "since": "Sun 2026-10-05 22:01:09 UTC", "result": "success",
            },
            "openvpn@corp.service": {
                "unit": "openvpn@corp.service",
                "description": "OpenVPN connection to corp",
                "state": "failed", "sub_state": "exit",
                "enabled_on_boot": False,
                "since": "Sun 2026-10-05 22:01:09 UTC", "result": "exit-code",
            },
            "vpn-console.service": {
                "unit": "vpn-console.service",
                "description": "Unified VPN Management Console",
                "state": "running", "sub_state": "running",
                "enabled_on_boot": True,
                "since": "Wed 2026-10-08 11:44:10 UTC", "result": "success",
            },
        }
        self.port_entries: list[dict[str, Any]] = [
            {"proto": "udp", "local_addr": "0.0.0.0:41641", "port": 41641, "process": "tailscaled", "annotation": "unexposed"},
            {"proto": "tcp", "local_addr": "0.0.0.0:22", "port": 22, "process": "sshd", "annotation": "unexposed"},
            {"proto": "tcp", "local_addr": "127.0.0.1:3000", "port": 3000, "process": "grafana", "annotation": "unexposed"},
            {"proto": "tcp", "local_addr": "*:443", "port": 443, "process": "tailscaled", "annotation": "unexposed"},
        ]
        self.journal_entries: list[dict[str, Any]] = [
            {"ts": "1760082723000000", "prio": 6, "msg": "Starting Tailscale node agent...", "cursor": "c1"},
            {"ts": "1760082731000000", "prio": 3, "msg": 'health("check UDP"): dial udp failed: timeout', "cursor": "c2"},
            {"ts": "1760082740000000", "prio": 4, "msg": "control: retry in 30s", "cursor": "c3"},
            {"ts": "1760082750000000", "prio": 6, "msg": "Routine: startup complete", "cursor": "c4"},
        ]
        self.action_log: list[tuple[str, str]] = []

    def break_(self) -> None:
        self._broken = True

    def repair(self) -> None:
        self._broken = False

    def _check(self) -> None:
        if self._broken:
            raise FileNotFoundError("systemd socket/journal not mounted (fake)")

    def units(self) -> list[dict[str, Any]]:
        self._check()
        return [dict(v) for v in self.units_data.values()]

    def unit_state(self, unit: str) -> dict[str, Any]:
        self._check()
        return dict(self.units_data[unit])

    def unit_action(self, unit: str, action: str) -> str:
        """Synchronous, like the real systemctl call (job tracking is the API layer's)."""
        self._check()
        if unit not in self.units_data:
            raise PermissionError(f"unit {unit} is not managed by the console")
        self.action_log.append((unit, action))
        unit_data = self.units_data[unit]
        if action == "stop":
            unit_data["state"] = "inactive"
        elif action == "start":
            unit_data["state"] = "running"
        elif action == "restart":
            unit_data["state"] = "running"
            unit_data["since"] = "just now"
        elif action == "enable":
            unit_data["enabled_on_boot"] = True
        elif action == "disable":
            unit_data["enabled_on_boot"] = False
        return f"{action}:{unit}"

    def journal(self, unit: str, since: str = "", severity: int | None = None,
                text: str = "", limit: int = 200, after_cursor: str = "") -> list[dict[str, Any]]:
        self._check()
        entries = self.journal_entries
        if after_cursor:
            idx = next((i for i, e in enumerate(entries) if e["cursor"] == after_cursor), -1)
            entries = entries[idx + 1:]
        out = []
        for entry in entries:
            if severity is not None and entry["prio"] > severity:
                continue
            if text and text.lower() not in entry["msg"].lower():
                continue
            out.append(dict(entry))
        return out[-limit:]

    def listening_ports(self) -> list[dict[str, Any]]:
        self._check()
        return [dict(p) for p in self.port_entries]

    def interfaces(self) -> list[dict[str, Any]]:
        self._check()
        return [dict(i) for i in self.interfaces_data]

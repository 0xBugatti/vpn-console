"""Device view model (data-model.md): Tailscale API device -> dashboard row.

Pure functions. `is_server` = carries tag:server. Key expiry renders "never"
when rekeying is disabled; expiry states feed is: flags and the attention queue.
Version staleness compares against the fleet max (offline-friendly, no lookup).
"""
from __future__ import annotations

import datetime as dt

SERVER_TAG = "tag:server"
EXPIRING_WINDOW = dt.timedelta(days=14)
STALE_MINOR_VERSIONS = 2  # contract: >= 2 minors behind tailnet max = stale


def _parse_ver(version: str) -> tuple[int, int, int] | None:
    try:
        major, minor, patch = (int(p) for p in version.split(".")[:3])
        return major, minor, patch
    except (ValueError, AttributeError):
        return None


def version_stale(version: str, fleet_max: str) -> bool:
    """True when this device trails the newest fleet version by >= 2 minors."""
    mine = _parse_ver(version or "")
    top = _parse_ver(fleet_max or "")
    if not mine or not top:
        return False
    return (top[0] * 1000 + top[1]) - (mine[0] * 1000 + mine[1]) >= STALE_MINOR_VERSIONS


def key_expiry_state(key_expiry: str, expiry_disabled: bool,
                     now: dt.datetime | None = None) -> str:
    """'never' | 'expired' | 'expiring' | 'valid' (FR-024 wording)."""
    if expiry_disabled or not key_expiry or key_expiry.startswith("0001-01-01"):
        return "never"
    expiry = dt.datetime.fromisoformat(key_expiry.replace("Z", "+00:00"))
    now = now or dt.datetime.now(dt.timezone.utc)
    if expiry <= now:
        return "expired"
    if expiry - now <= EXPIRING_WINDOW:
        return "expiring"
    return "valid"


def _is_exit(routes: list[str]) -> bool:
    return "0.0.0.0/0" in routes or "::/0" in routes


def device_view(device: dict, fleet_max_version: str,
                now: dt.datetime | None = None) -> dict:
    """One Tailscale device -> the row the UI renders (contracts/api.md)."""
    tags = list(device.get("tags") or [])
    approved = list(device.get("approvedRoutes") or [])
    advertised = list(device.get("advertisedRoutes") or [])
    expiry_state = key_expiry_state(
        device.get("keyExpiry") or "", bool(device.get("expiryDisabled")), now
    )
    # Live API: connectedToControl (needs ?fields=all); "online" kept for old recordings
    online = bool(device.get("connectedToControl", device.get("online")))
    subnet_routes = [r for r in approved if r not in ("0.0.0.0/0", "::/0")]
    is_server = SERVER_TAG in tags or not (device.get("user") or "")  # data-model rule
    return {
        "id": str(device.get("id", "")),
        "name": (device.get("dnsName") or device.get("name") or "").rstrip("."),
        "hostname": device.get("hostname") or "",
        "os": (device.get("os") or "").lower(),
        "os_label": device.get("os") or "unknown",
        "version": _version(device),
        "client_version": device.get("clientVersion") or "",
        "version_stale": version_stale(_version(device), fleet_max_version),
        "user": device.get("user") or "",
        "tags": tags,
        "addresses": list(device.get("addresses") or []),
        "online": online,
        "last_seen": device.get("lastSeen") or "",
        "key_expiry": device.get("keyExpiry") or "",
        "key_expiry_state": expiry_state,
        "expiry_disabled": bool(device.get("expiryDisabled")),
        "authorized": bool(device.get("authorized")),
        "is_server": is_server,
        "is_external": bool(device.get("isExternal")),
        "approved_routes": approved,
        "advertised_routes": advertised,
        "subnet_routes": subnet_routes,
        "advertised_exit": _is_exit(advertised),
        "exit_node": _is_exit(approved),
        "_flags": {
            "online": online,
            "offline": not online,
            "unapproved": not device.get("authorized", True),
            "server": is_server,
            "expiring": expiry_state in ("expiring", "expired"),
            "expired": expiry_state == "expired",
            "external": bool(device.get("isExternal")),
            "stale": version_stale(_version(device), fleet_max_version),
        },
    }


def _version(device: dict) -> str:
    """Short client version: the live API sends only clientVersion
    ("1.104.1-t7f4efe814-g8da…"); older recordings carry "version"."""
    raw = device.get("version") or device.get("clientVersion") or ""
    return raw.split("-")[0]


def fleet_max_version(devices: list[dict]) -> str:
    best = (0, 0, 0)
    best_str = ""
    for device in devices:
        version = _version(device)
        parsed = _parse_ver(version)
        if parsed and parsed > best:
            best, best_str = parsed, version
    return best_str

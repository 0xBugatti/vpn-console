"""API: overview — attention queue, five stat tiles, quick actions, recent (US6).

Trust rule (FR-053 / VII): tiles and attention items are derived only from
OK-state data. A degraded/unavailable subsystem contributes zeros and its
health travels in _health — never silently-stale numbers.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body

from .. import audit, attention, db
from . import common
from .schemas import api_error

router = APIRouter()

_OS_KEY_FLAGS = {"linux", "macos", "windows", "ios", "android", "tvos"}


def _profile_rows() -> list[dict]:
    with db.get_conn() as c:
        rows = c.execute(
            "SELECT id, name, status, enabled, cert_expires_at FROM profiles"
        ).fetchall()
    return [
        {"id": r["id"], "name": r["name"], "status": r["status"],
         "enabled": bool(r["enabled"]), "cert_expires_at": r["cert_expires_at"] or ""}
        for r in rows
    ]


def _devices_or_empty() -> tuple[list[dict], dict]:
    from .devices import _devices_result

    return _devices_result()


def _local_status() -> dict | None:
    result = common.local_get("status", 10.0, common.local().status)
    return result.data if result.health.state == "ok" else None


def _service_rows() -> list[dict]:
    result = common.host_get("units", 10.0, common.host().units)
    return result.data if result.health.state == "ok" else []


def _exposure_rows() -> list[dict]:
    """Serve/funnel/drive entries for attention + tile (US8 wiring, FR-031)."""
    from . import exposures as exposures_api

    serve = exposures_api._serve_r()
    drive = exposures_api._drive_r()
    if serve.health.state != "ok" or drive.health.state != "ok":
        return []
    return exposures_api._entries((serve.data or {}).get("Config") or {},
                                  drive.data or {})


def _policy_errors() -> list[str]:
    """Applied ACL problems (queue item policy.errors) — empty when unreachable."""
    from .. import acl as acl_rules  # the validator, not server.api.acl

    result = common.cloud_get("acl", 10.0, common.cloud().get_acl_text)
    if result.health.state != "ok" or result.data is None:
        return []
    return [f'line {e["line"]}: {e["message"]}' for e in acl_rules.validate(result.data)]


@router.get("/health")
def health() -> dict[str, Any]:
    """Active per-subsystem health (FR-053): probes each subsystem now."""
    return {"subsystems": common.all_health()}


@router.get("/overview")
def overview() -> dict[str, Any]:
    health = common.all_health()

    profile_rows = _profile_rows()
    device_rows, device_health = _devices_or_empty()
    if device_health["state"] != "ok":
        device_rows = []
    local = _local_status()
    services = _service_rows()

    running = sum(1 for s in services if s.get("state") == "running")
    exp_rows = _exposure_rows()
    tailnet = sum(1 for e in exp_rows if e["kind"] in ("serve", "taildrive"))
    public = sum(1 for e in exp_rows if e["kind"] == "funnel")
    return {
        "attention": attention.attention_items(
            profile_rows, device_rows, local, services,
            exposures=exp_rows, policy_errors=_policy_errors(),
        ),
        "tiles": {
            "node": {"state": (local or {}).get("BackendState", "unknown")},
            "devices": {
                "online": sum(1 for d in device_rows if d["online"]),
                "total": len(device_rows),
            },
            "profiles": {
                "enabled": sum(1 for p in profile_rows if p["enabled"]),
                "total": len(profile_rows),
            },
            "exposures": {"tailnet": tailnet, "public": public, "public_alert": public > 0},
            "services": {"running": running, "total": len(services)},
        },
        "recent": audit.query(limit=10)[0],
        "_health": health,
    }


@router.post("/overview/connect-device")
def connect_device(body: dict = Body(...)) -> dict[str, Any]:
    """Command-crafting helper: mint a one-time auth key + copy-paste instruction."""
    os_name = str(body.get("os") or "linux").lower()
    if os_name not in _OS_KEY_FLAGS:
        raise api_error(422, "bad_os", f"Unsupported OS: {os_name}")
    kind = str(body.get("kind") or "user").lower()
    if kind not in ("user", "server"):
        raise api_error(422, "bad_kind", "kind must be user or server")

    tags = ["tag:server"] if kind == "server" else None
    try:
        key = common.cloud().create_auth_key(reusable=False, tags=tags)
    except Exception as exc:
        audit.insert("device.connect_key", "devices", target=kind, outcome="failed",
                     detail={"error": str(exc)[:300], "os": os_name})
        raise api_error(502, "action_failed", f"Tailscale refused to mint a key: {exc}")

    audit.insert("device.connect_key", "devices", target=kind,
                 detail={"os": os_name, "tagged_server": bool(tags)})

    if os_name == "linux":
        command = (f"curl -fsSL https://tailscale.com/install.sh | sh"
                   f" && sudo tailscale up --authkey={key}")
    elif os_name in ("macos", "windows", "tvos"):
        command = f"tailscale up --authkey={key}"
    else:  # ios, android — app sign-in flow, no shell
        command = ""
    hint = {
        "ios": "Install the Tailscale app, choose “Use an auth key”, and paste the key.",
        "android": "Install the Tailscale app, open the ⋮ menu → “Use an auth key”, and paste the key.",
    }.get(os_name, "Paste the command in a terminal on the new device.")
    return {"key": key, "command": command, "hint": hint, "os": os_name, "kind": kind}

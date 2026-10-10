"""API: devices — reads (list/tabs/filter/drawer) + lifecycle mutations (US5).

Friction tiers (constitution III, contracts/api.md): approve = tier 1 (no
dialog); expire-key = tier 2 ({confirm: true}); delete = tier 3 (type the
device name). Every mutation is audit-logged ok or failed (SC-004), and all
of them are refused while the tailnet subsystem cannot refresh (FR-053).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, Query

from .. import audit, devicemodel
from ..searchlang import predicate
from . import common
from .schemas import api_error, require_confirm, require_typed

router = APIRouter()


def _devices_result() -> tuple[list[dict], Any]:
    result = common.cloud_get("devices", ttl=60.0, fetch=common.cloud().list_devices)
    health = result.health.as_dict()
    if result.data is None:
        return [], health  # unavailable: empty list + loud health (FR-053)
    devices = result.data
    fleet_max = devicemodel.fleet_max_version(devices)
    rows = [devicemodel.device_view(d, fleet_max) for d in devices]
    return rows, health


def _find(did: str) -> dict:
    """Resolve one device from the (health-checked) tailnet cache."""
    rows, _ = _devices_result()
    for row in rows:
        if row["id"] == did:
            return row
    raise api_error(404, "not_found", "Device not found (refresh to pick up new devices).")


def _mutate(did: str, action: str, label: str, run, tier_note: str = "",
            detail: dict[str, Any] | None = None) -> dict[str, Any]:
    """Shared mutation skeleton: guard → run → audit ok|failed → invalidate (T040)."""
    target = _find(did)
    common.require_ok(
        common.cloud_get("devices", ttl=60.0, fetch=common.cloud().list_devices),
        "Tailscale",
    )
    name = target["hostname"] or target["name"] or did
    try:
        run()
    except HTTPException:
        raise
    except Exception as exc:
        audit.insert(f"device.{action}", "devices", target=name, outcome="failed",
                     detail={"error": str(exc)[:300], "device_id": did, **(detail or {})})
        raise api_error(
            502, "action_failed",
            f'Tailscale rejected "{label}" for {name}: {exc}{tier_note}',
        ) from exc
    common.cloud_cache().invalidate("devices")
    event_id = audit.insert(f"device.{action}", "devices", target=name,
                            detail={"device_id": did, **(detail or {})})
    return {"ok": True, "device_id": did, "event_id": event_id}


@router.get("/devices")
def list_devices(
    q: str = "",
    tab: str = Query("all", pattern="^(all|users|servers)$"),
) -> dict[str, Any]:
    rows, health = _devices_result()

    if tab == "users":
        rows = [r for r in rows if not r["is_server"]]
    elif tab == "servers":
        rows = [r for r in rows if r["is_server"]]

    if q:
        # "tag:server" matches Tailscale's "tag:server" chips AND the bare word
        def tags_getter(r: dict) -> list[str]:
            return r["tags"] + [t.removeprefix("tag:") for t in r["tags"]]

        rows = [r for r in rows if predicate(q, {
            "os": lambda r: r["os"],
            "tag": tags_getter,
            "user": lambda r: r["user"],
            "version": lambda r: r["version"],
            "name": lambda r: r["name"],
            "_text": lambda r: " ".join([r["name"], r["hostname"], r["user"],
                                         r["os"], *r["tags"], *r["addresses"]]),
            "_flags": lambda r: r["_flags"],
        })(r)]

    for r in rows:
        r.pop("_flags", None)  # internal, not part of the response contract

    return {
        "devices": rows,
        "counts": {
            "total": len(rows),
            "online": sum(1 for r in rows if r["online"]),
            "users": sum(1 for r in rows if not r["is_server"]),
            "servers": sum(1 for r in rows if r["is_server"]),
        },
        "_health": health,
    }


@router.get("/devices/{did}")
def get_device(did: str) -> dict[str, Any]:
    rows, health = _devices_result()
    for row in rows:
        if row["id"] == did:
            row.pop("_flags", None)
            return {**row, "_health": health}
    raise api_error(404, "not_found", "Device not found (refresh to pick up new devices).")


@router.post("/devices/{did}/approve")
def approve_device(did: str) -> dict[str, Any]:
    # Tier 1: reversible and low-blast — no dialog, no undo token (device can be
    # un-approved in the Tailscale admin; the audit log records the action).
    return _mutate(did, "approve", "Approve device",
                   lambda: common.cloud().approve_device(did))


@router.post("/devices/{did}/expire-key")
def expire_device_key(did: str = ..., body: dict = Body(default={})) -> dict[str, Any]:
    # Tier 2: disconnects the device until its user re-authenticates (FR-026).
    require_confirm(body)
    return _mutate(
        did, "expire_key", "Expire key",
        lambda: common.cloud().expire_key(did),
        tier_note=" The device stays disconnected until re-authentication.",
    )


@router.patch("/devices/{did}")
def update_device(did: str = ..., body: dict = Body(...)) -> dict[str, Any]:
    tags = body.get("tags")
    routes = body.get("routes_approved")
    require_reauth = body.get("require_reauth")
    if tags is None and routes is None and require_reauth is None:
        raise api_error(400, "no_changes",
                        "Nothing to update — send tags, routes_approved or require_reauth.")

    def run() -> None:
        cloud = common.cloud()
        if tags is not None:
            cloud.set_tags(did, [str(t) for t in tags])
        if routes is not None:
            cloud.set_approved_routes(did, [str(r) for r in routes])
        # "Require periodic re-authentication" ON == key expiry enabled (GH#4835 lesson)
        if require_reauth is not None:
            cloud.set_key_expiry_disabled(did, disabled=not bool(require_reauth))

    changed = [k for k, v in (("tags", tags), ("routes_approved", routes),
                              ("require_reauth", require_reauth)) if v is not None]
    return _mutate(did, "update", "Update device", run, detail={"changed": changed})


@router.delete("/devices/{did}")
def delete_device(did: str = ..., body: dict = Body(default={})) -> dict[str, Any]:
    # Tier 3: irreversible — the exact device name must be typed (FR-026).
    target = _find(did)
    require_typed(body, target["hostname"] or target["name"], "device")
    return _mutate(did, "delete", "Delete device",
                   lambda: common.cloud().delete_device(did))

"""API: node — local tailscaled control (US8, FR-041..044).

Friction tiers (constitution III): disconnect risks locking the admin out of
the host they are using, so it is tier 3 — type DISCONNECT *and* acknowledge
out-of-band (LAN/physical console) access in the same call. connect /
exit-node / routes are simple actions. Every mutation is audited ok|failed
and refused while tailscaled cannot refresh (FR-053).
"""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Body

from .. import audit, devicemodel
from ..adapters.base import OK, Result
from . import common
from .schemas import api_error, require_typed

router = APIRouter()

_CIDR_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}/\d{1,2}$")
_EXIT_ROUTES = {"0.0.0.0/0", "::/0"}


def _status() -> Result:
    return common.local_get("status", ttl=10.0, fetch=common.local().status)


def _prefs() -> Result:
    return common.local_get("prefs", ttl=10.0, fetch=common.local().prefs)


def _worst(*results: Result) -> Any:
    """The health to report for combined reads: any failure wins (Fail Loud)."""
    for r in results:
        if r.health.state != OK:
            return r.health
    return results[0].health


def _self_view(hostname: str, ip: str) -> dict[str, Any] | None:
    """This host's row from the tailnet view (None = unknown/unreachable)."""
    try:
        result = common.cloud_get("devices", ttl=60.0, fetch=common.cloud().list_devices)
    except Exception:  # noqa: BLE001 — join must never take the node page down
        return None
    if result.data is None:
        return None
    fleet_max = devicemodel.fleet_max_version(result.data)
    for d in result.data:
        view = devicemodel.device_view(d, fleet_max)
        if (hostname and view["hostname"] == hostname) or (ip and ip in view["addresses"]):
            return view
    return None


@router.get("/node")
def get_node() -> dict[str, Any]:
    status_r = _status()
    prefs_r = _prefs()
    status = status_r.data or {}
    prefs = prefs_r.data or {}
    advertised = list(prefs.get("AdvertiseRoutes") or [])
    self_host = (status.get("Self") or {}).get("HostName") or ""
    self_ip = (status.get("TailscaleIPs") or [""])[0]
    view = _self_view(self_host, self_ip)
    approved = {r for r in view["approved_routes"]} if view else None
    return {
        "state": status.get("BackendState") or "Unknown",
        "hostname": self_host,
        "addresses": status.get("TailscaleIPs") or [],
        "version": status.get("Version") or "",
        "self_device": (
            {"id": view["id"], "approved_routes": view["approved_routes"]} if view else None
        ),
        "exit_node": {
            "advertising": bool(_EXIT_ROUTES & set(advertised)),
            "using": prefs.get("ExitNodeIP") or prefs.get("ExitNodeID") or "",
        },
        "subnet_routes": [
            {
                "route": r,
                "advertised": True,
                "approved": (r in approved) if approved is not None else None,
            }
            for r in advertised
            if r not in _EXIT_ROUTES
        ],
        "_health": _worst(status_r, prefs_r).as_dict(),
    }


def _local_mutate(action: str, run, detail: dict[str, Any] | None = None) -> dict[str, Any]:
    """Shared local mutation: guard → run → audit ok|failed → invalidate (FR-053)."""
    common.require_ok(_status(), "local node")
    try:
        run()
    except Exception as exc:  # noqa: BLE001 — audited boundary (SC-004)
        audit.insert(f"node.{action}", "node", target="this host", outcome="failed",
                     detail={"error": str(exc)[:300], **(detail or {})})
        raise api_error(
            502, "action_failed", f'Local node rejected "{action}": {exc}',
        ) from exc
    common.local_cache().invalidate("status")
    common.local_cache().invalidate("prefs")
    event_id = audit.insert(f"node.{action}", "node", target="this host",
                            detail=detail or {})
    return {"ok": True, "event_id": event_id}


@router.post("/node/connect")
def connect_node() -> dict[str, Any]:
    return _local_mutate("connect", common.local().connect)


@router.post("/node/disconnect")
def disconnect_node(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    require_typed(body, "DISCONNECT", "disconnect")
    if not body.get("lan_ack"):
        raise api_error(
            409, "lan_ack_required",
            "Disconnecting can lock you out of this host over Tailscale. "
            "Tick the box to confirm you can still reach it via LAN or a "
            "physical console.",
        )
    return _local_mutate("disconnect", common.local().disconnect)


@router.post("/node/exit-node")
def set_exit_node(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    use = body.get("use")  # "" clears the selection; missing key = no change
    advertise = body.get("advertise")
    if use is None and advertise is None:
        raise api_error(400, "no_changes", "Nothing to change: pass use and/or advertise.")
    detail: dict[str, Any] = {}
    if advertise is not None:
        detail["advertise_exit"] = bool(advertise)
    if use is not None:
        detail["use_exit_node"] = use or None
    return _local_mutate(
        "exit_node",
        lambda: common.local().set_exit_node(
            use=use, advertise_exit=None if advertise is None else bool(advertise)
        ),
        detail=detail,
    )


@router.post("/node/routes")
def set_routes(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    tokens = body.get("advertise")
    if not isinstance(tokens, list) or not tokens:
        raise api_error(
            422, "invalid_route",
            'advertise must be a list of "+cidr" / "-cidr" tokens.',
        )
    added: list[str] = []
    removed: list[str] = []
    for token in tokens:
        text = str(token).strip()
        if len(text) < 2 or text[0] not in "+-":
            raise api_error(422, "invalid_route",
                            f'Invalid route token {token!r}; expected "+a.b.c.d/nn".')
        cidr = text[1:].strip()
        if not _CIDR_RE.match(cidr):
            raise api_error(422, "invalid_route", f'"{cidr}" is not a valid IPv4 CIDR.')
        (added if text[0] == "+" else removed).append(cidr)
    current = (_prefs().data or {}).get("AdvertiseRoutes") or []
    kept = [r for r in current if r not in removed and r not in added]
    new_routes = kept + [r for r in added if r not in kept]
    return _local_mutate(
        "routes",
        lambda: common.local().set_advertised_routes(new_routes),
        detail={"added": added, "removed": removed},
    )

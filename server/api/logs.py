"""API: logs — journalctl per-unit viewer (US9, FR-048, research D13).

Lines are read live per poll (the UI tails every 2–3 s with --after-cursor,
which is cheap), so a stale cache never gets between the admin and the log.
An unreachable journal is a loud unavailable state, never silent emptiness.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Response

from . import common
from .schemas import api_error

router = APIRouter()

SEVERITY = {"emerg": 0, "alert": 1, "crit": 2, "err": 3,
            "warning": 4, "notice": 5, "info": 6, "debug": 7}


def _parse_severity(raw: str) -> int:
    if raw in SEVERITY:
        return SEVERITY[raw]
    if raw.isdigit() and len(raw) == 1:
        return int(raw)
    raise api_error(422, "bad_severity", f'"{raw}" is not a journal severity.')


@router.get("/logs")
def logs_units() -> dict[str, Any]:
    result = common.host_get("units", ttl=15.0, fetch=common.host().units)
    units = [u["unit"] for u in (result.data or [])]
    return {"units": units, "_health": result.health.as_dict()}


@router.get("/logs/{unit}/download")
def logs_download(unit: str, severity: str = "", q: str = "") -> Response:
    sev = _parse_severity(severity) if severity else None
    try:
        entries = common.host().journal(unit, severity=sev, text=q, limit=500)
    except Exception as exc:  # noqa: BLE001 — loud, typed refusal (FR-053)
        raise api_error(503, "unavailable", f"Journal not reachable: {exc}") from exc
    text = "\n".join(f"{e['ts']} [{e['prio']}] {e['msg']}" for e in entries)
    return Response(
        content=text,
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{unit}.log"'},
    )


@router.get("/logs/{unit}")
def logs_lines(
    unit: str,
    severity: str = Query("", pattern="^(emerg|alert|crit|err|warning|notice|info|debug|[0-7])?$"),
    q: str = "",
    after: str = "",
    limit: int = Query(200, ge=1, le=500),
) -> dict[str, Any]:
    sev = _parse_severity(severity) if severity else None
    try:
        entries = common.host().journal(unit, severity=sev, text=q, limit=limit,
                                        after_cursor=after)
    except Exception as exc:  # noqa: BLE001 — loud state, not silent emptiness
        return {
            "lines": [],
            "next_cursor": after,
            "_health": {"state": "unavailable", "detail": str(exc)[:200],
                        "last_ok": 0.0, "age_seconds": 0.0},
        }
    return {
        "lines": [{"ts": e["ts"], "prio": e["prio"], "msg": e["msg"]} for e in entries],
        "next_cursor": entries[-1]["cursor"] if entries else after,
        "_health": common.host_cache().health().as_dict(),
    }

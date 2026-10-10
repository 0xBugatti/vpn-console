"""API: services — systemd units on this host (US9, FR-045..047).

The adapter enforces the unit allow-list; stop/restart are confirm-tier
(constitution III); actions run on a worker thread and are pollable via
GET /api/jobs/{id}. Every action is audited ok|failed when it completes.
"""
from __future__ import annotations

import threading
from typing import Any

from fastapi import APIRouter, Body

from .. import audit
from ..adapters.host import unit_allowed
from . import common
from .schemas import api_error, require_confirm

router = APIRouter()

ACTIONS = ("start", "stop", "restart", "enable", "disable")
CONFIRM_ACTIONS = {"stop", "restart"}

_jobs: dict[str, dict[str, Any]] = {}
_seq = 0
_lock = threading.Lock()


def _units_result():
    return common.host_get("units", ttl=15.0, fetch=common.host().units)


@router.get("/services")
def list_services() -> dict[str, Any]:
    result = _units_result()
    return {"units": result.data or [], "_health": result.health.as_dict()}


@router.post("/services/{unit}/{action}")
def unit_action(unit: str, action: str, body: dict = Body(default={})) -> dict[str, Any]:
    if action not in ACTIONS:
        raise api_error(422, "bad_action", f'"{action}" is not a service action.')
    if not unit_allowed(unit):
        raise api_error(403, "unit_not_allowed", f'"{unit}" is not managed by the console.')
    if action in CONFIRM_ACTIONS:
        require_confirm(body)
    # FR-053: no service surgery while the host layer cannot refresh.
    common.require_ok(_units_result(), "host services")
    return {"job_id": _launch(unit, action)}


def _launch(unit: str, action: str) -> str:
    global _seq
    with _lock:
        _seq += 1
        job_id = f"job-{_seq}"
    _jobs[job_id] = {"done": False, "ok": False, "detail": f"{action} {unit}…"}

    def work() -> None:
        try:
            common.host().unit_action(unit, action)
            _jobs[job_id].update(done=True, ok=True, detail="")
            audit.insert(f"service.{action}", "services", target=unit)
        except Exception as exc:  # noqa: BLE001 — audited boundary (SC-004)
            _jobs[job_id].update(done=True, ok=False, detail=str(exc)[:300])
            audit.insert(f"service.{action}", "services", target=unit, outcome="failed",
                         detail={"error": str(exc)[:300]})
        common.host_cache().invalidate("units")

    threading.Thread(target=work, daemon=True).start()
    return job_id


@router.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = _jobs.get(job_id)
    if job is None:
        raise api_error(404, "not_found", "Unknown job id.")
    return dict(job)

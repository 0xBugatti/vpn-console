"""API: undo tokens (tier-1 friction, FR-013/FR-051). Admin-gated via app wiring."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from .. import audit
from ..undo import store
from .schemas import api_error

router = APIRouter()


@router.post("/undo/{token}")
def perform_undo(token: str) -> dict[str, Any]:
    try:
        entry = store.pop(token)
    except KeyError:
        raise api_error(410, "undo_expired",
                        "The undo window has passed; nothing was changed.")  # noqa: B904
    try:
        entry.restore()
    except Exception as exc:  # noqa: BLE001 — audit the failure, then fail loud
        audit.insert(f"undo.{entry.label}", entry.section, outcome="failed",
                     detail={"error": str(exc)}, undoes_event_id=entry.event_id)
        raise api_error(500, "undo_failed", f"Undo failed: {exc}")  # noqa: B904
    audit.insert(f"undo.{entry.label}", entry.section, outcome="undone",
                 undoes_event_id=entry.event_id)
    return {"ok": True}

"""API: audit — filterable reverse-chron trail + exact-set JSON export (US11).

The table is append-only (SQLite triggers, T006); this layer only reads and
joins the undo links. Export walks the exact same filter code path, so the
attachment always equals the union of the matching pages (SC-004).
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Query, Response

from .. import audit, db

router = APIRouter()


def _row_view(row: dict[str, Any], undone_by: dict[int, int]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "ts": row["ts"],
        "action": row["action"],
        "section": row["section"],
        "target": row["target"],
        "outcome": row["outcome"],
        "detail": json.loads(row["detail"] or "{}"),
        "undoes_event_id": row["undoes_event_id"],
        "undone_by": undone_by.get(row["id"]),
    }


def _undone_map(ids: list[int]) -> dict[int, int]:
    """Newest outcome=undone event referencing each row — the UI's undo link."""
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    rows = db.get_conn().execute(
        f"SELECT id, undoes_event_id FROM audit"  # noqa: S608 — marks are '?' placeholders
        f" WHERE outcome = 'undone' AND undoes_event_id IN ({marks})"
        " ORDER BY id DESC",
        ids,
    ).fetchall()
    out: dict[int, int] = {}
    for r in rows:
        out.setdefault(r["undoes_event_id"], r["id"])
    return out


@router.get("/audit")
def get_audit(
    action: str | None = Query(None),
    section: str | None = Query(None),
    outcome: str | None = Query(None),
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None, alias="to"),
    limit: int = Query(50, ge=1, le=500),
    cursor: int | None = Query(None),
) -> dict[str, Any]:
    rows, next_cursor = audit.query(
        action=action, section=section, outcome=outcome,
        from_ts=from_, to_ts=to, limit=limit, cursor=cursor,
    )
    undone = _undone_map([r["id"] for r in rows])
    return {"entries": [_row_view(r, undone) for r in rows], "next_cursor": next_cursor}


@router.get("/audit/export")
def export_audit(
    action: str | None = Query(None),
    section: str | None = Query(None),
    outcome: str | None = Query(None),
    from_: str | None = Query(None, alias="from"),
    to: str | None = Query(None, alias="to"),
) -> Response:
    rows = list(audit.iter_filtered(
        action=action, section=section, outcome=outcome, from_ts=from_, to_ts=to,
    ))
    undone = _undone_map([r["id"] for r in rows])
    payload = json.dumps([_row_view(r, undone) for r in rows], indent=2)
    return Response(
        content=payload,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="audit.json"'},
    )

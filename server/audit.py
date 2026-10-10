"""Append-only audit repository (FR-050, research D8).

insert() + query() ONLY — the SQLite triggers in db.py back the guarantee that
history is never rewritten.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Iterator

from .db import get_conn

PAGE_SIZE = 50


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def insert(
    action: str,
    section: str,
    target: str = "",
    outcome: str = "ok",
    detail: dict[str, Any] | None = None,
    undoes_event_id: int | None = None,
    conn: Any = None,
) -> int:
    c = conn or get_conn()
    cur = c.execute(
        "INSERT INTO audit(ts, action, section, target, outcome, detail, undoes_event_id)"
        " VALUES(?,?,?,?,?,?,?)",
        (
            now_iso(),
            action,
            section,
            target,
            outcome,
            json.dumps(detail or {}, separators=(",", ":")),
            undoes_event_id,
        ),
    )
    return int(cur.lastrowid)


def _rows(c: Any, where: str, params: tuple, limit: int, cursor: int | None) -> tuple[list[dict], int | None]:
    sql = "SELECT * FROM audit"
    clauses: list[str] = []
    args: list = []
    if cursor is not None:
        clauses.append("id < ?")
        args.append(cursor)
    if where:
        clauses.append(where)
        args.extend(params)  # args follow clause order — cursor clause comes first
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(min(limit, 500))
    rows = [dict(r) for r in c.execute(sql, args).fetchall()]
    next_cursor = rows[-1]["id"] if len(rows) == min(limit, 500) else None
    return rows, next_cursor


def query(
    action: str | None = None,
    section: str | None = None,
    outcome: str | None = None,
    from_ts: str | None = None,
    to_ts: str | None = None,
    limit: int = PAGE_SIZE,
    cursor: int | None = None,
) -> tuple[list[dict], int | None]:
    """Reverse-chron page. Filters per contracts/api.md; export = same query."""
    where_parts, params = [], []
    if action:
        where_parts.append("action = ?")
        params.append(action)
    if section:
        where_parts.append("section = ?")
        params.append(section)
    if outcome:
        where_parts.append("outcome = ?")
        params.append(outcome)
    if from_ts:
        where_parts.append("ts >= ?")
        params.append(from_ts)
    if to_ts:
        where_parts.append("ts <= ?")
        params.append(to_ts)
    return _rows(get_conn(), " AND ".join(where_parts), tuple(params), limit, cursor)


def iter_filtered(**filters: Any) -> Iterator[dict]:
    """Full filtered set for export (SC-004)."""
    cursor = None
    while True:
        rows, cursor = query(limit=500, cursor=cursor, **{
            k: v for k, v in filters.items() if v
        })
        yield from rows
        if cursor is None:
            return


def recent(limit: int = 10) -> list[dict]:
    rows, _ = query(limit=limit)
    return rows

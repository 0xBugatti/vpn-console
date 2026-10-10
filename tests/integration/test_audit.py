"""US11 — audit integration (T065, FR-050/SC-004): the friction-tier matrix,
filter combos, exact-set export, and the append-only guarantee (T006 trigger).
"""
from __future__ import annotations

import json
import sqlite3
import time

import pytest

from server import audit


@pytest.fixture()
def matrix():
    """One event per friction tier + a failure + its undo. Returns the base id."""
    base = audit.insert("matrix.disable", "profiles", target="matrix-phone",
                        detail={"undo_token": "tok-m1"})
    audit.insert("undo.matrix-disable", "profiles", target="matrix-phone",
                 outcome="undone", undoes_event_id=base)
    audit.insert("matrix.expire-key", "devices", target="matrix-laptop",
                 detail={"confirm": True})
    audit.insert("matrix.wipe", "settings", target="matrix-all",
                 detail={"typed_confirm": "WIPE"})
    audit.insert("matrix.stop", "services", target="matrix-unit",
                 outcome="failed", detail={"error": "boom"})
    return base


def _ids(body):
    return [e["id"] for e in body["entries"]]


def test_matrix_newest_first_with_complete_fields(authed, matrix):
    body = authed.get("/api/audit", params={"limit": 500}).json()
    mine = [e for e in body["entries"] if e["id"] >= matrix]  # this fixture run only
    assert [e["action"] for e in mine] == [
        "matrix.stop", "matrix.wipe", "matrix.expire-key",
        "undo.matrix-disable", "matrix.disable",
    ]  # newest-first (reverse insert order)
    top = mine[0]
    assert set(top) >= {"id", "ts", "action", "section", "target",
                        "outcome", "detail", "undoes_event_id", "undone_by"}
    assert top["outcome"] == "failed" and top["detail"] == {"error": "boom"}
    assert top["section"] == "services" and top["target"] == "matrix-unit"


def test_undo_link_runs_both_ways(authed, matrix):
    body = authed.get("/api/audit", params={"limit": 500}).json()
    mine = [e for e in body["entries"] if e["id"] >= matrix]  # this fixture run only
    undo_ev = next(e for e in mine if e["action"] == "undo.matrix-disable")
    assert undo_ev["outcome"] == "undone"
    assert undo_ev["undoes_event_id"] == matrix
    base = next(e for e in mine if e["id"] == matrix)
    assert base["undone_by"] == undo_ev["id"]


def test_filter_combos(authed):
    ok1 = audit.insert("combo.a", "combo-sec", target="t1", outcome="ok")
    fail = audit.insert("combo.a", "combo-sec", target="t2", outcome="failed")
    other = audit.insert("combo.b", "combo-sec", target="t3", outcome="ok")

    got = _ids(authed.get("/api/audit", params={"action": "combo.a"}).json())
    assert set(got) >= {ok1, fail} and other not in got

    got = _ids(authed.get("/api/audit", params={"action": "combo.a", "outcome": "failed"}).json())
    assert fail in got and ok1 not in got and other not in got

    got = _ids(authed.get("/api/audit", params={"section": "combo-sec"}).json())
    assert {ok1, fail, other} <= set(got)

    got = _ids(authed.get("/api/audit", params={"action": "combo.nope"}).json())
    assert not got


def test_from_to_window(authed):
    before = audit.insert("window.x", "window-sec", target="w1")
    time.sleep(1.1)  # ts has second granularity — force a distinct stamp
    after = audit.insert("window.x", "window-sec", target="w2")
    ts_before = next(e for e in authed.get("/api/audit", params={"limit": 500}).json()["entries"]
                     if e["id"] == before)["ts"]

    got = _ids(authed.get("/api/audit", params={"section": "window-sec",
                                                "from": ts_before}).json())
    assert after in got and before in got  # inclusive lower bound

    got = _ids(authed.get("/api/audit", params={"section": "window-sec",
                                                "from": "2090-01-01T00:00:00Z"}).json())
    assert not got

    got = _ids(authed.get("/api/audit", params={"section": "window-sec",
                                                "to": "2090-01-01T00:00:00Z"}).json())
    assert {before, after} <= set(got)


def test_cursor_pagination_covers_exactly_once(authed):
    ids = [audit.insert("page.y", "page-sec", target=f"p{i}") for i in range(5)]
    seen, cursor = [], None
    for _ in range(10):
        params = {"action": "page.y", "limit": 2}
        if cursor:
            params["cursor"] = cursor
        body = authed.get("/api/audit", params=params).json()
        seen += _ids(body)
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert seen == ids[::-1]  # every event exactly once, newest-first
    assert cursor is None


def test_export_is_exactly_the_filtered_set(authed):
    keep = audit.insert("exp.z", "exp-sec", target="keep1", outcome="failed")
    audit.insert("exp.z", "exp-sec", target="skip", outcome="ok")
    keep2 = audit.insert("exp.z", "exp-sec", target="keep2", outcome="failed")

    r = authed.get("/api/audit/export", params={"action": "exp.z", "outcome": "failed"})
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    assert r.headers["content-type"].startswith("application/json")
    rows = json.loads(r.text)
    ids = [row["id"] for row in rows]
    assert ids == [keep2, keep]  # exact set, nothing more, newest-first
    assert all(row["action"] == "exp.z" and row["outcome"] == "failed" for row in rows)


def test_audit_table_refers_update_and_delete(authed):
    from server.settings import CONFIG

    conn = sqlite3.connect(CONFIG.db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT id FROM audit ORDER BY id DESC LIMIT 1").fetchone()
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE audit SET outcome='ok' WHERE id=?", (row["id"],))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM audit WHERE id=?", (row["id"],))
    conn.close()

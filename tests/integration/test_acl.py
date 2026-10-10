"""US7 — ACL editor flows (T048, FR-040/041, research D14: text is canonical)."""
from __future__ import annotations

from pathlib import Path

FIXTURE_ACL = Path(__file__).parents[1] / "fixtures" / "tailscale/acl.hujson"


def _draft_with_extra_rule(base: str) -> str:
    extra = '\t{"action": "accept", "src": ["group:admins"], "dst": ["nas:*"]},\n'
    marker = '\t{"action": "accept", "src": ["tag:server"], "dst": ["*:*"]},\n'
    return base.replace(marker, marker + extra)


def test_get_returns_applied_text_structured_no_draft(authed):
    body = authed.get("/api/acl").json()
    assert body["applied_text"] == FIXTURE_ACL.read_text()  # bytes, comments intact
    kinds = {s["kind"] for s in body["structured"]}
    assert {"groups", "tagOwners", "hosts", "acls", "nodeAttrs"} <= kinds
    assert body["draft"] is None


def test_draft_syntax_error_reports_line(authed):
    bad = FIXTURE_ACL.read_text() + "\n}}"  # stray closing brace at the end
    r = authed.put("/api/acl/draft", json={"text": bad})
    body = r.json()
    assert body["valid"] is False
    assert body["errors"][0]["line"] >= 1
    assert body["errors"][0]["message"]


def test_draft_reference_error_names_the_unknown_ref(authed):
    bad = FIXTURE_ACL.read_text().replace(
        '"src": ["group:devs"]', '"src": ["group:ghosts"]', 1)
    r = authed.put("/api/acl/draft", json={"text": bad})
    body = r.json()
    assert body["valid"] is False
    assert any("group:ghosts" in e["message"] for e in body["errors"])


def test_valid_draft_stored_and_diff_shows_rule(authed):
    draft = _draft_with_extra_rule(FIXTURE_ACL.read_text())
    r = authed.put("/api/acl/draft", json={"text": draft})
    assert r.json()["valid"] is True

    body = authed.get("/api/acl").json()
    assert body["draft"] == draft  # preserved for the editor

    diff = authed.get("/api/acl/diff").json()
    assert len(diff["added"]) == 1
    assert "group:admins" in diff["added"][0] and "nas" in diff["added"][0]
    assert diff["removed"] == []


def test_apply_without_confirm_refused(authed):
    authed.put("/api/acl/draft", json={"text": _draft_with_extra_rule(FIXTURE_ACL.read_text())})
    r = authed.post("/api/acl/apply", json={})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "confirm_required"


def test_apply_invalid_draft_409_validation_failed(authed):
    bad = FIXTURE_ACL.read_text().replace('"src": ["group:devs"]',
                                          '"src": ["group:ghosts"]', 1)
    authed.put("/api/acl/draft", json={"text": bad})
    r = authed.post("/api/acl/apply", json={"confirm": True})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "validation_failed"
    # applied text untouched
    assert authed.get("/api/acl").json()["applied_text"] == FIXTURE_ACL.read_text()


def test_apply_rollback_byte_identical_and_audited(authed, fakes):
    original = FIXTURE_ACL.read_text()
    authed.put("/api/acl/draft", json={"text": _draft_with_extra_rule(original)})
    r = authed.post("/api/acl/apply", json={"confirm": True})
    assert r.status_code == 200, r.text
    assert authed.get("/api/acl").json()["applied_text"] != original

    rb = authed.post("/api/acl/rollback")
    assert rb.status_code == 200, rb.text
    after = authed.get("/api/acl").json()["applied_text"]
    assert after == original  # byte-identical — comments and all (D14)

    events = authed.get("/api/overview").json()["recent"]
    actions = [e["action"] for e in events]
    assert "acl.apply" in actions and "acl.rollback" in actions

    # nothing pinned anymore
    again = authed.post("/api/acl/rollback")
    assert again.status_code == 409


def test_apply_needs_live_subsystem(authed, fakes):
    from server.api import common

    authed.get("/api/acl")  # prime cache
    fakes["cloud"].break_()
    stamp, data = common._cloud_cache._entries["acl"]
    common._cloud_cache._entries["acl"] = (stamp - 61, data)
    authed.put("/api/acl/draft", json={"text": _draft_with_extra_rule(FIXTURE_ACL.read_text())})
    r = authed.post("/api/acl/apply", json={"confirm": True})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "subsystem_unavailable"

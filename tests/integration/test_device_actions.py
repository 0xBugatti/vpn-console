"""US5 — device mutation friction matrix (T039, SC-004/SC-005, FR-053)."""
from __future__ import annotations

from server import audit

NAS = "9"  # nas-server: unapproved, advertises 192.168.1.0/24


def _nas_hostname(authed) -> str:
    rows = authed.get("/api/devices").json()["devices"]
    return next(d["hostname"] for d in rows if d["id"] == NAS)


def test_approve_needs_no_confirm(authed, fakes):
    r = authed.post(f"/api/devices/{NAS}/approve")
    assert r.status_code == 200, r.text
    row = next(d for d in authed.get("/api/devices").json()["devices"] if d["id"] == NAS)
    assert row["authorized"] is True


def test_expire_key_requires_confirm(authed, fakes):
    r = authed.post(f"/api/devices/7/expire-key", json={})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "confirm_required"

    ok = authed.post("/api/devices/7/expire-key", json={"confirm": True})
    assert ok.status_code == 200
    row = next(d for d in authed.get("/api/devices").json()["devices"] if d["id"] == "7")
    assert row["key_expiry_state"] == "expired"


def test_delete_requires_typed_hostname(authed, fakes):
    hostname = _nas_hostname(authed)
    r = authed.request("DELETE", f"/api/devices/{NAS}", json={})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "typed_confirm_required"

    wrong = authed.request("DELETE", f"/api/devices/{NAS}",
                           json={"typed_confirm": "wrong-name"})
    assert wrong.status_code == 409

    ok = authed.request("DELETE", f"/api/devices/{NAS}",
                        json={"typed_confirm": hostname})
    assert ok.status_code == 200
    assert all(d["id"] != NAS for d in authed.get("/api/devices").json()["devices"])


def test_patch_tags_reauth_routes(authed, fakes):
    r = authed.patch(f"/api/devices/{NAS}", json={"tags": ["tag:server", "tag:nas"]})
    assert r.status_code == 200
    d = next(d for d in authed.get("/api/devices").json()["devices"] if d["id"] == NAS)
    assert d["tags"] == ["tag:server", "tag:nas"]

    r = authed.patch(f"/api/devices/{NAS}", json={"routes_approved": ["192.168.1.0/24"]})
    assert r.status_code == 200
    d = next(d for d in authed.get("/api/devices").json()["devices"] if d["id"] == NAS)
    assert d["approved_routes"] == ["192.168.1.0/24"]
    assert d["subnet_routes"] == ["192.168.1.0/24"]

    # require_reauth=true re-enables key expiry on the build server
    r = authed.patch("/api/devices/3", json={"require_reauth": True})
    assert r.status_code == 200
    d = next(d for d in authed.get("/api/devices").json()["devices"] if d["id"] == "3")
    assert d["key_expiry_state"] != "never"


def test_every_mutation_audited_ok_or_failed(authed, fakes):
    authed.get("/api/devices")  # prime the cache — mutations read through it
    fakes["cloud"].fail_next = True
    r = authed.post(f"/api/devices/{NAS}/approve")
    assert r.status_code == 502  # forced adapter failure surfaces loud

    authed.post(f"/api/devices/{NAS}/approve")  # now succeeds

    events = audit.query(section="devices", limit=50)[0]
    approve_events = [e for e in events if e["action"] == "device.approve"]
    assert {e["outcome"] for e in approve_events} >= {"ok", "failed"}
    failed = next(e for e in approve_events if e["outcome"] == "failed")
    assert failed["detail"]  # error summary recorded


def test_mutations_disabled_while_subsystem_down(authed, fakes):
    from server.api import common

    authed.get("/api/devices")  # prime cache
    fakes["cloud"].break_()
    stamp, data = common._cloud_cache._entries["devices"]
    common._cloud_cache._entries["devices"] = (stamp - 61, data)  # force stale

    for call in (
        lambda: authed.post(f"/api/devices/{NAS}/approve"),
        lambda: authed.post("/api/devices/7/expire-key", json={"confirm": True}),
        lambda: authed.patch(f"/api/devices/{NAS}", json={"tags": ["tag:x"]}),
        lambda: authed.request("DELETE", f"/api/devices/{NAS}",
                               json={"typed_confirm": "nas-server"}),
    ):
        r = call()
        assert r.status_code == 409, r.text
        assert r.json()["error"]["code"] == "subsystem_unavailable"
    fakes["cloud"].repair()

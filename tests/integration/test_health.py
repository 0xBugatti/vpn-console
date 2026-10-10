"""Foundational — health envelope + stale propagation (SC-010, research D10)."""
from __future__ import annotations


def test_health_reports_all_subsystems(authed):
    data = authed.get("/api/health").json()["subsystems"]
    assert set(data) == {"tscloud", "tslocal", "host"}
    for subsystem in data.values():
        assert subsystem["state"] in ("ok", "degraded", "unavailable")


def test_broken_subsystem_degrades_reads_and_reports(authed, fakes):
    fakes["cloud"].break_()
    r = authed.get("/api/devices")
    body = r.json()
    assert body["_health"]["state"] in ("degraded", "unavailable")
    assert body["_health"]["detail"], "a broken adapter must say why"

    # cached last-good data (if any) carries its age; nothing pretends to be live
    health = authed.get("/api/health").json()["subsystems"]["tscloud"]
    assert health["state"] in ("degraded", "unavailable")
    fakes["cloud"].repair()
    assert authed.get("/api/health").json()["subsystems"]["tscloud"]["state"] == "ok"

"""US4 — devices read API (T035): tabs, filters, drawer payload, stale reads."""
from __future__ import annotations

import time


def test_tabs_split_user_and_server(authed):
    data = authed.get("/api/devices", params={"tab": "servers"}).json()
    assert data["counts"]["total"] == data["counts"]["servers"] == 3
    assert all(d["is_server"] for d in data["devices"])

    users = authed.get("/api/devices", params={"tab": "users"}).json()
    assert users["counts"]["total"] == 3
    assert all(not d["is_server"] for d in users["devices"])


def test_row_fields_expiry_never(authed):
    rows = authed.get("/api/devices").json()["devices"]
    build = next(d for d in rows if d["hostname"] == "build-server")
    assert build["key_expiry_state"] == "never"
    assert build["expiry_disabled"] is True
    # addresses start with 100. for copy-on-click (FR-020)
    assert build["addresses"][0].startswith("100.")


def test_filters_flags_and_negation(authed):
    hit = authed.get("/api/devices", params={"q": "is:expiring"}).json()["devices"]
    assert {d["hostname"] for d in hit} == {"guest-tablet"}  # key expired 2026-09

    hit = authed.get("/api/devices", params={"q": "is:offline"}).json()["devices"]
    assert {d["hostname"] for d in hit} == {"jonas-phone", "guest-tablet"}

    hit = authed.get("/api/devices", params={"q": "is:unapproved"}).json()["devices"]
    assert [d["hostname"] for d in hit] == ["nas-server"]

    hit = authed.get("/api/devices", params={"q": "tag:server !os:ios"}).json()["devices"]
    assert len(hit) == 3
    assert all("ios" not in d["os"] for d in hit)


def test_drawer_payload_complete(authed):
    rows = authed.get("/api/devices").json()["devices"]
    did = next(d["id"] for d in rows if d["hostname"] == "nas-server")
    d = authed.get(f"/api/devices/{did}").json()
    for field in ("name", "os", "version", "user", "tags", "addresses", "online",
                  "last_seen", "key_expiry", "key_expiry_state", "expiry_disabled",
                  "authorized", "approved_routes", "advertised_routes",
                  "subnet_routes", "is_server", "_health"):
        assert field in d, f"drawer payload missing {field}"


def test_drawer_404(authed):
    assert authed.get("/api/devices/nope").status_code == 404


def test_unreachable_serves_stale_with_age(authed, fakes):
    from server.api import common

    assert authed.get("/api/devices").status_code == 200  # prime the cache
    fakes["cloud"].break_()

    stamp, data = common._cloud_cache._entries["devices"]
    common._cloud_cache._entries["devices"] = (stamp - 61, data)  # force TTL expiry

    body = authed.get("/api/devices").json()
    assert body["_health"]["state"] == "degraded"
    assert body["_health"]["age_seconds"] >= 60
    assert body["_health"]["detail"]
    assert len(body["devices"]) == 6  # last-good data, loudly aged (FR-053)
    fakes["cloud"].repair()

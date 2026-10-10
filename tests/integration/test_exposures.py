"""US10 — exposures integration (T062, FR-043/044): funnel constraints, scope
badges data, port annotations, collision warning."""
from __future__ import annotations


def test_get_exposures_shape(authed):
    body = authed.get("/api/exposures").json()
    by_id = {e["id"]: e for e in body["entries"]}

    funnel = by_id["tcp-443"]
    assert funnel["kind"] == "funnel" and funnel["scope"] == "public"
    assert funnel["tls"] is True and funnel["source"].startswith("https://")

    serve = by_id["tcp-8080"]
    assert serve["kind"] == "serve" and serve["scope"] == "tailnet"

    drive = by_id["drive-/photos"]
    assert drive["kind"] == "taildrive" and drive["scope"] == "share"

    # every listening port carries exactly one annotation (FR-044)
    assert {p["annotation"] for p in body["ports"]} <= {"funnel", "serve", "local_only", "unexposed"}
    ann = {p["local_addr"]: p["annotation"] for p in body["ports"]}
    assert ann["*:443"] == "funnel"
    assert ann["127.0.0.1:3000"] == "local_only"
    assert ann["0.0.0.0:22"] == "unexposed"
    assert body["collisions"] == []
    assert body["_health"]["state"] == "ok"


def test_funnel_disallowed_port_rejected_before_friction(authed):
    # no confirm in the body — the port error must win (constraint BEFORE friction)
    r = authed.post("/api/exposures", json={"kind": "funnel", "port": 8080,
                                            "target": "http://127.0.0.1:5000"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "port_not_allowed"


def test_funnel_create_is_confirm_tier(authed):
    r = authed.post("/api/exposures", json={"kind": "funnel", "port": 443,
                                            "target": "http://127.0.0.1:5001"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "confirm_required"

    r = authed.post("/api/exposures", json={"kind": "funnel", "port": 443,
                                            "target": "http://127.0.0.1:5001",
                                            "confirm": True})
    assert r.status_code == 200, r.text
    by_id = {e["id"]: e for e in authed.get("/api/exposures").json()["entries"]}
    assert by_id["tcp-443"]["target"].endswith("5001")


def test_funnel_enable_is_confirm_tier(authed):
    r = authed.patch("/api/exposures/tcp-443", json={"enabled": True})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "confirm_required"


def test_serve_create_is_tier_one(authed):
    r = authed.post("/api/exposures", json={"kind": "serve", "port": 5000,
                                            "target": "http://127.0.0.1:5000", "tls": False})
    assert r.status_code == 200, r.text
    by_id = {e["id"]: e for e in authed.get("/api/exposures").json()["entries"]}
    assert by_id["tcp-5000"]["scope"] == "tailnet"
    assert by_id["tcp-5000"]["target"].startswith("proxy")


def test_serve_and_funnel_on_one_port_collide(authed, fakes):
    authed.post("/api/exposures", json={"kind": "serve", "port": 5000,
                                        "target": "http://127.0.0.1:5000", "tls": False})
    # a funnel allowance for a different name lands on the served port
    fakes["local"].serve_config.setdefault("AllowFunnel", {})[
        "staging.fangorn.example.com:5000"] = True
    body = authed.get("/api/exposures").json()
    assert body["collisions"] == [5000]


def test_disable_removes_the_listener(authed):
    r = authed.patch("/api/exposures/tcp-8080", json={"enabled": False})
    assert r.status_code == 200, r.text
    ids = {e["id"] for e in authed.get("/api/exposures").json()["entries"]}
    assert "tcp-8080" not in ids


def test_drive_disable_not_supported(authed):
    r = authed.patch("/api/exposures/drive-/photos", json={"enabled": False})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "not_supported"


def test_delete_requires_confirm(authed):
    # removal is confirm-tier server-side (contract; the UI dialog supplies it)
    r = authed.delete("/api/exposures/tcp-8080")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "confirm_required"


def test_delete_serve_and_drive(authed):
    # this httpx version takes no json= on delete — use request()
    assert authed.request("DELETE", "/api/exposures/tcp-8080", json={"confirm": True}).status_code == 200
    assert authed.request("DELETE", "/api/exposures/drive-/backup", json={"confirm": True}).status_code == 200
    ids = {e["id"] for e in authed.get("/api/exposures").json()["entries"]}
    assert "tcp-8080" not in ids and "drive-/backup" not in ids

    # assert via the audit trail (overview "recent" is a 10-event window)
    actions = [e["action"] for e in authed.get("/api/audit?limit=500").json()["entries"]]
    assert "exposure.delete" in actions and "exposure.create" in actions


def test_unknown_entry_is_404(authed):
    assert authed.delete("/api/exposures/tcp-9999").status_code == 404


def test_mutations_blocked_while_local_down(authed, fakes):
    from server.api import common

    authed.get("/api/exposures")  # prime
    fakes["local"].break_()
    stamp, data = common._local_cache._entries["serve"]
    common._local_cache._entries["serve"] = (stamp - 11, data)
    for call in (
        lambda: authed.post("/api/exposures", json={"kind": "serve", "port": 5000,
                                                    "target": "http://127.0.0.1:5"}),
        lambda: authed.patch("/api/exposures/tcp-8080", json={"enabled": False}),
        lambda: authed.delete("/api/exposures/tcp-8080"),
    ):
        r = call()
        assert r.status_code == 409, r.text
        assert r.json()["error"]["code"] == "subsystem_unavailable"

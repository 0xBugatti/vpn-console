"""US8 — local node control (T053, FR-042): disconnect friction, exit/route edits."""
from __future__ import annotations


def test_get_node_state(authed):
    body = authed.get("/api/node").json()
    assert body["state"] == "Running"
    assert body["addresses"][0].startswith("100.")
    assert body["version"].startswith("1.")
    assert body["exit_node"] == {"advertising": False, "using": ""}
    row = next(r for r in body["subnet_routes"] if r["route"] == "10.20.0.0/16")
    assert row["advertised"] is True
    assert row["approved"] is False  # cloud view: build-server has no approvals yet


def test_approved_routes_join_the_cloud_view(authed, fakes):
    from server.api import common

    fakes["cloud"].set_approved_routes("3", ["10.20.0.0/16"])
    common.cloud_cache().invalidate("devices")
    row = next(r for r in authed.get("/api/node").json()["subnet_routes"]
               if r["route"] == "10.20.0.0/16")
    assert row["approved"] is True


def test_disconnect_needs_typed_confirm(authed, fakes):
    r = authed.post("/api/node/disconnect", json={})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "typed_confirm_required"


def test_disconnect_needs_lan_acknowledgement(authed, fakes):
    r = authed.post("/api/node/disconnect", json={"typed_confirm": "DISCONNECT"})
    assert r.status_code == 409
    body = r.json()
    assert body["error"]["code"] == "lan_ack_required"
    assert "lock" in body["error"]["message"].lower()  # self-lockout spelled out


def test_disconnect_and_connect_round_trip(authed, fakes):
    r = authed.post("/api/node/disconnect",
                    json={"typed_confirm": "DISCONNECT", "lan_ack": True})
    assert r.status_code == 200, r.text
    assert authed.get("/api/node").json()["state"] == "Stopped"

    assert authed.post("/api/node/connect").status_code == 200
    assert authed.get("/api/node").json()["state"] == "Running"

    actions = [e["action"] for e in authed.get("/api/overview").json()["recent"]]
    assert "node.disconnect" in actions and "node.connect" in actions


def test_exit_node_advertise_and_use(authed, fakes):
    r = authed.post("/api/node/exit-node", json={"advertise": True})
    assert r.status_code == 200
    body = authed.get("/api/node").json()
    assert body["exit_node"]["advertising"] is True

    r = authed.post("/api/node/exit-node", json={"use": "100.84.12.9"})
    assert r.status_code == 200
    assert authed.get("/api/node").json()["exit_node"]["using"] == "100.84.12.9"

    # clearing the selection
    authed.post("/api/node/exit-node", json={"use": ""})
    assert authed.get("/api/node").json()["exit_node"]["using"] == ""


def test_route_advertise_and_withdraw(authed, fakes):
    r = authed.post("/api/node/routes",
                    json={"advertise": ["+10.30.0.0/24", "-10.20.0.0/16"]})
    assert r.status_code == 200, r.text
    routes = [x["route"] for x in authed.get("/api/node").json()["subnet_routes"]]
    assert "10.30.0.0/24" in routes and "10.20.0.0/16" not in routes


def test_route_rejects_garbage_cidr(authed, fakes):
    r = authed.post("/api/node/routes", json={"advertise": ["not-a-cidr"]})
    assert r.status_code == 422


def test_mutations_blocked_while_local_down(authed, fakes):
    from server.api import common

    authed.get("/api/node")  # prime
    fakes["local"].break_()
    stamp, data = common._local_cache._entries["status"]
    common._local_cache._entries["status"] = (stamp - 11, data)
    for call in (
        lambda: authed.post("/api/node/connect"),
        lambda: authed.post("/api/node/disconnect", json={"typed_confirm": "DISCONNECT", "lan_ack": True}),
        lambda: authed.post("/api/node/exit-node", json={"advertise": True}),
        lambda: authed.post("/api/node/routes", json={"advertise": ["+10.30.0.0/24"]}),
    ):
        r = call()
        assert r.status_code == 409, r.text
        assert r.json()["error"]["code"] == "subsystem_unavailable"

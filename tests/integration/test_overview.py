"""US6 — overview endpoint: tiles, recent activity, connect-device helper (T043)."""
from __future__ import annotations

import datetime as dt


def test_tiles_counts(authed):
    body = authed.get("/api/overview").json()
    t = body["tiles"]
    assert t["devices"]["total"] == 6
    assert t["devices"]["online"] == 4
    assert t["node"]["state"] == "Running"
    assert t["services"]["total"] == 4  # incl. the openvpn.service bag-of-config unit
    assert t["services"]["running"] == 2  # openvpn@corp failed, openvpn.service inactive
    # fixture serve config: 443 funnel + 8080 serve (+ drive shares)
    assert t["exposures"]["public"] == 1
    assert t["exposures"]["public_alert"] is True
    assert t["exposures"]["tailnet"] >= 1


def test_public_exposure_in_attention_queue(authed):
    # the seeded funnel must surface as a red queue item (US6 + US8, FR-031)
    body = authed.get("/api/overview").json()
    items = [a for a in body["attention"] if a["code"] == "exposure.public"]
    assert len(items) == 1
    assert items[0]["severity"] == "red"
    assert items[0]["target_href"] == "#/exposures"
    assert items[0]["inline_action"]


def test_policy_errors_absent_when_applied_acl_valid(authed):
    body = authed.get("/api/overview").json()
    assert not [a for a in body["attention"] if a["code"] == "policy.errors"]


def test_profile_tile_counts_and_attention_item(authed, ovpn_factory):
    # import one valid + one expired-cert profile -> 2 total, both enabled
    expired = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)
    files = [("files", ("ok.ovpn", ovpn_factory().encode(), "text/plain")),
             ("files", ("dead.ovpn", ovpn_factory(expires=expired).encode(), "text/plain"))]
    authed.post("/api/profiles/import", files=files)

    body = authed.get("/api/overview").json()
    assert body["tiles"]["profiles"]["total"] == 2
    assert body["tiles"]["profiles"]["enabled"] == 2

    expired = [a for a in body["attention"] if a["code"] == "profile.cert_expired"]
    assert len(expired) == 1
    assert expired[0]["severity"] == "red"
    assert expired[0]["target_label"] == "dead"


def test_unapproved_device_in_queue_and_resolves(authed, fakes):
    body = authed.get("/api/overview").json()
    unapproved = [a for a in body["attention"] if a["code"] == "device.unapproved"]
    assert [a["target_label"] for a in unapproved] == ["nas-server"]

    r = authed.post("/api/devices/9/approve")
    assert r.status_code == 200
    body = authed.get("/api/overview").json()
    assert not [a for a in body["attention"] if a["code"] == "device.unapproved"]


def test_recent_is_last_10_audit_events_desc(authed, ovpn_factory):
    for i in range(3):
        authed.post("/api/profiles/import",
                    files=[("files", (f"p{i}.ovpn", ovpn_factory().encode(), "text/plain"))])
    body = authed.get("/api/overview").json()
    recent = body["recent"]
    assert 3 <= len(recent) <= 10
    stamps = [e["ts"] for e in recent]
    assert stamps == sorted(stamps, reverse=True)
    assert recent[0]["action"].startswith("profile.import")


def test_connect_device_helper_server(authed, fakes):
    r = authed.post("/api/overview/connect-device",
                    json={"os": "linux", "kind": "server"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["key"].startswith("tskey-auth-")
    assert "--authkey=" in body["command"] and body["key"] in body["command"]
    assert "install.sh" in body["command"]  # linux tailoring
    created = fakes["cloud"].created_keys[-1]
    assert created["reusable"] is False    # one-time
    assert created["tags"] == ["tag:server"]
    # audit trail records the key mint
    assert authed.get("/api/overview").json()["recent"][0]["action"] == "device.connect_key"


def test_connect_device_helper_macos_user(authed, fakes):
    r = authed.post("/api/overview/connect-device", json={"os": "macos"})
    body = r.json()
    assert body["key"].startswith("tskey-auth-")
    assert "--authkey=" in body["command"]
    assert "install.sh" not in body["command"]
    created = fakes["cloud"].created_keys[-1]
    assert created["tags"] in (None, [])   # user device: no tag


def test_overview_degrades_when_cloud_down(authed, fakes):
    from server.api import common

    authed.get("/api/overview")  # prime caches
    fakes["cloud"].break_()
    stamp, data = common._cloud_cache._entries["devices"]
    common._cloud_cache._entries["devices"] = (stamp - 61, data)  # force refetch
    body = authed.get("/api/overview").json()
    assert body["tiles"]["devices"]["total"] == 0  # no data, not fake zeros
    assert body["_health"]["tscloud"]["state"] in ("degraded", "unavailable")


# --- owner-requested additions: explicit service rows, IPs, tunnel states ---

def test_vpn_services_rows(authed):
    body = authed.get("/api/overview").json()
    vpn = body["vpn_services"]
    assert vpn["tailscale"]["state"] == "running"   # fake vocabulary
    assert vpn["openvpn"]["state"] == "inactive"    # the bag-of-config unit
    # openvpn@corp is a tunnel unit, not the "openvpn" row — it appears as failed
    assert vpn["openvpn"]["state"] != "failed"


def test_server_ips_from_local_status(authed):
    body = authed.get("/api/overview").json()
    ips = body["ips"]
    assert ips["tailscale"] == "100.84.12.1"        # v4 from FakeLocal.status
    assert "fd7a" not in ips["tailscale"]           # v6 stays on the Node page


def test_tunnel_states_track_unit_instances(authed):
    body = authed.get("/api/overview").json()
    tunnels = {t["name"]: t["state"] for t in body["vpn_services"]["tunnels"]}
    assert isinstance(tunnels, dict)  # imported profiles (none yet) add entries
    # the seeded openvpn@corp unit is not tracked as a profile tunnel
    assert "corp" not in tunnels


def test_tunnel_states_after_profile_import(authed, ovpn_factory):
    authed.post("/api/profiles/import",
                files=[("files", ("corp2.ovpn", ovpn_factory().encode(), "text/plain"))])
    body = authed.get("/api/overview").json()
    tunnels = {t["name"]: t["state"] for t in body["vpn_services"]["tunnels"]}
    assert tunnels["corp2"] == "not-installed"  # no systemd unit for it

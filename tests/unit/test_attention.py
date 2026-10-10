"""US6 — attention derivation (T042, FR-031, data-model AttentionItem)."""
from __future__ import annotations

import datetime as dt

from server.attention import attention_items

NOW = dt.datetime(2026, 10, 10, 12, 0, 0, tzinfo=dt.timezone.utc)


def iso(days_from_now: float) -> str:
    return (NOW + dt.timedelta(days=days_from_now)).strftime("%Y-%m-%dT%H:%M:%SZ")


def device(**over) -> dict:
    d = {"id": "1", "hostname": "box", "key_expiry_state": "valid",
         "authorized": True, "online": True, "last_seen": iso(0)}
    d.update(over)
    return d


def profile(**over) -> dict:
    p = {"id": "p1", "name": "corp", "status": "Valid",
         "cert_expires_at": iso(200), "enabled": True}
    p.update(over)
    return p


def codes(items: list[dict]) -> list[str]:
    return [i["code"] for i in items]


def test_expired_cert_is_red_and_leads_queue():
    items = attention_items(
        profiles=[profile(status="Expired", cert_expires_at=iso(-1)),
                  profile(id="p2", name="home", status="Valid")],
        devices=[device(authorized=False)],
        local_status={"BackendState": "Running"},
        services=[], now=NOW,
    )
    assert codes(items)[0] == "profile.cert_expired"
    assert items[0]["severity"] == "red"
    assert items[0]["target_label"] == "corp"
    assert items[0]["inline_action"]


def test_expiring_cert_is_amber():
    items = attention_items(
        profiles=[profile(status="Expiring", cert_expires_at=iso(10))],
        devices=[], local_status=None, services=[], now=NOW,
    )
    assert codes(items) == ["profile.cert_expiring"]
    assert items[0]["severity"] == "amber"


def test_device_conditions_one_item_most_severe_wins():
    # guest-tablet pattern: key expired AND offline > 7d -> only the red item
    stale_expired = device(key_expiry_state="expired", online=False,
                           last_seen=iso(-30))
    items = attention_items(
        profiles=[], devices=[stale_expired], local_status=None, services=[], now=NOW,
    )
    assert codes(items) == ["device.key_expired"]
    assert items[0]["severity"] == "red"


def test_unapproved_device_has_inline_approve_action():
    items = attention_items(
        profiles=[], devices=[device(id="9", authorized=False)],
        local_status=None, services=[], now=NOW,
    )
    assert codes(items) == ["device.unapproved"]
    action = items[0]["inline_action"]
    assert action["method"] == "POST"
    assert "/api/devices/9/approve" in action["path"]


def test_stale_offline_device_after_7_days():
    items = attention_items(
        profiles=[], devices=[device(online=False, last_seen=iso(-8))],
        local_status=None, services=[], now=NOW,
    )
    assert codes(items) == ["device.stale"]


def test_recently_offline_device_is_not_stale():
    items = attention_items(
        profiles=[], devices=[device(online=False, last_seen=iso(-2))],
        local_status=None, services=[], now=NOW,
    )
    assert items == []


def test_daemon_down_is_red():
    items = attention_items(
        profiles=[], devices=[],
        local_status={"BackendState": "Stopped"}, services=[], now=NOW,
    )
    assert codes(items) == ["node.down"]
    assert items[0]["severity"] == "red"


def test_failed_service_is_red():
    items = attention_items(
        profiles=[], devices=[], local_status=None,
        services=[{"unit": "openvpn@corp.service", "state": "failed"}], now=NOW,
    )
    assert codes(items) == ["service.failed"]
    assert "openvpn@corp" in items[0]["message"]


def test_public_exposure_is_red():
    items = attention_items(
        profiles=[], devices=[], local_status=None, services=[],
        exposures=[{"kind": "funnel", "scope": "public", "name": "grafana"}], now=NOW,
    )
    assert codes(items) == ["exposure.public"]
    assert items[0]["severity"] == "red"


def test_policy_errors_are_amber():
    items = attention_items(
        profiles=[], devices=[], local_status=None, services=[],
        policy_errors=["line 14: unknown group"], now=NOW,
    )
    assert codes(items) == ["policy.errors"]
    assert items[0]["severity"] == "amber"


def test_ordering_severity_then_age():
    items = attention_items(
        profiles=[profile(status="Expiring", cert_expires_at=iso(9)),
                  profile(id="p3", name="old", status="Expired", cert_expires_at=iso(-3))],
        devices=[device(id="d2", hostname="nas-d2", authorized=False, last_seen=iso(-5)),
                 device(id="d3", hostname="nas-d3", authorized=False, last_seen=iso(-1))],
        local_status=None, services=[], now=NOW,
    )
    sev = [i["severity"] for i in items]
    assert sev == ["red", "amber", "amber", "amber"]
    # within severity: oldest problem first
    assert items[0]["target_label"] == "old"           # expired 3d ago (red)
    assert items[1]["target_label"] == "nas-d2"            # unseen 5d ago
    assert items[2]["target_label"] == "nas-d3"            # unseen 1d ago


def test_empty_inputs_no_items():
    assert attention_items(profiles=[], devices=[], local_status=None,
                           services=[], now=NOW) == []


def test_item_shape_contract():
    items = attention_items(
        profiles=[profile(status="Expired", cert_expires_at=iso(-1))],
        devices=[], local_status={"BackendState": "Running"}, services=[], now=NOW,
    )
    for item in items:
        assert set(item) >= {"severity", "code", "message", "target_href",
                             "target_label", "inline_action", "age"}
        assert item["severity"] in ("red", "amber")

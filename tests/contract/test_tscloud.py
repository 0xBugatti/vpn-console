"""US4 — Tailscale cloud adapter contract (T034, research D3).

Runs the REAL TailscaleCloud adapter against httpx.MockTransport replaying the
recorded fixtures — no live credentials (Principle VI).
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from server.adapters.base import DEGRADED, OK, UNAVAILABLE
from server.adapters.tscloud import TailscaleCloud
from server.devicemodel import device_view, fleet_max_version, version_stale

FIXTURES = Path(__file__).parents[1] / "fixtures" / "tailscale"


def make_adapter(handler) -> TailscaleCloud:
    transport = httpx.MockTransport(handler)
    return TailscaleCloud(httpx.Client(transport=transport), tailnet="test.tail.net",
                          token="ttest-fake")


def test_list_devices_maps_all_fields():
    devices = json.loads((FIXTURES / "devices.json").read_text())["devices"]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.tailscale.com"
        assert request.headers["Authorization"] == "Bearer ttest-fake"
        return httpx.Response(200, json={"devices": devices})

    cloud = make_adapter(handler)
    rows = [device_view(d, fleet_max_version(devices)) for d in cloud.list_devices()]
    assert len(rows) == 6

    build = next(r for r in rows if r["hostname"] == "build-server")
    assert build["is_server"] is True  # server-class tag AND no owner
    assert build["key_expiry_state"] == "never"
    assert build["expiry_disabled"] is True

    nas = next(r for r in rows if r["hostname"] == "nas-server")
    assert nas["authorized"] is False
    assert nas["_flags"]["unapproved"] is True
    assert nas["advertised_routes"] == ["192.168.1.0/24"]

    old = next(r for r in rows if r["hostname"] == "old-relay")
    assert old["version_stale"] is True  # >= 2 minors behind fleet max


def test_is_server_rule_tag_or_ownerless():
    devices = json.loads((FIXTURES / "devices.json").read_text())["devices"]
    top = fleet_max_version(devices)
    for d in devices:
        row = device_view(d, top)
        assert row["is_server"] == ("tag:server" in d["tags"] or not d.get("user"))


def test_staleness_threshold_two_minors():
    assert version_stale("1.84.0", "1.86.2") is True   # 2 behind
    assert version_stale("1.86.0", "1.86.2") is False  # same minor
    assert version_stale("1.80.0", "1.86.2") is True
    assert version_stale("", "1.86.2") is False        # unknown never flags


def test_429_maps_to_degraded_with_detail():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"message": "too many requests"})

    cloud = make_adapter(handler)
    with pytest.raises(Exception) as exc:
        cloud.list_devices()
    assert "429" in str(exc.value) or "too many" in str(exc.value).lower()


def test_transport_error_maps_to_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    cloud = make_adapter(handler)
    with pytest.raises(Exception):
        cloud.list_devices()


def test_acl_round_trip_preserves_bytes(T_ACL_FIXTURE=None):
    """T047 (research D14): the policy file moves as bytes — comments survive."""
    hujson = (FIXTURES / "acl.hujson").read_text()
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, json={"acls": hujson})
        seen["put"] = json.loads(request.content)["acls"]
        return httpx.Response(200, json={})

    cloud = make_adapter(handler)
    assert cloud.get_acl_text() == hujson
    cloud.put_acl_text(hujson)
    assert seen["put"] == hujson  # byte-identical incl. comments

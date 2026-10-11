"""US2 — .ovpn parser (T022, research D4, spec edge cases)."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from server import ovpn

FIXTURES = Path(__file__).parents[1] / "fixtures" / "ovpn"


def _load(name: str) -> str:
    return (FIXTURES / name).read_text()


def test_valid_fixture_parses_clean():
    parsed = ovpn.parse(_load("valid.ovpn"))
    assert parsed["parse_error"] is None
    assert parsed["cert_expires_at"].startswith("2033-")
    assert parsed["endpoints"] and parsed["endpoints"][0]["port"] > 0
    assert parsed["cipher"]


def test_expired_cert_extracts_expiry():
    parsed = ovpn.parse(_load("expired.ovpn"))
    assert parsed["parse_error"] is None
    assert parsed["cert_expires_at"].startswith("2020-")
    assert ovpn.derive_status(parsed["cert_expires_at"], True, None) == "Expired"


def test_multi_remote_lists_all_endpoints():
    parsed = ovpn.parse(_load("multi-remote.ovpn"))
    assert len(parsed["endpoints"]) == 3
    hosts = [e["host"] for e in parsed["endpoints"]]
    assert len(set(hosts)) == 3


def test_remote_without_port_defaults_to_1194():
    # real-world configs (e.g. `remote cyber-vpn.allendevaux.net ` with a
    # trailing space) omit the port — OpenVPN defaults it to 1194
    body = "client\ndev tun\nproto udp\nremote gw.example.com \n<cert>\n-----BEGIN CERTIFICATE-----\n"
    parsed = ovpn.parse(body)
    eps = [e for e in parsed["endpoints"] if e["host"] == "gw.example.com"]
    assert eps == [{"host": "gw.example.com", "port": 1194, "proto": None}]


def test_missing_cert_block_reports_reason():
    parsed = ovpn.parse(_load("no-cert.ovpn"))
    assert parsed["parse_error"] == "missing certificate block"
    assert ovpn.derive_status(None, True, parsed["parse_error"]) == "Parse error"


def test_oversize_exceeds_cap():
    raw = (FIXTURES / "oversize.ovpn").read_bytes()
    assert len(raw) > ovpn.MAX_PROFILE_BYTES


def test_no_remote_is_parse_error():
    body = "client\ndev tun\n<cert>\n-----BEGIN CERTIFICATE-----\n"
    parsed = ovpn.parse(body)  # garbage cert + no remote
    assert parsed["parse_error"]


def test_status_derivation_matrix(ovpn_factory):
    soon = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=7)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    assert ovpn.derive_status(soon, True, None) == "Expiring"
    assert ovpn.derive_status(None, True, None) == "Valid"  # user-pass only
    assert ovpn.derive_status(None, False, None) == "Disabled"
    assert ovpn.derive_status(None, True, "boom") == "Parse error"


def test_factory_generates_parseable_body(ovpn_factory):
    parsed = ovpn.parse(ovpn_factory(cn="factory-check", cipher="AES-128-GCM"))
    assert parsed["parse_error"] is None
    assert parsed["cipher"] == "AES-128-GCM"
    assert parsed["has_auth_user_pass"] is False


def test_sha256_differs_per_body(ovpn_factory):
    a = ovpn.parse(ovpn_factory(cn="a"))
    b = ovpn.parse(ovpn_factory(cn="b"))
    assert a["config_sha256"] != b["config_sha256"]

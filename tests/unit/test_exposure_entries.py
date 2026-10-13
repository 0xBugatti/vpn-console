"""Exposure rows built from tailscaled's REAL shapes.

The first console version parsed an invented wrapper ({"Version","Config"}) and fields
that do not exist (ServeURL, MustAcceptTLS), so on a real host the list was always empty
while adds worked. These tests pin the captured real outputs (tests/fixtures/cli/real/,
tailscale v1.104.1) and the shapes documented in tailscale ipn/serve.go.
"""
from __future__ import annotations

import json
from pathlib import Path

from server.api.exposures import _entries

REAL = Path(__file__).parents[1] / "fixtures" / "cli" / "real"
HOST = "0xbugatti-vps-1.dwelf-nase.ts.net"


def real(name: str):
    return json.loads((REAL / name).read_text())


def test_real_http_serve_is_listed():
    rows = _entries(real("serve-http.json"), [])
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == "tcp-18080" and row["port"] == 18080
    assert row["kind"] == "serve" and row["scope"] == "tailnet"
    assert row["source"] == f"http://{HOST}:18080"
    assert row["target"] == "proxy → http://127.0.0.1:9"
    assert row["raw_target"] == "http://127.0.0.1:9"
    assert row["tls"] is False and row["enabled"] is True


def test_real_drive_share_is_listed_by_name():
    rows = _entries({}, real("drive-shares.json"))
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == "drive-consoletest" and row["name"] == "consoletest"
    assert row["kind"] == "taildrive" and row["scope"] == "share"
    assert row["source"] == "/tmp/console-drive-test"


def test_nothing_configured_is_an_empty_list_not_an_error():
    # tailscaled prints {} for serve and answers null (read as []) for shares
    assert _entries({}, []) == []
    assert _entries({}, None) == []


def test_https_funnel_per_ipn_serve_go():
    # Funnel exposes the public internet, so this shape is built from ipn/serve.go, not captured
    cfg = {
        "TCP": {"443": {"HTTPS": True}},
        "Web": {f"{HOST}:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:3000"}}}},
        "AllowFunnel": {f"{HOST}:443": True},
    }
    row = _entries(cfg, [])[0]
    assert row["kind"] == "funnel" and row["scope"] == "public"
    assert row["tls"] is True
    assert row["source"] == f"https://{HOST}"  # default port is not repeated


def test_https_on_a_non_default_port_keeps_the_port():
    cfg = {
        "TCP": {"8443": {"HTTPS": True}},
        "Web": {f"{HOST}:8443": {"Handlers": {"/": {"Path": "/srv/www"}}}},
    }
    row = _entries(cfg, [])[0]
    assert row["source"] == f"https://{HOST}:8443"
    assert row["target"] == "path /srv/www" and row["kind"] == "serve"


def test_funnel_allowance_only_counts_for_the_exact_host_and_port():
    cfg = {
        "TCP": {"8080": {"HTTP": True}},
        "Web": {f"{HOST}:8080": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:1"}}}},
        "AllowFunnel": {"other.example.com:8080": True},
    }
    assert _entries(cfg, [])[0]["kind"] == "serve"


def test_extra_mount_points_are_counted_not_hidden():
    cfg = {
        "TCP": {"18080": {"HTTP": True}},
        "Web": {f"{HOST}:18080": {"Handlers": {
            "/": {"Proxy": "http://127.0.0.1:1"}, "/docs": {"Path": "/srv/docs"}, "/x": {"Text": "x"}}}},
    }
    assert _entries(cfg, [])[0]["target"].endswith("(+2 more paths)")


def test_raw_tcp_forward_is_shown_and_flagged():
    cfg = {"TCP": {"2222": {"TCPForward": "127.0.0.1:22"}}}
    row = _entries(cfg, [])[0]
    assert row["tcp_forward"] is True and row["target"] == "tcp → 127.0.0.1:22"
    assert row["source"].startswith("tcp://") and row["kind"] == "serve"


def test_the_invented_wrapper_is_not_the_contract():
    # the old fixtures wrapped the config; tailscale never did
    wrapped = {"Version": "3", "Config": real("serve-http.json")}
    assert _entries(wrapped, []) == []

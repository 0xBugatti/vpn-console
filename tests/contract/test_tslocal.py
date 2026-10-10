"""US8 — local adapter contract (T052, research D1/D2).

Drives the REAL TailscaleLocal adapter with fixture JSON fed through stubbed
transport, then proves the missing-socket path reports unavailable — no live
tailscaled needed (Principle VI).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.adapters.tslocal import TailscaleLocal

FIXTURES = Path(__file__).parents[1] / "fixtures" / "cli"


def make_local(socket_path: str | None = "/fake/tailscaled.socket") -> TailscaleLocal:
    return TailscaleLocal(socket_path=socket_path, cli="true")


def test_status_and_prefs_map_from_localapi(monkeypatch):
    local = make_local()
    status_fx = json.loads((FIXTURES / "status.json").read_text())
    prefs_fx = json.loads((FIXTURES / "prefs.json").read_text())
    monkeypatch.setattr(local, "_socket_http",
                        lambda method, path, body=None: status_fx if "status" in path else prefs_fx)
    assert local.status()["BackendState"] == "Running"
    assert local.status()["TailscaleIPs"][0] == "100.84.12.1"
    assert local.prefs()["AdvertiseRoutes"] == ["10.20.0.0/16"]
    assert local.prefs()["ExitNodeIP"] == ""  # not using an exit node


def test_serve_and_drive_json_from_cli(monkeypatch):
    local = make_local()
    serve_fx = json.loads((FIXTURES / "serve-status.json").read_text())
    drive_fx = json.loads((FIXTURES / "drive-status.json").read_text())
    monkeypatch.setattr(local, "_cli_json",
                        lambda *args: serve_fx if args[0] == "serve" else drive_fx)
    cfg = local.serve_status()["Config"]
    assert "443" in cfg["TCP"]
    shares = local.drive_status()["Config"]["Shares"]
    assert "/photos" in shares


def test_cli_mutations_build_expected_args(monkeypatch):
    local = make_local()
    calls: list[tuple] = []
    monkeypatch.setattr(local, "_cli", lambda *args: calls.append(args) or "")
    local.connect()
    local.disconnect()
    local.set_exit_node(use="100.84.12.9", advertise_exit=True)
    local.set_exit_node(use="", advertise_exit=False)
    local.set_advertised_routes(["10.30.0.0/24", "0.0.0.0/0"])
    local.serve_add(443, "http://127.0.0.1:3000", scheme="https", funnel=True)
    local.serve_add(8080, "http://127.0.0.1:5000", scheme="http")
    local.serve_off(443, scheme="https", funnel=True)
    local.serve_off(8080, scheme="http")
    local.drive_remove("/photos")
    assert calls[0] == ("up",)
    assert calls[1] == ("down",)
    assert calls[2] == ("set", "--exit-node=100.84.12.9", "--advertise-exit-node=true")
    assert calls[3] == ("set", "--exit-node=", "--advertise-exit-node=false")
    assert calls[4] == ("set", "--advertise-routes=10.30.0.0/24,0.0.0.0/0")
    assert calls[5] == ("funnel", "--bg", "--https=443", "http://127.0.0.1:3000")
    assert calls[6] == ("serve", "--bg", "--http=8080", "http://127.0.0.1:5000")
    assert calls[7] == ("funnel", "--bg", "--https=443", "off")
    assert calls[8] == ("serve", "--bg", "--http=8080", "off")
    assert calls[9] == ("drive", "share", "remove", "/photos")


def test_missing_socket_is_a_loud_unavailable(tmp_path):
    local = TailscaleLocal(socket_path=str(tmp_path / "does-not-exist.socket"), cli="true")
    with pytest.raises(FileNotFoundError):
        local.status()

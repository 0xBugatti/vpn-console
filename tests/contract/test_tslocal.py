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


def test_serve_status_is_the_bare_config_tailscale_prints(monkeypatch):
    """`tailscale serve status --json` prints the ServeConfig itself, with no wrapper."""
    local = make_local()
    real = json.loads((FIXTURES / "real" / "serve-http.json").read_text())  # captured live, v1.104.1
    monkeypatch.setattr(local, "_cli_json", lambda *args: real)
    cfg = local.serve_status()
    assert cfg["TCP"]["18080"] == {"HTTP": True}
    assert cfg["Web"]["0xbugatti-vps-1.dwelf-nase.ts.net:18080"]["Handlers"]["/"] == {"Proxy": "http://127.0.0.1:9"}


def test_drive_shares_come_from_the_local_api_not_a_cli_status(monkeypatch):
    """There is no `tailscale drive status`: shares are read from /localapi/v0/drive/shares,
    and tailscaled answers `null` when nothing is shared."""
    local = make_local()
    seen: list[tuple] = []
    real = json.loads((FIXTURES / "real" / "drive-shares.json").read_text())  # captured live
    monkeypatch.setattr(local, "_socket_http",
                        lambda method, path, body=None: seen.append((method, path)) or real)
    assert local.drive_shares() == [{"name": "consoletest", "path": "/tmp/console-drive-test", "who": "root"}]
    assert seen == [("GET", "/localapi/v0/drive/shares")]
    monkeypatch.setattr(local, "_socket_http", lambda *a, **k: None)  # nothing shared
    assert local.drive_shares() == []


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
    local.drive_remove("photos")
    assert calls[0] == ("up",)
    assert calls[1] == ("down",)
    assert calls[2] == ("set", "--exit-node=100.84.12.9", "--advertise-exit-node=true")
    assert calls[3] == ("set", "--exit-node=", "--advertise-exit-node=false")
    assert calls[4] == ("set", "--advertise-routes=10.30.0.0/24,0.0.0.0/0")
    assert calls[5] == ("funnel", "--bg", "--https=443", "http://127.0.0.1:3000")
    assert calls[6] == ("serve", "--bg", "--http=8080", "http://127.0.0.1:5000")
    assert calls[7] == ("funnel", "--bg", "--https=443", "off")
    assert calls[8] == ("serve", "--bg", "--http=8080", "off")
    # by NAME: `drive share remove <path>` would add a share called "remove"
    assert calls[9] == ("drive", "unshare", "photos")


def test_missing_socket_is_a_loud_unavailable(tmp_path):
    local = TailscaleLocal(socket_path=str(tmp_path / "does-not-exist.socket"), cli="true")
    with pytest.raises(FileNotFoundError):
        local.status()

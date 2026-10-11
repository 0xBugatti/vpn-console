"""US9 — host adapter contract (T057, research D2).

Drives the REAL HostControl with fixture systemctl/journalctl/ss output fed
through a stubbed _run, then proves absent mounts are a loud FileNotFoundError
(FR-053) — no live systemd needed (Principle VI).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from server.adapters import host as hostmod
from server.adapters.host import HostControl

FIXTURES = Path(__file__).parents[1] / "fixtures" / "host"


def fx(name: str) -> str:
    return (FIXTURES / name).read_text()


def make_host(monkeypatch, outputs: dict[str, str]) -> HostControl:
    """HostControl whose _run serves fixture text keyed by the first CLI word.

    `systemctl show <unit>` gets a per-unit answer: the real fixture for
    tailscaled, a synthetic disabled/failed block for the other template units.
    """
    ctl = HostControl(systemctl="systemctl", journalctl="journalctl", ss="ss")
    calls: list[list[str]] = []

    def fake_run(cmd, timeout=30):
        calls.append(cmd)
        if "show" in cmd:
            unit = cmd[cmd.index("show") + 1]
            if unit == "tailscaled.service":
                return fx("show-tailscaled.txt")
            return (f"Id={unit}\nDescription=synthetic unit\n"
                    "ActiveState=active\nSubState=running\nUnitFileState=disabled\n"
                    "ExecMainStartTimestamp=Sun 2026-10-05 22:01:09 UTC\nResult=exit-code\n")
        for key, text in outputs.items():
            if key in cmd:
                return text
        raise AssertionError(f"unexpected command {cmd}")

    monkeypatch.setattr(ctl, "_run", fake_run)
    ctl.calls = calls  # type: ignore[attr-defined]
    return ctl


def test_unit_state_maps_systemctl_show(monkeypatch):
    ctl = make_host(monkeypatch, {"show": fx("show-tailscaled.txt")})
    state = ctl.unit_state("tailscaled.service")
    assert state == {
        "unit": "tailscaled.service",
        "description": "Tailscale node agent",
        "state": "active",
        "sub_state": "running",
        "enabled_on_boot": True,
        "since": "Mon 2026-09-28 04:12:33 UTC",
        "result": "success",
    }


def test_units_lists_the_allowed_set(monkeypatch):
    ctl = make_host(monkeypatch, {
        "list-units": fx("list-units.txt"),
        "show": fx("show-tailscaled.txt"),
    })
    units = ctl.units()
    assert [u["unit"] for u in units] == [
        "openvpn@corp.service", "tailscaled.service", "vpn-console.service",
    ]


def test_journal_maps_json_and_passes_filters(monkeypatch):
    ctl = make_host(monkeypatch, {"journalctl": fx("journal.jsonl")})
    entries = ctl.journal("tailscaled.service", severity=3, text="retry", limit=50)
    cmd = ctl.calls[0]
    assert "--priority=0..3" in cmd and "--lines=50" in cmd and "-u" in cmd
    # text filter is applied server-side on the mapped messages
    assert [e["msg"] for e in entries] == ["control: retry in 30s"]
    assert entries[0]["prio"] == 4 and entries[0]["cursor"] == "c3"

    everything = ctl.journal("tailscaled.service")
    assert len(everything) == 4


def test_journal_cursor_is_passed_through(monkeypatch):
    """Resume semantics belong to journalctl --after-cursor; the adapter builds args."""
    ctl = make_host(monkeypatch, {"journalctl": fx("journal.jsonl")})
    ctl.journal("tailscaled.service", after_cursor="c2")
    assert "--after-cursor=c2" in ctl.calls[0]


def test_ss_parses_listening_ports(monkeypatch):
    ctl = make_host(monkeypatch, {"ss": fx("ss.txt")})
    ports = ctl.listening_ports()
    assert [(p["proto"], p["port"], p["process"]) for p in ports] == [
        ("udp", 41641, "tailscaled"),
        ("tcp", 22, "sshd"),        # duplicate (proto, port) row is dropped
        ("tcp", 3000, "grafana"),
    ]


def test_unit_action_allow_list(monkeypatch):
    ctl = make_host(monkeypatch, {"restart": "", "start": "", "stop": ""})
    assert ctl.unit_action("tailscaled.service", "restart") == "restart:tailscaled.service"
    assert ctl.unit_action("openvpn@corp.service", "restart") == "restart:openvpn@corp.service"
    with pytest.raises(PermissionError):
        ctl.unit_action("docker.service", "stop")
    with pytest.raises(ValueError):
        ctl.unit_action("tailscaled.service", "reboot")


def test_unit_allowed_patterns():
    assert hostmod.unit_allowed("tailscaled.service")
    assert hostmod.unit_allowed("openvpn@corp.service")
    assert hostmod.unit_allowed("openvpn.service")  # the bag-of-config unit (overview)
    assert hostmod.unit_allowed("openvpn-client@corp.service")  # per-profile tunnels
    assert not hostmod.unit_allowed("openvpn-server@corp.service")
    assert not hostmod.unit_allowed("docker.service")


def test_missing_mounts_are_a_loud_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(hostmod, "SYSTEMD_SOCKET", str(tmp_path / "no.sock"))
    monkeypatch.setattr(hostmod, "JOURNAL_DIRS", [str(tmp_path / "no-journal")])
    ctl = HostControl(systemctl="systemctl", journalctl="journalctl", ss="ss")
    with pytest.raises(FileNotFoundError):
        ctl.units()
    with pytest.raises(FileNotFoundError):
        ctl.journal("tailscaled.service")


def test_interfaces_filters_tunnel_prefixes(monkeypatch, tmp_path):
    # fake /sys/class/net: tun0/tap1/wg0 qualify, eth0/docker0/veth never do
    for name in ("tun0", "tap1", "wg0", "eth0", "docker0", "vethabc123"):
        (tmp_path / name).touch()
    monkeypatch.setattr(hostmod, "NET_CLASS_DIR", tmp_path)
    monkeypatch.setattr(hostmod, "_interface_ipv4",
                        lambda n: {"tun0": "10.233.2.74", "wg0": "10.9.0.1"}.get(n, ""))
    out = hostmod.HostControl().interfaces()
    assert out == [{"iface": "tun0", "addr": "10.233.2.74"},
                   {"iface": "wg0", "addr": "10.9.0.1"}]


def test_interfaces_empty_when_net_class_missing(monkeypatch):
    monkeypatch.setattr(hostmod, "NET_CLASS_DIR", Path("/nonexistent/net/class"))
    assert hostmod.HostControl().interfaces() == []

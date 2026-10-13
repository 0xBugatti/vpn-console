"""Server tunnels: Enable starts a profile's tunnel, Disable stops it (owner request, 2026-10-12).

Run against the fake host: the same API, jobs and safety rules, no real systemd or network.
"""
from __future__ import annotations

import datetime as dt
import time

import pytest

from server import tunnels
from server.api import tunnelctl

ENABLE = {"enabled": True, "confirm": True}
DISABLE = {"enabled": False, "confirm": True}


@pytest.fixture(autouse=True)
def fast_jobs(monkeypatch):
    monkeypatch.setattr(tunnelctl, "POLL_SECONDS", 0)
    monkeypatch.setattr(tunnelctl, "WAIT_SECONDS", 2)


def add(authed, ovpn_factory, name="corp", extra="", **kw) -> str:
    text = ovpn_factory(cn=name, **kw) + extra
    r = authed.post("/api/profiles/import", files=[("files", (f"{name}.ovpn", text.encode(), "text/plain"))])
    assert r.status_code == 200, r.text
    return r.json()["results"][0]["id"]


def wait(authed, job_id: str) -> dict:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        job = authed.get(f"/api/jobs/{job_id}").json()
        if job["done"]:
            return job
        time.sleep(0.01)
    raise AssertionError("job never finished")


def until(check, timeout: float = 5.0) -> None:
    """Wait for something a worker thread does (an undo that restarts a tunnel has no job id)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.01)
    raise AssertionError("the expected change never happened")


def state(authed, pid: str) -> dict:
    return authed.get(f"/api/profiles/{pid}").json()["tunnel"]


def enable(authed, pid: str, **extra) -> dict:
    r = authed.patch(f"/api/profiles/{pid}", json={**ENABLE, **extra})
    assert r.status_code == 200, r.text
    return wait(authed, r.json()["job_id"])


def audit(authed, action: str) -> list[dict]:
    rows = authed.get("/api/audit?limit=200").json()["entries"]
    return [e for e in rows if e["action"] == action]


# ----------------------------------------------------------------------------- Enable

def test_nothing_starts_when_the_console_starts(authed, fakes):
    assert fakes["host"].action_log == [] and fakes["host"].tunnel_files == {}


def test_enable_needs_a_confirm_and_installs_nothing_without_it(authed, ovpn_factory, fakes):
    pid = add(authed, ovpn_factory)
    r = authed.patch(f"/api/profiles/{pid}", json={"enabled": True})
    assert r.status_code == 409 and r.json()["error"]["code"] == "confirm_required"
    assert fakes["host"].tunnel_files == {} and fakes["host"].action_log == []


def test_enable_installs_the_tunnel_only_copy_starts_it_and_reports_the_ip(authed, ovpn_factory, fakes):
    pid = add(authed, ovpn_factory, name="vps-cybervpn")
    job = enable(authed, pid)
    assert job["ok"] is True and job["state"] == "connected" and job["ip"] == "10.200.0.2"

    host = fakes["host"]
    conf = host.tunnel_files["vps-cybervpn"]
    assert conf.startswith(f"# vpn-console-managed profile={pid}\n")
    iface = tunnels.iface_name(pid)
    assert f"dev {iface}" in conf.splitlines() and 'pull-filter ignore "redirect-gateway"' in conf
    unit = "openvpn-client@vps-cybervpn.service"
    assert host.units_data[unit]["enabled_on_boot"] is True          # starts on boot, as chosen
    assert ("openvpn-client@vps-cybervpn.service", "enable") in host.action_log

    t = state(authed, pid)
    assert t["state"] == "connected" and t["ip"] == "10.200.0.2" and t["unit"] == unit
    p = authed.get(f"/api/profiles/{pid}").json()
    assert p["enabled"] is True
    assert audit(authed, "profile.enable")[0]["outcome"] == "ok"


def test_overview_shows_the_console_tunnel_by_profile_name(authed, ovpn_factory):
    pid = add(authed, ovpn_factory, name="vps-cybervpn")
    enable(authed, pid)
    body = authed.get("/api/overview").json()
    row = next(t for t in body["vpn_services"]["tunnels"] if t["id"] == pid)
    assert row["state"] == "up" and row["unit"] == "openvpn-client@vps-cybervpn.service"
    ip = next(i for i in body["ips"]["openvpn"] if i["iface"] == tunnels.iface_name(pid))
    assert ip["addr"] == "10.200.0.2" and ip["profile"] == "vps-cybervpn"


def test_enabling_a_running_tunnel_does_nothing_twice(authed, ovpn_factory, fakes):
    pid = add(authed, ovpn_factory)
    enable(authed, pid)
    before = list(fakes["host"].action_log)
    r = authed.patch(f"/api/profiles/{pid}", json=ENABLE)
    assert r.status_code == 200 and r.json()["job_id"] is None
    assert fakes["host"].action_log == before


def test_unit_names_are_safe_for_odd_profile_names(authed, ovpn_factory, fakes):
    pid = add(authed, ovpn_factory, name="My VPN (home)")  # import turns the brackets into "_"
    enable(authed, pid)
    assert state(authed, pid)["unit"] == "openvpn-client@My-VPN-_home_.service"
    assert "My-VPN-_home_" in fakes["host"].tunnel_files


# ------------------------------------------------------------------- refused profiles

def test_a_profile_needing_a_password_is_refused_with_the_line(authed, ovpn_factory, fakes):
    pid = add(authed, ovpn_factory, extra="\nauth-user-pass\n")
    r = authed.patch(f"/api/profiles/{pid}", json=ENABLE)
    assert r.status_code == 422 and r.json()["error"]["code"] == "tunnel_refused"
    assert r.json()["error"]["detail"]["findings"][0]["directive"] == "auth-user-pass"
    assert fakes["host"].tunnel_files == {} and fakes["host"].action_log == []


def test_an_expired_certificate_is_refused(authed, ovpn_factory):
    old = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=3)
    pid = add(authed, ovpn_factory, name="lapsed", expires=old)
    r = authed.patch(f"/api/profiles/{pid}", json=ENABLE)
    assert r.status_code == 422 and "expired" in r.json()["error"]["message"]


def test_a_profile_that_does_not_parse_is_refused(authed):
    r = authed.post("/api/profiles/import", files=[("files", ("broken.ovpn", b"client\ndev tun\n", "text/plain"))])
    pid = r.json()["results"][0]["id"]
    assert authed.patch(f"/api/profiles/{pid}", json=ENABLE).status_code == 422


def test_enable_explains_when_the_tunnel_folder_is_not_mounted(authed, ovpn_factory, fakes):
    fakes["host"].tunnel_dir_ok = False
    pid = add(authed, ovpn_factory)
    r = authed.patch(f"/api/profiles/{pid}", json=ENABLE)
    assert r.status_code == 409 and r.json()["error"]["code"] == "tunnel_unavailable"


def test_a_config_the_console_did_not_write_is_never_overwritten(authed, ovpn_factory, fakes):
    fakes["host"].tunnel_files["corp"] = "client\nremote hand-made.example 1194\n"
    pid = add(authed, ovpn_factory, name="corp")
    r = authed.patch(f"/api/profiles/{pid}", json=ENABLE)
    assert r.status_code == 409 and r.json()["error"]["code"] == "tunnel_name_taken"
    assert fakes["host"].tunnel_files["corp"].startswith("client\nremote hand-made")


def test_two_profiles_cannot_share_one_tunnel_name(authed, ovpn_factory, fakes):
    first = add(authed, ovpn_factory, name="my vpn")
    enable(authed, first)
    # a different profile name that reduces to the same unit name ("my-vpn")
    second = add(authed, ovpn_factory, name="my-vpn", remotes=(("other.example.net", "1194", "udp"),))
    r = authed.patch(f"/api/profiles/{second}", json=ENABLE)
    assert r.status_code == 409 and r.json()["error"]["code"] == "tunnel_name_taken"
    assert fakes["host"].tunnel_files["my-vpn"].startswith(f"# vpn-console-managed profile={first}\n")


def test_a_leftover_copy_of_a_deleted_profile_can_be_taken_over_unless_it_still_runs(authed, ovpn_factory, fakes):
    old = add(authed, ovpn_factory, name="corp")
    enable(authed, old)
    authed.request("DELETE", f"/api/profiles/{old}", json={"confirm": True})  # tunnel and copy stay
    again = add(authed, ovpn_factory, name="corp", remotes=(("other.example.net", "1194", "udp"),))
    r = authed.patch(f"/api/profiles/{again}", json=ENABLE)
    assert r.status_code == 409 and "still running" in r.json()["error"]["message"]
    stopped = authed.post("/api/services/openvpn-client@corp.service/stop", json={"confirm": True})
    assert wait(authed, stopped.json()["job_id"])["ok"] is True
    assert authed.patch(f"/api/profiles/{again}", json=ENABLE).status_code == 200


# ------------------------------------------------------------------------- scripts

def test_script_lines_need_the_profile_name_typed(authed, ovpn_factory, fakes):
    pid = add(authed, ovpn_factory, name="scripted", extra="\nscript-security 2\nup /etc/openvpn/up.sh\n")
    r = authed.patch(f"/api/profiles/{pid}", json=ENABLE)  # a plain confirm is not enough
    assert r.status_code == 409 and r.json()["error"]["code"] == "typed_confirm_required"
    assert fakes["host"].tunnel_files == {}
    job = enable(authed, pid, typed_confirm="scripted")
    assert job["ok"] is True
    conf = fakes["host"].tunnel_files["scripted"].splitlines()
    assert "up /etc/openvpn/up.sh" in conf and "script-security 1" not in conf


def test_the_plan_lists_what_enable_would_do(authed, ovpn_factory):
    extra = "\nup /x\nredirect-gateway def1\nlog /var/log/x\nca /root/ca.crt\n"
    pid = add(authed, ovpn_factory, extra=extra)
    plan = authed.get(f"/api/profiles/{pid}/tunnel").json()["plan"]
    assert plan["needs_typed_confirm"] is True and plan["available"] is True
    assert [f["directive"] for f in plan["scripts"]] == ["up"]
    assert [f["directive"] for f in plan["default_route"]] == ["redirect-gateway"]
    assert [f["directive"] for f in plan["stripped"]] == ["log"]
    assert [f["directive"] for f in plan["refused"]] == ["ca"]
    assert plan["instance"] == "corp" and plan["iface"].startswith("vc-")


# --------------------------------------------------------------------- safety guard

def test_a_tunnel_that_replaces_the_default_route_is_stopped_and_disabled(authed, ovpn_factory, fakes):
    fakes["host"].tunnel_routes = ["0.0.0.0/1", "128.0.0.0/1"]  # as if the pull-filter had been bypassed
    pid = add(authed, ovpn_factory)
    job = enable(authed, pid)
    assert job["ok"] is False and job["state"] == "guard" and "default route" in job["detail"]
    assert state(authed, pid)["state"] == "stopped"
    assert authed.get(f"/api/profiles/{pid}").json()["enabled"] is False
    assert fakes["host"].units_data["openvpn-client@corp.service"]["enabled_on_boot"] is False
    assert audit(authed, "profile.enable")[0]["outcome"] == "failed"


def test_a_tunnel_may_not_take_traffic_from_a_tunnel_started_by_hand(authed, ovpn_factory, fakes):
    fakes["host"].routes_data.append({"dest": "10.112.0.0/12", "iface": "tun0", "gateway": ""})  # your lab
    fakes["host"].tunnel_routes = ["10.112.4.0/24"]
    pid = add(authed, ovpn_factory)
    job = enable(authed, pid)
    assert job["state"] == "guard" and "10.112.0.0/12" in job["detail"] and "tun0" in job["detail"]
    assert any(r["iface"] == "tun0" for r in fakes["host"].routes_data)  # the lab route is untouched


def test_a_tunnel_that_never_connects_reports_the_log(authed, ovpn_factory, fakes):
    fakes["host"].tunnel_outcome = "failed"
    fakes["host"].journal_entries = [
        {"ts": "1", "prio": 6, "msg": "OpenVPN 2.7.3 starting", "cursor": "a"},
        {"ts": "2", "prio": 3, "msg": "TLS key negotiation failed to occur within 60 seconds", "cursor": "b"},
    ]
    pid = add(authed, ovpn_factory)
    job = enable(authed, pid)
    assert job["ok"] is False and job["state"] == "failed" and "TLS key negotiation failed" in job["detail"]
    assert state(authed, pid)["state"] == "failed"
    assert authed.get(f"/api/profiles/{pid}").json()["enabled"] is True  # still wanted; Disable turns it off


def test_a_server_that_has_not_answered_yet_is_reported_as_still_connecting(authed, ovpn_factory, fakes):
    fakes["host"].tunnel_outcome = "activating"
    pid = add(authed, ovpn_factory)
    job = enable(authed, pid)
    assert job["ok"] is False and job["state"] == "connecting"
    assert state(authed, pid)["state"] == "connecting"


# ------------------------------------------------------------------------ Disable

def test_disable_stops_the_tunnel_and_turns_boot_start_off(authed, ovpn_factory, fakes):
    pid = add(authed, ovpn_factory)
    enable(authed, pid)
    r = authed.patch(f"/api/profiles/{pid}", json={"enabled": False})  # stopping a live tunnel asks first
    assert r.status_code == 409 and r.json()["error"]["code"] == "confirm_required"
    assert state(authed, pid)["state"] == "connected"

    r = authed.patch(f"/api/profiles/{pid}", json=DISABLE)
    assert r.status_code == 200 and r.json()["undo_token"] is None
    assert wait(authed, r.json()["job_id"])["ok"] is True
    host = fakes["host"]
    assert state(authed, pid)["state"] == "stopped"
    assert host.units_data["openvpn-client@corp.service"]["enabled_on_boot"] is False
    assert not any(i["iface"] == tunnels.iface_name(pid) for i in host.interfaces_data)
    assert authed.get(f"/api/profiles/{pid}").json()["enabled"] is False
    assert audit(authed, "profile.disable")[0]["outcome"] == "ok"
    assert "corp" in host.tunnel_files  # the installed copy stays


def test_enable_again_after_disable_starts_it_again(authed, ovpn_factory):
    pid = add(authed, ovpn_factory)
    enable(authed, pid)
    r = authed.patch(f"/api/profiles/{pid}", json=DISABLE)
    wait(authed, r.json()["job_id"])
    assert enable(authed, pid)["state"] == "connected"


# --------------------------------------------------------------------------- Edit

def edit(authed, pid: str, text: str, **extra):
    return authed.patch(f"/api/profiles/{pid}", json={"config_text": text, **extra})


def test_edit_of_a_running_tunnel_asks_first_then_rewrites_and_restarts(authed, ovpn_factory, fakes):
    pid = add(authed, ovpn_factory, name="corp")
    enable(authed, pid)
    new_text = ovpn_factory(cn="corp-v2")
    r = edit(authed, pid, new_text)
    assert r.status_code == 409 and r.json()["error"]["code"] == "confirm_required"
    assert authed.get(f"/api/profiles/{pid}").json()["config_text"] != new_text  # nothing saved yet

    r = edit(authed, pid, new_text, confirm=True)
    assert r.status_code == 200 and r.json()["tunnel_sync"]["applied"] is True
    assert wait(authed, r.json()["job_id"])["ok"] is True
    assert ("openvpn-client@corp.service", "restart") in fakes["host"].action_log
    assert new_text.strip().splitlines()[-1] in fakes["host"].tunnel_files["corp"]
    assert audit(authed, "profile.restart")[0]["outcome"] == "ok"


def test_undoing_an_edit_puts_the_old_config_back_on_the_server_too(authed, ovpn_factory, fakes):
    original = ovpn_factory(cn="corp")
    pid = authed.post("/api/profiles/import", files=[("files", ("corp.ovpn", original.encode(), "text/plain"))]).json()["results"][0]["id"]
    enable(authed, pid)
    r = edit(authed, pid, ovpn_factory(cn="corp-v2"), confirm=True)
    wait(authed, r.json()["job_id"])
    restarts = lambda: fakes["host"].action_log.count(("openvpn-client@corp.service", "restart"))  # noqa: E731
    before = restarts()
    assert authed.post(f"/api/undo/{r.json()['undo_token']}").status_code == 200
    assert authed.get(f"/api/profiles/{pid}").json()["config_text"] == original
    assert original.strip().splitlines()[-1] in fakes["host"].tunnel_files["corp"]
    until(lambda: restarts() == before + 1)  # the undo restarts the tunnel on its worker thread


def test_an_edit_that_adds_scripts_is_saved_but_not_applied(authed, ovpn_factory, fakes):
    pid = add(authed, ovpn_factory)
    enable(authed, pid)
    installed = fakes["host"].tunnel_files["corp"]
    text = authed.get(f"/api/profiles/{pid}").json()["config_text"] + "\nscript-security 2\nup /x\n"
    r = edit(authed, pid, text, confirm=True)
    assert r.status_code == 200
    assert r.json()["tunnel_sync"]["applied"] is False and "Disable and Enable" in r.json()["tunnel_sync"]["reason"]
    assert r.json()["job_id"] is None
    assert fakes["host"].tunnel_files["corp"] == installed          # the running copy is untouched
    assert authed.get(f"/api/profiles/{pid}").json()["config_text"] == text  # but the profile is saved


def test_an_edit_that_cannot_run_unattended_is_saved_but_not_applied(authed, ovpn_factory, fakes):
    pid = add(authed, ovpn_factory)
    enable(authed, pid)
    installed = fakes["host"].tunnel_files["corp"]
    text = authed.get(f"/api/profiles/{pid}").json()["config_text"] + "\nauth-user-pass\n"
    r = edit(authed, pid, text, confirm=True)
    assert r.json()["tunnel_sync"]["applied"] is False and fakes["host"].tunnel_files["corp"] == installed


def test_edit_of_a_profile_with_no_tunnel_only_saves_it(authed, ovpn_factory, fakes):
    pid = add(authed, ovpn_factory)
    r = edit(authed, pid, ovpn_factory(cn="other"))
    assert r.status_code == 200 and r.json()["tunnel_sync"]["applied"] is None and r.json()["job_id"] is None
    assert fakes["host"].tunnel_files == {}


def test_reverting_a_running_tunnels_profile_asks_first(authed, ovpn_factory, fakes):
    pid = add(authed, ovpn_factory)
    enable(authed, pid)
    edit(authed, pid, ovpn_factory(cn="v2"), confirm=True)
    r = authed.post(f"/api/profiles/{pid}/revert")
    assert r.status_code == 409 and r.json()["error"]["code"] == "confirm_required"
    r = authed.post(f"/api/profiles/{pid}/revert", json={"confirm": True})
    assert r.status_code == 200 and wait(authed, r.json()["job_id"])["ok"] is True


# ------------------------------------------------------------------ Rename / Delete

def test_rename_is_blocked_while_enabled(authed, ovpn_factory):
    pid = add(authed, ovpn_factory)
    enable(authed, pid)
    r = authed.patch(f"/api/profiles/{pid}", json={"name": "renamed"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "rename_blocked"
    r = authed.patch(f"/api/profiles/{pid}", json=DISABLE)
    wait(authed, r.json()["job_id"])
    other = add(authed, ovpn_factory, name="fresh")
    assert authed.patch(f"/api/profiles/{other}", json={"name": "fresh2"}).status_code == 200


def test_delete_leaves_the_tunnel_and_its_config_as_they_are(authed, ovpn_factory, fakes):
    pid = add(authed, ovpn_factory)
    enable(authed, pid)
    r = authed.request("DELETE", f"/api/profiles/{pid}", json={"confirm": True})
    assert r.status_code == 200 and r.json()["tunnel_left"] == "openvpn-client@corp.service"
    assert authed.get(f"/api/profiles/{pid}").status_code == 404
    host = fakes["host"]
    assert "corp" in host.tunnel_files and host.units_data["openvpn-client@corp.service"]["state"] == "active"
    assert audit(authed, "profile.delete")[0]["detail"]["tunnel_left"] == "openvpn-client@corp.service"


def test_delete_of_a_profile_without_a_tunnel_says_nothing_is_left(authed, ovpn_factory):
    pid = add(authed, ovpn_factory)
    r = authed.request("DELETE", f"/api/profiles/{pid}", json={"confirm": True})
    assert r.json()["tunnel_left"] is None


# ---------------------------------------------------------- alerts, scan, host down

def test_certificate_alerts_cover_disabled_profiles(authed, ovpn_factory):
    soon = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=7)
    pid = add(authed, ovpn_factory, name="soon", expires=soon)
    assert authed.get(f"/api/profiles/{pid}").json()["status"] == "Disabled"
    codes = [a["code"] for a in authed.get("/api/overview").json()["attention"]]
    assert "profile.cert_expiring" in codes


def test_the_system_scan_skips_the_consoles_own_installed_copies(authed, ovpn_factory, tmp_path, monkeypatch):
    from server.settings import CONFIG

    monkeypatch.setattr(CONFIG, "scan_dirs", str(tmp_path))
    (tmp_path / "hand-made.ovpn").write_text(ovpn_factory(cn="hand"))
    managed, _ = tunnels.render(ovpn_factory(cn="ours"), "abc123")
    (tmp_path / "ours.conf").write_text(managed)
    names = {c["name"] for c in authed.get("/api/profiles/scan").json()["candidates"]}
    assert names == {"hand-made"}


def test_enable_is_refused_while_the_host_layer_is_down(authed, ovpn_factory, fakes):
    pid = add(authed, ovpn_factory)
    fakes["host"].break_()
    r = authed.patch(f"/api/profiles/{pid}", json=ENABLE)
    assert r.status_code in (409, 502)
    assert fakes["host"].tunnel_files == {}

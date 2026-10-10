"""US9 — services + logs integration (T058, FR-045..048): friction, jobs, cursor tail."""
from __future__ import annotations

import time


def wait_job(authed, job_id: str, timeout: float = 3.0) -> dict:
    body: dict = {}
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = authed.get(f"/api/jobs/{job_id}").json()
        if body.get("done"):
            return body
        time.sleep(0.05)
    return body


def test_services_list_is_allow_listed(authed):
    body = authed.get("/api/services").json()
    names = [u["unit"] for u in body["units"]]
    assert names == ["tailscaled.service", "openvpn@corp.service", "vpn-console.service"]
    assert body["_health"]["state"] == "ok"
    ts = next(u for u in body["units"] if u["unit"] == "tailscaled.service")
    assert ts["state"] == "running" and ts["enabled_on_boot"] is True


def test_stop_needs_confirm(authed):
    r = authed.post("/api/services/tailscaled.service/stop", json={})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "confirm_required"


def test_stop_with_confirm_runs_a_job(authed, fakes):
    r = authed.post("/api/services/tailscaled.service/stop", json={"confirm": True})
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]

    job = wait_job(authed, job_id)
    assert job["done"] is True and job["ok"] is True, job

    units = authed.get("/api/services").json()["units"]
    ts = next(u for u in units if u["unit"] == "tailscaled.service")
    assert ts["state"] == "inactive"

    actions = [e["action"] for e in authed.get("/api/overview").json()["recent"]]
    assert "service.stop" in actions


def test_restart_is_confirm_tier_and_completes(authed):
    r = authed.post("/api/services/openvpn@corp.service/restart", json={"confirm": True})
    assert r.status_code == 200, r.text
    job = wait_job(authed, r.json()["job_id"])
    assert job["ok"] is True, job
    units = authed.get("/api/services").json()["units"]
    ov = next(u for u in units if u["unit"] == "openvpn@corp.service")
    assert ov["state"] == "running"  # was failed before the restart


def test_simple_actions_skip_confirm(authed, fakes):
    r = authed.post("/api/services/openvpn@corp.service/start", json={})
    assert r.status_code == 200, r.text
    assert wait_job(authed, r.json()["job_id"])["ok"] is True
    assert ("openvpn@corp.service", "start") in fakes["host"].action_log


def test_foreign_unit_is_refused(authed):
    r = authed.post("/api/services/docker.service/stop", json={"confirm": True})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "unit_not_allowed"


def test_bad_action_is_422(authed):
    r = authed.post("/api/services/tailscaled.service/reboot", json={})
    assert r.status_code == 422


def test_unknown_job_is_404(authed):
    assert authed.get("/api/jobs/job-999").status_code == 404


def test_services_blocked_while_host_down(authed, fakes):
    fakes["host"].break_()
    body = authed.get("/api/services").json()
    assert body["units"] == []
    assert body["_health"]["state"] == "unavailable"

    r = authed.post("/api/services/tailscaled.service/stop", json={"confirm": True})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "subsystem_unavailable"


# ---------- logs ----------

def test_logs_units_listing(authed):
    body = authed.get("/api/logs").json()
    assert "tailscaled.service" in body["units"]
    assert body["_health"]["state"] == "ok"


def test_log_lines_shape_and_cursor(authed):
    body = authed.get("/api/logs/tailscaled.service").json()
    assert len(body["lines"]) == 4
    assert body["lines"][0]["msg"] == "Starting Tailscale node agent..."
    assert body["next_cursor"] == "c4"

    tail = authed.get("/api/logs/tailscaled.service", params={"after": "c4"}).json()
    assert tail["lines"] == []
    assert tail["next_cursor"] == "c4"  # position kept while quiet


def test_log_severity_and_text_filters(authed):
    errs = authed.get("/api/logs/tailscaled.service", params={"severity": "err"}).json()
    assert [ln["prio"] for ln in errs["lines"]] == [3]

    hits = authed.get("/api/logs/tailscaled.service", params={"q": "retry"}).json()
    assert [ln["msg"] for ln in hits["lines"]] == ["control: retry in 30s"]


def test_log_new_entries_arrive_after_cursor(authed, fakes):
    authed.get("/api/logs/tailscaled.service")  # prime + learn cursor
    fakes["host"].journal_entries.append(
        {"ts": "1760082800000000", "prio": 3, "msg": "probe failed again", "cursor": "c5"})
    tail = authed.get("/api/logs/tailscaled.service", params={"after": "c4"}).json()
    assert [ln["msg"] for ln in tail["lines"]] == ["probe failed again"]
    assert tail["next_cursor"] == "c5"


def test_log_limit_cap(authed):
    # the app maps request-validation failures to its 400 envelope (app.py)
    r = authed.get("/api/logs/tailscaled.service", params={"limit": 501})
    assert r.status_code == 400
    assert "error" in r.json()


def test_log_lines_loud_when_host_down(authed, fakes):
    fakes["host"].break_()
    body = authed.get("/api/logs/tailscaled.service").json()
    assert body["lines"] == []
    assert body["_health"]["state"] == "unavailable"
    assert body["_health"]["detail"]  # says why — never silent emptiness


def test_log_download(authed):
    r = authed.get("/api/logs/tailscaled.service/download")
    assert r.status_code == 200
    assert "attachment" in r.headers.get("content-disposition", "")
    assert "dial udp failed" in r.text

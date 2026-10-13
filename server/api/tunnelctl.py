"""Enable, disable and re-apply a profile's server tunnel (orchestration).

Enable writes the tunnel-only copy and starts the unit; once it has connected (and passed the
route check) boot start is turned on. Disable stops it and turns boot start off. The slow steps (a tunnel takes up to ~100 s to connect) run on a
worker thread reported through server/jobs.py. Nothing here runs when the console starts:
a tunnel only changes when somebody clicks.

After a tunnel connects its routes are checked; one that replaces the default route or
overlaps an existing route is stopped at once, so a tunnel can never cut off SSH, nginx or
Tailscale, nor take traffic from a tunnel started by hand.
"""
from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from typing import Any

from .. import audit, jobs, ovpn, tunnels
from ..db import get_conn
from . import common
from .schemas import api_error

POLL_SECONDS = 1.0     # tests set both of these to 0
WAIT_SECONDS = 100.0   # a Type=notify unit gives up after ~90 s by itself

RUNNING = ("connected", "connecting")

# The newest start/stop job per profile. A job that is no longer the newest (the admin edited,
# restarted or disabled the tunnel while it was waiting) steps aside without touching the unit.
_latest: dict[str, str] = {}
_latest_lock = threading.Lock()


def _claim(pid: str, job_id: str) -> None:
    with _latest_lock:
        _latest[pid] = job_id


def _superseded(pid: str, job_id: str) -> bool:
    with _latest_lock:
        return _latest.get(pid) != job_id


def names(row: dict[str, Any]) -> tuple[str, str, str]:
    """(instance, unit, interface) for a profile."""
    instance = tunnels.instance_name(row["name"])
    return instance, tunnels.unit_name(instance), tunnels.iface_name(row["id"])


# ---------------------------------------------------------------- state

def _owner(host: Any, instance: str) -> str | None:
    try:
        return host.tunnel_conf_owner(instance)
    except (OSError, ValueError):
        return None


def summaries(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Tunnel state for many profiles from cached host reads (one pass per request)."""
    host = common.host()
    units_r = common.host_get("units", 15.0, host.units)
    ifaces_r = common.host_get("interfaces", 10.0, host.interfaces)
    units_ok = units_r.health.state == "ok"
    units = {u["unit"]: u for u in (units_r.data or [])} if units_ok else {}
    ips = {i["iface"]: i["addr"] for i in (ifaces_r.data or [])} if ifaces_r.health.state == "ok" else {}
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        instance, unit_id, iface = names(row)
        if not units_ok:
            out[row["id"]] = {"state": "unknown", "unit": unit_id, "iface": iface, "ip": "", "since": "", "boot": False}
            continue
        mine = _owner(host, instance) == row["id"]
        out[row["id"]] = tunnels.tunnel_summary(units.get(unit_id) if mine else None, mine, unit_id, iface, ips.get(iface, ""))
    return out


def require_host() -> None:
    """A change to a server tunnel is refused while systemd cannot be read (FR-053): the
    console would be guessing what is running."""
    common.require_ok(common.host_get("units", 15.0, common.host().units), "host services")


def has_installed(row: dict[str, Any]) -> bool:
    """True if the server holds an installed copy that belongs to this profile."""
    return _owner(common.host(), names(row)[0]) == row["id"]


def current(row: dict[str, Any]) -> dict[str, Any]:
    """One profile's state read live (not cached), used right before acting."""
    host = common.host()
    instance, unit_id, iface = names(row)
    try:
        mine = _owner(host, instance) == row["id"]
        unit = host.unit_state(unit_id) if mine else None
        ip = next((i["addr"] for i in host.interfaces() if i["iface"] == iface), "")
    except (OSError, RuntimeError) as exc:
        raise api_error(409, "subsystem_unavailable",
                        f"host services is unavailable ({str(exc)[:120]}); mutations are disabled.",
                        subsystem="host services") from exc
    return tunnels.tunnel_summary(unit, mine, unit_id, iface, ip)


def is_running(row: dict[str, Any]) -> bool:
    try:
        return current(row)["state"] in RUNNING
    except Exception:  # noqa: BLE001 — host layer down: treat as unknown, never as running
        return False


# ---------------------------------------------------------------- what would happen

def _finding(f: tunnels.Finding) -> dict[str, Any]:
    return {"line_no": f.line_no, "text": f.text, "directive": f.directive, "why": f.why}


def plan(row: dict[str, Any], text: str) -> dict[str, Any]:
    """What enabling this profile would do, for the confirm dialog."""
    analysis = tunnels.analyze(text)
    _, notices = tunnels.render(text, row["id"], analysis)
    instance, unit_id, iface = names(row)
    try:
        available = common.host().tunnel_available()
    except Exception:  # noqa: BLE001
        available = False
    status = ovpn.derive_status(row["cert_expires_at"], True, row["parse_error"])
    blocked = ""
    if row["parse_error"]:
        blocked = f"This profile cannot be parsed ({row['parse_error']})."
    elif status == "Expired":
        blocked = "The certificate in this profile has expired."
    return {
        "instance": instance, "unit": unit_id, "iface": iface, "available": available,
        "blocked": blocked,
        "refused": [_finding(f) for f in analysis.refused],
        "scripts": [_finding(f) for f in analysis.scripts],
        "stripped": [_finding(f) for f in analysis.stripped],
        "default_route": [_finding(f) for f in analysis.default_route_lines],
        "needs_typed_confirm": bool(analysis.scripts),
        "wait_seconds": int(WAIT_SECONDS),
        "notices": notices,
    }


def check_runnable(row: dict[str, Any], text: str) -> tunnels.Analysis:
    """Refuse a profile that cannot run unattended on this server, naming the reason."""
    if row["parse_error"]:
        raise api_error(422, "tunnel_refused", f"This profile cannot be parsed ({row['parse_error']}).", findings=[])
    if ovpn.derive_status(row["cert_expires_at"], True, None) == "Expired":
        raise api_error(422, "tunnel_refused", "The certificate in this profile has expired.", findings=[])
    analysis = tunnels.analyze(text)
    if analysis.refused:
        lines = "; ".join(f"line {f.line_no}: {f.text} ({f.why})" for f in analysis.refused[:3])
        raise api_error(422, "tunnel_refused", f"This profile cannot run as a server tunnel. {lines}",
                        findings=[_finding(f) for f in analysis.refused])
    return analysis


def _profile_exists(pid: str) -> bool:
    return get_conn().execute("SELECT 1 FROM profiles WHERE id=?", (pid,)).fetchone() is not None


def install(row: dict[str, Any], text: str, analysis: tunnels.Analysis) -> list[str]:
    """Write the tunnel-only copy to the server; returns the notices about it."""
    host = common.host()
    instance, unit_id, _ = names(row)
    if not host.tunnel_available():
        raise api_error(409, "tunnel_unavailable",
                        "The server folder for tunnel configs is not mounted (VPNCONSOLE_TUNNEL_DIR).")
    owner = host.tunnel_conf_owner(instance)
    if owner == "":
        raise api_error(409, "tunnel_name_taken",
                        f'A config named "{instance}.conf" already exists on the server and the console did not create it.')
    if owner not in (None, row["id"]):
        if _profile_exists(owner):
            raise api_error(409, "tunnel_name_taken", f'Another profile already uses the tunnel name "{instance}".')
        if host.unit_state(unit_id)["state"] in ("active", "running", "activating"):
            raise api_error(409, "tunnel_name_taken",
                            f'A tunnel from a deleted profile is still running as "{instance}". Stop it on the Services page first.')
    conf, notices = tunnels.render(text, row["id"], analysis)
    host.tunnel_write(instance, conf)
    return notices


# ---------------------------------------------------------------- acting

_PROBLEM = re.compile(r"error|fail|cannot|can't|refused|denied|time(d)? ?out|exiting|SIGUSR|SIGTERM|SIGHUP|auth|verify|unreachable|resolve",
                      re.IGNORECASE)


def _log_tail(host: Any, unit_id: str) -> str:
    """The few journal lines that explain a tunnel that did not connect."""
    try:
        entries = host.journal(unit_id, limit=60)
    except Exception:  # noqa: BLE001
        return ""
    lines = [e["msg"] for e in entries if e.get("prio", 6) <= 4 or _PROBLEM.search(e["msg"])]
    lines = lines or [e["msg"] for e in entries]
    return " | ".join(lines[-3:])[:300]


def _address(host: Any, iface: str) -> str:
    return next((i["addr"] for i in host.interfaces() if i["iface"] == iface), "")


def _wait(host: Any, unit_id: str, iface: str, pid: str, job_id: str, name: str) -> tuple[str, str]:
    """Poll until the tunnel has an address, the unit has failed or stopped, the wait runs
    out, or a newer job takes over. Returns (outcome, ip) with outcome
    connected | failed | timeout | superseded."""
    deadline = time.monotonic() + WAIT_SECONDS
    started = time.monotonic()
    seen_running = False
    while True:
        if _superseded(pid, job_id):
            return "superseded", ""
        active = host.unit_state(unit_id).get("state", "")
        if active in ("active", "running") and (ip := _address(host, iface)):
            return "connected", ip
        if active == "failed":
            return "failed", ""
        if active in ("active", "running", "activating"):
            seen_running = True
            jobs.update(job_id, detail=f"Connecting {name}… waiting for the VPN server.")
        elif active == "inactive" and (seen_running or time.monotonic() - started > 8):
            return "failed", ""  # it exited by itself
        if time.monotonic() >= deadline:
            return "timeout", ""
        time.sleep(POLL_SECONDS)


def _finish(job_id: str, ok: bool, detail: str, **extra: Any) -> None:
    common.host_cache().invalidate("units")  # before "done", so whoever sees "done" reads fresh state
    common.host_cache().invalidate("interfaces")
    jobs.update(job_id, done=True, ok=ok, detail=detail, **extra)


def start_job(row: dict[str, Any], action: str, on_unsafe: Callable[[], None]) -> str:
    """Enable (action="start") or re-apply (action="restart") a tunnel; returns a job id.

    OpenVPN keeps trying forever, and a tunnel that connected later would skip the route
    check, so one that has no address when the wait runs out is stopped (and its boot start
    switched off). A tunnel therefore only ever comes up while this job is watching."""
    instance, unit_id, iface = names(row)
    name, pid = row["name"], row["id"]
    verb = "Restarting" if action == "restart" else "Starting"
    job_id = jobs.create(f"{verb} {name}…")
    _claim(pid, job_id)

    def work() -> None:
        host = common.host()
        audit_action = "profile.restart" if action == "restart" else "profile.enable"

        def fail(message: str, state: str, error: str, stop: bool) -> None:
            if stop:
                host.unit_action(unit_id, "disable", now=True)  # stop it and keep boot start off
                on_unsafe()
            audit.insert(audit_action, "profiles", target=name, outcome="failed",
                         detail={"id": pid, "unit": unit_id, "error": error})
            _finish(job_id, False, message, state=state)

        try:
            host.unit_queue(unit_id, action)
            common.host_cache().invalidate("units")  # the page polls: show Connecting, not the old state
            common.host_cache().invalidate("interfaces")
            outcome, ip = _wait(host, unit_id, iface, pid, job_id, name)
            if outcome == "superseded":
                _finish(job_id, False, "Replaced by a newer action on this profile.", state="superseded")
                return
            if outcome == "connected":
                bad = tunnels.route_violations(tunnels.routes_from_dicts(host.routes()), iface)
                if bad:
                    why = "; ".join(bad[:2])
                    fail(f"Stopped and disabled: {why}. The tunnel never touches the server's own routes.",
                         "guard", f"stopped by the safety check: {why}", stop=True)
                    return
                boot_note = ""
                try:
                    host.unit_action(unit_id, "enable")  # boot start only once it has connected (owner decision)
                except Exception as exc:  # noqa: BLE001 — the tunnel is up; say what did not work
                    boot_note = f" It will not start again after a reboot ({str(exc)[:120]})."
                audit.insert(audit_action, "profiles", target=name,
                             detail={"id": pid, "unit": unit_id, "ip": ip, **({"boot_error": boot_note.strip()} if boot_note else {})})
                _finish(job_id, True, f"Connected. Tunnel IP {ip}.{boot_note}", state="connected", ip=ip)
                return
            tail = _log_tail(host, unit_id)
            if outcome == "timeout":
                fail(f"Did not connect within {int(WAIT_SECONDS)} s, so it was stopped and turned off."
                     + (f" Last log lines: {tail}" if tail else ""),
                     "failed", tail or f"no connection within {int(WAIT_SECONDS)} s", stop=True)
            else:
                fail("The tunnel did not come up." + (f" Last log lines: {tail}" if tail else ""),
                     "failed", tail or "the tunnel did not come up", stop=False)
        except Exception as exc:  # noqa: BLE001 — audited boundary (SC-004)
            audit.insert(audit_action, "profiles", target=name, outcome="failed",
                         detail={"id": pid, "unit": unit_id, "error": str(exc)[:300]})
            _finish(job_id, False, str(exc)[:300], state="failed")

    threading.Thread(target=work, daemon=True).start()
    return job_id


def stop_job(row: dict[str, Any]) -> str:
    """Disable: stop the tunnel and turn boot start off."""
    _, unit_id, _ = names(row)
    name, pid = row["name"], row["id"]
    job_id = jobs.create(f"Stopping {name}…")
    _claim(pid, job_id)

    def work() -> None:
        try:
            common.host().unit_action(unit_id, "disable", now=True)
            audit.insert("profile.disable", "profiles", target=name, detail={"id": pid, "unit": unit_id})
            _finish(job_id, True, "Stopped.", state="stopped")
        except Exception as exc:  # noqa: BLE001 — audited boundary (SC-004)
            audit.insert("profile.disable", "profiles", target=name, outcome="failed",
                         detail={"id": pid, "unit": unit_id, "error": str(exc)[:300]})
            _finish(job_id, False, str(exc)[:300], state="failed")

    threading.Thread(target=work, daemon=True).start()
    return job_id


# ---------------------------------------------------------------- the stored profile changed

def resync(row: dict[str, Any], new_text: str, restart: bool, on_unsafe: Callable[[], None]) -> dict[str, Any]:
    """Bring the installed copy in line with the stored profile after an edit, an undo or a
    revert. {"applied": None} = nothing installed for it, nothing to do."""
    host = common.host()
    instance, _, _ = names(row)
    if not row["enabled"] or _owner(host, instance) != row["id"]:
        return {"applied": None}
    if row["parse_error"]:
        return {"applied": False, "reason": f"The new config cannot be parsed ({row['parse_error']}), so the running copy was left as it is."}
    analysis = tunnels.analyze(new_text)
    if analysis.refused:
        f = analysis.refused[0]
        return {"applied": False, "reason": f"The new config cannot run as a server tunnel (line {f.line_no}: {f.text}), so the installed copy was left as it is."}
    installed = host.tunnel_read(instance) or ""
    approved = {f.text for f in tunnels.analyze(installed).scripts}
    fresh = [f for f in analysis.scripts if f.text not in approved]
    if fresh:
        return {"applied": False, "reason": f"The new config adds script lines ({fresh[0].text}). Disable and Enable the profile to confirm them; the installed copy was left as it is."}
    notices = install(row, new_text, analysis)
    result: dict[str, Any] = {"applied": True, "notices": notices, "restarted": False}
    if restart:
        result["job_id"] = start_job(row, "restart", on_unsafe)
        result["restarted"] = True
    return result

"""API: exposures — serve / funnel / taildrive view + port annotations (US10).

Funnel is the only path to the public internet this console can open, so it
carries the heaviest friction: the 443/8443/10000 port constraint is checked
BEFORE the confirmation ask, and both funnel create and enable are
confirm-tier. Everything is audited ok|failed (constitution III, FR-043/044).
"""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Body

from .. import audit
from . import common
from .schemas import api_error, require_confirm

router = APIRouter()

FUNNEL_PORTS = {443, 8443, 10000}


def _serve_r():
    return common.local_get("serve", ttl=10.0, fetch=common.local().serve_status)


def _drive_r():
    return common.local_get("drive", ttl=10.0, fetch=common.local().drive_shares)


def _ports_r():
    return common.host_get("ports", ttl=15.0, fetch=common.host().listening_ports)


def _handler_target(handler: dict[str, Any]) -> tuple[str, str]:
    """(display, raw) pair for a serve Web handler."""
    if "Proxy" in handler:
        return f"proxy → {handler['Proxy']}", str(handler["Proxy"])
    if "Path" in handler:
        return f"path {handler['Path']}", str(handler["Path"])
    if "Text" in handler:
        return f"text · {handler['Text']}", ""
    return "", ""


def _entries(serve_cfg: dict[str, Any], shares: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Serve / funnel / taildrive rows from tailscaled's real shapes (ipn.ServeConfig,
    tailscale v1.104.1): TCP is keyed by port and holds HTTP or HTTPS (served via Web)
    or a TCPForward address; Web and AllowFunnel are keyed "host:port"; Taildrive
    shares arrive as [{"name", "path", "who"}]."""
    web = serve_cfg.get("Web") or {}
    allow = serve_cfg.get("AllowFunnel") or {}
    entries: list[dict[str, Any]] = []
    ports = [p for p in (serve_cfg.get("TCP") or {}) if str(p).isdigit()]
    for port in sorted(ports, key=int):
        tcp = (serve_cfg.get("TCP") or {}).get(port) or {}
        suffix = f":{port}"
        # the Web key carries the host name; prefer the fully qualified one
        hosts = sorted((k[: -len(suffix)] for k in web if k.endswith(suffix)),
                       key=lambda h: (-h.count("."), h))
        forward = str(tcp.get("TCPForward") or "")
        host = hosts[0] if hosts else str(tcp.get("TerminateTLS") or "")
        tls = bool(tcp.get("HTTPS"))
        funnel = bool(allow.get(f"{host}:{port}"))
        if forward:
            source = f"tcp://{host or 'this host'}:{port}"
            display, raw = f"tcp → {forward}", ""
        else:
            scheme = "https" if tls else "http"
            default = 443 if tls else 80
            source = f"{scheme}://{host or 'this host'}" + ("" if int(port) == default else f":{port}")
            handlers = (web.get(f"{host}:{port}") or {}).get("Handlers") or {}
            mount = "/" if "/" in handlers else next(iter(handlers), "")
            display, raw = _handler_target(handlers.get(mount) or {})
            if len(handlers) > 1:
                more = len(handlers) - 1
                display += f" (+{more} more path{'s' if more != 1 else ''})"
        entries.append({
            "id": f"tcp-{port}",
            "kind": "funnel" if funnel else "serve",
            "scope": "public" if funnel else "tailnet",
            "source": source,
            "target": display,
            "raw_target": raw,
            "port": int(port),
            "tls": tls,
            "tcp_forward": bool(forward),
            "enabled": True,
        })
    for share in shares or []:
        name = str(share.get("name") or "")
        path = str(share.get("path") or "")
        who = str(share.get("who") or "")
        entries.append({
            "id": f"drive-{name}",
            "kind": "taildrive",
            "scope": "share",
            "source": path,
            "target": f"share as {who}" if who else "share",
            "name": name,
            "raw_target": path,
            "port": None,
            "tls": False,
            "tcp_forward": False,
            "enabled": True,
        })
    return entries


def _annotate(ports: list[dict[str, Any]], entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    funnel_ports = {e["port"] for e in entries if e["kind"] == "funnel"}
    serve_ports = {e["port"] for e in entries if e["kind"] == "serve"}
    out = []
    for p in ports:
        row = dict(p)
        if p["port"] in funnel_ports:
            row["annotation"] = "funnel"
        elif p["port"] in serve_ports:
            row["annotation"] = "serve"
        elif p["local_addr"].startswith(("127.", "::1", "[::1]:", "localhost")):
            row["annotation"] = "local_only"
        else:
            row["annotation"] = "unexposed"
        out.append(row)
    return out


def _collisions(entries: list[dict[str, Any]], serve_cfg: dict[str, Any]) -> list[int]:
    """Ports where a funnel allowance and a serve listener disagree on the host
    name — tailscaled keeps whichever claim was made most recently, so the UI
    carries a standing warning until this is resolved."""
    owner: dict[int, str] = {}
    for e in entries:
        if e["port"] is not None and e["kind"] in ("serve", "funnel"):
            owner[e["port"]] = e["source"].split("//")[-1].split(":")[0]
    coll: set[int] = set()
    for key in (serve_cfg.get("AllowFunnel") or {}):
        name, _, port = key.rpartition(":")
        if not port.isdigit():
            continue
        if owner.get(int(port)) and name and name != owner[int(port)]:
            coll.add(int(port))
    return sorted(coll)


def _refuse_tcp_forward(entry: dict[str, Any]) -> None:
    """Raw TCP forwards use `tailscale serve --tcp`, which this page does not drive;
    they are listed so nothing is hidden, but changed with the CLI."""
    if entry.get("tcp_forward"):
        raise api_error(409, "not_supported",
                        "Raw TCP forwards are shown here but managed with the tailscale CLI.")


def _find(entries: list[dict[str, Any]], eid: str) -> dict[str, Any]:
    for e in entries:
        if e["id"] == eid:
            return e
    raise api_error(404, "not_found", "Exposure entry not found (refresh to pick up changes).")


@router.get("/exposures")
def get_exposures() -> dict[str, Any]:
    serve_r = _serve_r()
    drive_r = _drive_r()
    ports_r = _ports_r()
    serve_cfg = serve_r.data or {}
    entries = _entries(serve_cfg, drive_r.data or [])
    annotations = _annotate(ports_r.data or [], entries) if ports_r.data is not None else []
    return {
        "entries": entries,
        "ports": annotations,
        "collisions": _collisions(entries, serve_cfg),
        "_health": _worst_health(serve_r, drive_r).as_dict(),
        "ports_health": ports_r.health.as_dict(),
    }


def _worst_health(*results: Any) -> Any:
    for r in results:
        if r.health.state != "ok":
            return r.health
    return results[0].health


def _blocked() -> None:
    common.require_ok(_serve_r(), "local node")


def _create_drive(body: dict[str, Any]) -> dict[str, Any]:
    """Taildrive share (tailnet scope → confirm-tier, same as serve)."""
    path = str(body.get("path") or "").strip()
    name = str(body.get("name") or "").strip()
    if not path.startswith("/"):
        raise api_error(422, "invalid_path", "path must be an absolute filesystem path.")
    if not _DRIVE_NAME_RE.fullmatch(name):
        raise api_error(422, "invalid_name",
                        "share name must start with a letter or digit (letters, digits, . _ - after).")
    require_confirm(body)  # shares are visible to the whole tailnet
    _blocked()
    try:
        common.local().drive_add(name, path)
    except Exception as exc:  # noqa: BLE001 — audited boundary (SC-004)
        audit.insert("exposure.create", "exposures", target=path,
                     outcome="failed", detail={"error": str(exc)[:300], "kind": "drive"})
        raise api_error(502, "action_failed", f"tailscaled rejected the share: {exc}") from exc
    common.local_cache().invalidate("drive")
    audit.insert("exposure.create", "exposures", target=path,
                 detail={"kind": "drive", "name": name, "path": path})
    return {"ok": True}


_DRIVE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


@router.post("/exposures")
def create_exposure(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    kind = body.get("kind")
    if kind == "drive":
        return _create_drive(body)
    port = body.get("port")
    target = str(body.get("target") or "").strip()
    if kind not in ("serve", "funnel"):
        raise api_error(422, "bad_kind", 'kind must be "serve", "funnel" or "drive".')
    if not isinstance(port, int):
        raise api_error(422, "bad_port", "port must be an integer.")
    if not (target.startswith("http://") or target.startswith("https://") or target.startswith("/")):
        raise api_error(422, "invalid_target", 'target must be an http(s):// URL or a filesystem path.')
    tls = bool(body.get("tls", kind == "funnel"))

    # Funnel reaches the whole internet — the port constraint comes FIRST,
    # before friction (T063), so a bad port is rejected outright.
    if kind == "funnel" and port not in FUNNEL_PORTS:
        raise api_error(
            400, "port_not_allowed",
            f"Funnel only works on ports 443, 8443 and 10000 (got {port}).",
        )
    if kind == "funnel":
        require_confirm(body)  # creating a public exposure is confirm-tier
    _blocked()

    scheme = "https" if tls else "http"
    try:
        common.local().serve_add(port, target, scheme=scheme, funnel=kind == "funnel")
    except Exception as exc:  # noqa: BLE001 — audited boundary (SC-004)
        audit.insert("exposure.create", "exposures", target=f"port {port}",
                     outcome="failed", detail={"error": str(exc)[:300], "kind": kind})
        raise api_error(502, "action_failed", f"tailscaled rejected the {kind}: {exc}") from exc
    common.local_cache().invalidate("serve")
    audit.insert("exposure.create", "exposures", target=f"port {port}",
                 detail={"kind": kind, "port": port, "target": target, "funnel": kind == "funnel"})
    return {"ok": True}


@router.patch("/exposures/{eid:path}")
def set_enabled(eid: str, body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    _blocked()
    entries = _entries(_serve_r().data or {}, _drive_r().data or [])
    entry = _find(entries, eid)
    enabled = bool(body.get("enabled"))
    if entry["kind"] == "taildrive":
        raise api_error(409, "not_supported", "Taildrive shares are removed, not disabled.")
    _refuse_tcp_forward(entry)
    if entry["kind"] == "funnel" and enabled:
        require_confirm(body)  # re-enabling a public exposure is confirm-tier

    scheme = "https" if entry["tls"] else "http"
    funnel = entry["kind"] == "funnel"
    try:
        if enabled:
            common.local().serve_add(entry["port"], entry["raw_target"],
                                     scheme=scheme, funnel=funnel)
        else:
            common.local().serve_off(entry["port"], scheme=scheme, funnel=funnel)
    except Exception as exc:  # noqa: BLE001 — audited boundary (SC-004)
        audit.insert("exposure.enable" if enabled else "exposure.disable",
                     "exposures", target=f"port {entry['port']}", outcome="failed",
                     detail={"error": str(exc)[:300], "id": eid})
        raise api_error(502, "action_failed", f"tailscaled rejected the change: {exc}") from exc
    common.local_cache().invalidate("serve")
    audit.insert("exposure.enable" if enabled else "exposure.disable", "exposures",
                 target=f"port {entry['port']}", detail={"id": eid, "kind": entry["kind"]})
    return {"ok": True}


@router.delete("/exposures/{eid:path}")
def delete_exposure(eid: str, body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    _blocked()
    entries = _entries(_serve_r().data or {}, _drive_r().data or [])
    entry = _find(entries, eid)
    _refuse_tcp_forward(entry)
    require_confirm(body)  # removal is confirm-tier too (contract; the UI dialog supplies it)
    try:
        if entry["kind"] == "taildrive":
            common.local().drive_remove(entry["name"])
        else:
            common.local().serve_off(entry["port"], scheme="https" if entry["tls"] else "http",
                                     funnel=entry["kind"] == "funnel")
    except Exception as exc:  # noqa: BLE001 — audited boundary (SC-004)
        audit.insert("exposure.delete", "exposures", target=entry["source"],
                     outcome="failed", detail={"error": str(exc)[:300], "id": eid})
        raise api_error(502, "action_failed", f"tailscaled rejected the removal: {exc}") from exc
    common.local_cache().invalidate("serve")
    common.local_cache().invalidate("drive")
    audit.insert("exposure.delete", "exposures", target=entry["source"],
                 detail={"id": eid, "kind": entry["kind"]})
    return {"ok": True}

"""API: OpenVPN profile library — import, search, edit, delete (US2, FR-010..021).

Storage is plain files + SQLite index (owner decision). Status is derived on
every read from (cert expiry, enabled, parse error) — never stored as truth.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import secrets
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Response, UploadFile

from .. import audit, ovpn, tunnels
from ..db import get_conn
from ..searchlang import predicate
from ..settings import CONFIG
from ..undo import store as undo_store
from . import common, tunnelctl
from .schemas import api_error, require_confirm, require_typed

router = APIRouter()

# duplicate-resolution stash: token -> {name, text, created}
_stashes: dict[str, dict[str, Any]] = {}
STASH_TTL_S = 600.0


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clean_name(filename: str) -> str:
    base = re.sub(r"\.ovpn$", "", filename, flags=re.IGNORECASE)
    base = re.sub(r"[^\w.\- ]+", "_", base).strip() or "profile"
    return base[:120]


# --- storage helpers ----------------------------------------------------------

def _file_path(pid: str) -> Path:
    return CONFIG.profiles_dir / f"{pid}.ovpn"


def _store_profile(name: str, text: str, tags: list[str] | None = None) -> str:
    """Insert a parsed profile; returns its id. New profiles start Disabled (no tunnel):
    a tunnel only starts when somebody clicks Enable."""
    pid = secrets.token_urlsafe(8)
    meta = ovpn.parse(text)
    _file_path(pid).write_text(text, encoding="utf-8")
    get_conn().execute(
        "INSERT INTO profiles(id, name, tags, file_path, size_bytes, endpoints, cipher,"
        " tls_version_min, has_auth_user_pass, cert_expires_at, parse_error, status,"
        " enabled, config_sha256, updated_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,0,?,?)",
        (
            pid, name, json.dumps(tags or []), str(_file_path(pid)), len(text.encode()),
            json.dumps(meta["endpoints"]), meta["cipher"], meta["tls_version_min"],
            int(meta["has_auth_user_pass"]), meta["cert_expires_at"], meta["parse_error"],
            ovpn.derive_status(meta["cert_expires_at"], False, meta["parse_error"]),
            meta["config_sha256"], _now(),
        ),
    )
    return pid


def _reparse_update(pid: str, text: str, keep_previous: bool) -> dict[str, Any]:
    """Replace the config text of an existing profile (edit / duplicate-replace)."""
    conn = get_conn()
    row = conn.execute("SELECT * FROM profiles WHERE id=?", (pid,)).fetchone()
    if row is None:
        raise api_error(404, "not_found", "Profile not found.")
    old_text = _read_text(pid)  # read BEFORE the file is overwritten
    meta = ovpn.parse(text)
    _file_path(pid).write_text(text, encoding="utf-8")
    enabled = bool(row["enabled"])
    conn.execute(
        "UPDATE profiles SET size_bytes=?, endpoints=?, cipher=?, tls_version_min=?,"
        " has_auth_user_pass=?, cert_expires_at=?, parse_error=?, status=?,"
        " config_sha256=?, previous_text=?, updated_at=? WHERE id=?",
        (
            len(text.encode()), json.dumps(meta["endpoints"]), meta["cipher"],
            meta["tls_version_min"], int(meta["has_auth_user_pass"]),
            meta["cert_expires_at"], meta["parse_error"],
            ovpn.derive_status(meta["cert_expires_at"], enabled, meta["parse_error"]),
            meta["config_sha256"], old_text if keep_previous else None, _now(), pid,
        ),
    )
    return meta


def _read_text(pid: str) -> str:
    return _file_path(pid).read_text(encoding="utf-8")


def _get_row(pid: str) -> dict[str, Any]:
    row = get_conn().execute("SELECT * FROM profiles WHERE id=?", (pid,)).fetchone()
    if row is None:
        raise api_error(404, "not_found", "Profile not found.")
    return dict(row)


def _validate_auth(profile_row: dict[str, Any], auth: Any) -> tuple[str, str]:
    if not profile_row["has_auth_user_pass"]:
        raise api_error(422, "auth_not_needed", "This profile does not sign in with a username and password.")
    if not isinstance(auth, dict):
        raise api_error(422, "bad_auth", "auth must be {username, password}.")
    username, password = str(auth.get("username") or ""), str(auth.get("password") or "")
    try:
        tunnels.auth_file_text(username, password)
    except ValueError as exc:
        raise api_error(422, "bad_auth", str(exc).capitalize() + ".") from exc
    return username, password


def _set_auth(pid: str, username: str, password: str) -> None:
    get_conn().execute(
        "INSERT INTO profile_auth(profile_id, username, password, updated_at) VALUES(?,?,?,?) "
        "ON CONFLICT(profile_id) DO UPDATE SET username=excluded.username, password=excluded.password, "
        "updated_at=excluded.updated_at",
        (pid, username, password, _now()))


def _set_enabled(pid: str, enabled: bool) -> None:
    """Flip the enabled flag (and the stored status with it). Safe if the profile is gone."""
    try:
        row = _get_row(pid)
    except Exception:  # noqa: BLE001 — deleted while a tunnel job was running
        return
    get_conn().execute(
        "UPDATE profiles SET enabled=?, status=? WHERE id=?",
        (int(enabled), ovpn.derive_status(row["cert_expires_at"], enabled, row["parse_error"]), pid),
    )


def _view(row: dict[str, Any], with_text: bool = False, tunnel: dict[str, Any] | None = None) -> dict[str, Any]:
    status = ovpn.derive_status(row["cert_expires_at"], bool(row["enabled"]), row["parse_error"])
    names = get_conn().execute(
        "SELECT COUNT(*) AS n FROM profiles WHERE name=? AND id != ?",
        (row["name"], row["id"]),
    ).fetchone()["n"]
    out = {
        "id": row["id"],
        "name": row["name"],
        "tags": json.loads(row["tags"]),
        "status": status,
        "parse_error": row["parse_error"],
        "enabled": bool(row["enabled"]),
        "endpoints": json.loads(row["endpoints"]),
        "cipher": row["cipher"],
        "tls_version_min": row["tls_version_min"],
        "has_auth_user_pass": bool(row["has_auth_user_pass"]),
        "cert_expires_at": row["cert_expires_at"],
        "size_bytes": row["size_bytes"],
        "updated_at": row["updated_at"],
        "config_sha256": row["config_sha256"],
        "name_shared": names > 0,
    }
    auth_row = get_conn().execute(
        "SELECT username FROM profile_auth WHERE profile_id=?", (row["id"],)).fetchone()
    out["auth"] = {
        "needed": bool(row["has_auth_user_pass"]),
        "stored": auth_row is not None,
        "username": auth_row["username"] if auth_row else None,
    }
    if tunnel is not None:
        out["tunnel"] = tunnel
    if row["previous_text"]:
        out["previous_sha256"] = hashlib.sha256(row["previous_text"].encode()).hexdigest()
    if with_text:
        out["config_text"] = _read_text(row["id"])
    return out


# --- reads ---------------------------------------------------------------------

@router.get("/profiles")
def list_profiles(q: str = "") -> dict[str, Any]:
    rows = [dict(r) for r in get_conn().execute("SELECT * FROM profiles ORDER BY name COLLATE NOCASE")]
    if q:
        rows = [r for r in rows if predicate(q, {
            "tag": lambda r: json.loads(r["tags"]),
            "status": lambda r: ovpn.derive_status(r["cert_expires_at"], bool(r["enabled"]), r["parse_error"]),
            "cipher": lambda r: r["cipher"] or "",
            "server": lambda r: " ".join(e["host"] for e in json.loads(r["endpoints"])),
            "name": lambda r: r["name"],
            "_text": lambda r: " ".join(
                [r["name"], r["cipher"] or "", *json.loads(r["tags"]),
                 *[e["host"] for e in json.loads(r["endpoints"])]]
            ),
            "_flags": lambda r: {
                "expired": ovpn.derive_status(r["cert_expires_at"], bool(r["enabled"]), r["parse_error"]) == "Expired",
                "expiring": ovpn.derive_status(r["cert_expires_at"], bool(r["enabled"]), r["parse_error"]) == "Expiring",
                "disabled": not r["enabled"],
                "error": bool(r["parse_error"]),
            },
        })(r)]
    states = tunnelctl.summaries(rows)
    return {"profiles": [_view(r, tunnel=states.get(r["id"])) for r in rows]}


@router.get("/profiles/scan")
def scan_system_profiles() -> dict[str, Any]:
    """Preview importable configs from the host's scan mounts (read-only)."""
    from .. import systemscan

    return {"candidates": systemscan.scan(), "roots": CONFIG.scan_dirs}


@router.post("/profiles/import-system")
def import_system_profile(body: dict[str, Any]) -> dict[str, Any]:
    """Import ONE file discovered by the scan — path must be under a scan root,
    so the endpoint is not an arbitrary-file-read primitive."""
    raw_path = str(body.get("path") or "")
    try:
        resolved = Path(raw_path).resolve(strict=True)
    except OSError:
        raise api_error(404, "not_found", "File not found. Rescan and try again.") from None
    allowed = any(
        resolved.is_relative_to(Path(root.strip()).resolve())
        for root in CONFIG.scan_dirs.split(",") if root.strip()
    )
    if not allowed:
        raise api_error(422, "outside_scan_roots",
                        "Only files listed by the system scan can be imported.")
    try:
        raw = resolved.read_bytes()
    except OSError as exc:
        raise api_error(422, "unreadable", f"Could not read the file: {exc}") from exc
    if len(raw) > ovpn.MAX_PROFILE_BYTES:
        raise api_error(413, "too_large", "Config exceeds the 1 MiB cap.")

    text = raw.decode("utf-8", errors="replace")
    name = _clean_name(resolved.stem)
    meta = ovpn.parse(text)
    dup = get_conn().execute(
        "SELECT id FROM profiles WHERE config_sha256=?", (meta["config_sha256"],)
    ).fetchone()
    if dup:
        return {"status": "duplicate", "duplicate_of": dup["id"], "name": name,
                "parse_error": meta["parse_error"]}
    pid = _store_profile(name, text)
    audit.insert("profile.import", "profiles", target=name,
                 detail={"id": pid, "source": "system-scan", "path": str(resolved),
                         "parse_error": meta["parse_error"]})
    return {"status": "imported", "id": pid, "name": name,
            "parse_error": meta["parse_error"]}


@router.get("/profiles/{pid}")
def get_profile(pid: str) -> dict[str, Any]:
    row = _get_row(pid)
    return _view(row, with_text=True, tunnel=tunnelctl.summaries([row])[pid])


@router.get("/profiles/{pid}/tunnel")
def get_tunnel(pid: str) -> dict[str, Any]:
    """The tunnel's state, the last log lines, and what Enable would do (for its dialog)."""
    row = _get_row(pid)
    summary = tunnelctl.summaries([row])[pid]
    tail: list[dict[str, Any]] = []
    if summary["state"] not in ("none", "unknown"):
        try:
            tail = [{"ts": e["ts"], "msg": e["msg"]} for e in common.host().journal(summary["unit"], limit=8)]
        except Exception:  # noqa: BLE001 — a missing journal must not hide the state
            tail = []
    return {"tunnel": summary, "plan": tunnelctl.plan(row, _read_text(pid)), "log_tail": tail}


@router.get("/profiles/{pid}/download")
def download_profile(pid: str) -> Response:
    row = _get_row(pid)
    text = _read_text(pid)
    # certificate state, whatever the Enable switch says: the client warns before import (FR-019)
    status = ovpn.derive_status(row["cert_expires_at"], True, row["parse_error"])
    return Response(
        content=text,
        media_type="application/x-openvpn-profile",
        headers={
            "Content-Disposition": f'attachment; filename="{row["name"]}.ovpn"',
            "X-Profile-Status": status,  # the client warns before import (FR-019)
        },
    )


# --- import --------------------------------------------------------------------

def _sweep_stashes() -> None:
    now = time.monotonic()
    for token in [t for t, s in _stashes.items() if now - s["created"] > STASH_TTL_S]:
        del _stashes[token]


@router.post("/profiles/import")
async def import_profiles(files: list[UploadFile] = File(...)) -> dict[str, Any]:
    """Multipart upload; per-file result incl. duplicate detection (FR-014)."""
    results = []
    for upload in list(files):
        name = _clean_name(upload.filename or "profile.ovpn")
        raw = await upload.read()
        if len(raw) > ovpn.MAX_PROFILE_BYTES:
            audit.insert("profile.import", "profiles", target=name, outcome="failed",
                         detail={"reason": "oversize"})
            results.append({"name": name, "status": "error",
                            "message": f"over the 1 MiB cap ({len(raw)} bytes)"})
            continue
        text = raw.decode("utf-8", errors="replace")
        meta = ovpn.parse(text)
        dup = get_conn().execute(
            "SELECT id FROM profiles WHERE config_sha256=?", (meta["config_sha256"],)
        ).fetchone()
        if dup:
            _sweep_stashes()
            stash = secrets.token_urlsafe(12)
            _stashes[stash] = {"name": name, "text": text, "created": time.monotonic()}
            audit.insert("profile.import", "profiles", target=name, outcome="duplicate",
                         detail={"duplicate_of": dup["id"]})
            results.append({"name": name, "status": "duplicate",
                            "duplicate_of": dup["id"], "stash": stash,
                            "parse_error": meta["parse_error"]})
            continue
        pid = _store_profile(name, text)
        audit.insert("profile.import", "profiles", target=name,
                     detail={"id": pid, "parse_error": meta["parse_error"]})
        results.append({"name": name, "status": "imported", "id": pid,
                        "parse_error": meta["parse_error"]})
    return {"results": results}


@router.post("/profiles/import/confirm")
def confirm_import(body: dict[str, Any]) -> dict[str, Any]:
    stash_token = body.get("stash") or ""
    action = body.get("action")
    stash = _stashes.get(stash_token)
    if not stash:
        raise api_error(410, "stash_expired", "This duplicate prompt has expired; re-import the file.")
    if action not in ("keep_both", "replace"):
        raise api_error(400, "bad_action", "action must be keep_both or replace.")
    del _stashes[stash_token]

    if action == "keep_both":
        base, n = stash["name"], 1
        existing = {r["name"] for r in get_conn().execute("SELECT name FROM profiles")}
        while base in existing:
            n += 1
            base = f"{stash['name']} ({n})"
        pid = _store_profile(base, stash["text"])
        audit.insert("profile.import", "profiles", target=base,
                     detail={"id": pid, "kept_both": True})
        return {"profile": _view(_get_row(pid))}

    target = body.get("target")
    if not target:
        raise api_error(400, "target_required", "Replace needs the existing profile id.")
    _reparse_update(target, stash["text"], keep_previous=True)
    row = _get_row(target)
    audit.insert("profile.replace", "profiles", target=row["name"],
                 detail={"id": target, "replaced_duplicate": True})
    sync = tunnelctl.resync(row, stash["text"], restart=False, on_unsafe=lambda: _set_enabled(target, False))
    return {"profile": _view(row), "tunnel": sync}


# --- mutations -------------------------------------------------------------------

@router.patch("/profiles/{pid}")
def patch_profile(pid: str, body: dict[str, Any]):
    row = _get_row(pid)
    undo_token = None
    undo_restore = None
    undo_label = None
    event_id = None
    job_id = None
    notices: list[str] = []
    sync: dict[str, Any] | None = None

    def unsafe() -> None:
        _set_enabled(pid, False)

    # --- checks first: nothing is changed until every one of them has passed ---------
    new_text: str | None = None
    auth_creds: tuple[str, str] | None = None
    if "auth" in body:
        auth_creds = _validate_auth(row, body["auth"])
    renaming = "name" in body and body["name"] != row["name"]
    if "config_text" in body and body["config_text"] != _read_text(pid):
        new_text = body["config_text"]
        if len(new_text.encode()) > ovpn.MAX_PROFILE_BYTES:
            raise api_error(413, "too_large", "Config exceeds the 1 MiB cap.")
        if tunnelctl.has_installed(row):
            tunnelctl.require_host()
            if tunnelctl.is_running(row):
                # saving restarts the running tunnel, so it needs a confirm that names it
                require_confirm(body)
    if renaming and (row["enabled"] or tunnelctl.summaries([row])[pid]["state"] != "none"):
        raise api_error(409, "rename_blocked",
                        "Disable the profile before renaming it: its server tunnel is named after it.")
    want = tunnel_state = analysis = None
    auth_applied = False
    if "enabled" in body:
        if new_text is not None or renaming:
            # the tunnel is named after the profile and runs its config: one thing at a time
            raise api_error(422, "one_change_at_a_time",
                            "Enable or Disable the profile in a separate step from changing its config or name.")
        want = bool(body["enabled"])
        tunnelctl.require_host()
        tunnel_state = tunnelctl.current(row)["state"]
        tunnel_up = tunnel_state in tunnelctl.RUNNING
        if want and not tunnel_up:
            analysis = tunnelctl.check_runnable(row, _read_text(pid), auth_supplied=auth_creds is not None)
            if analysis.scripts:
                require_typed(body, row["name"], "to let this profile's scripts run as root")
            elif analysis.auth_needed and auth_creds:
                # a password is about to land in a root-only file on this server
                require_typed(body, row["name"], "to store this profile's password in a root-only file on this server")
            else:
                require_confirm(body)
        elif not want and tunnel_up:
            require_confirm(body)  # stopping a live tunnel

    # --- edit --------------------------------------------------------------------------
    if new_text is not None:
        running = tunnelctl.is_running(row)
        old_text = _read_text(pid)
        _reparse_update(pid, new_text, keep_previous=True)
        new_row = _get_row(pid)
        event_id = audit.insert("profile.edit", "profiles", target=new_row["name"],
                                detail={"id": pid})

        def _undo_edit(pid: str = pid, old: str = old_text) -> None:
            _reparse_update(pid, old, keep_previous=False)
            fresh = _get_row(pid)
            tunnelctl.resync(fresh, old, restart=tunnelctl.is_running(fresh),
                             on_unsafe=lambda: _set_enabled(pid, False))

        undo_restore = _undo_edit
        undo_label = "profile.edit"
        row = new_row
        sync = tunnelctl.resync(row, new_text, restart=running, on_unsafe=unsafe)
        job_id = sync.get("job_id")
        notices += sync.get("notices", [])

    # --- Enable starts the tunnel, Disable stops it --------------------------------------
    if want is not None:
        tunnel_up = tunnel_state in tunnelctl.RUNNING
        if want and tunnel_up:
            _set_enabled(pid, True)  # already up: nothing to start
        elif want:
            if auth_creds:
                _set_auth(pid, *auth_creds)
                audit.insert("profile.auth", "profiles", target=row["name"],
                             detail={"id": pid, "username": auth_creds[0], "at_enable": True})
                row = _get_row(pid)
                auth_applied = True
            notices += tunnelctl.install(row, _read_text(pid), analysis)
            _set_enabled(pid, True)
            row = _get_row(pid)
            job_id = tunnelctl.start_job(row, "start", unsafe)
        elif tunnel_state != "none":
            _set_enabled(pid, False)
            row = _get_row(pid)
            job_id = tunnelctl.stop_job(row)
        elif want != bool(row["enabled"]):
            # no tunnel was ever installed for it: only the flag changes, and that is undoable
            previous_enabled = bool(row["enabled"])
            _set_enabled(pid, want)
            event_id = audit.insert("profile.disable", "profiles", target=row["name"], detail={"id": pid})
            undo_restore = lambda pid=pid, prev=previous_enabled: _set_enabled(pid, prev)  # noqa: E731
            undo_label = "profile.disable"
        row = _get_row(pid)

    if renaming:
        new_name = _clean_name(str(body["name"]))
        get_conn().execute("UPDATE profiles SET name=? WHERE id=?", (new_name, pid))
        audit.insert("profile.rename", "profiles", target=new_name,
                     detail={"id": pid, "from": row["name"]})
        row = _get_row(pid)

    if auth_creds is not None and not auth_applied:
        _set_auth(pid, *auth_creds)
        audit.insert("profile.auth", "profiles", target=row["name"],
                     detail={"id": pid, "username": auth_creds[0]})
        if tunnelctl.has_installed(row):
            sync = tunnelctl.resync(row, _read_text(pid), restart=False,
                                    on_unsafe=lambda: _set_enabled(pid, False))
            notices += sync.get("notices", [])
        row = _get_row(pid)

    if "tags" in body:
        tags = [str(t)[:40] for t in body["tags"]][:12]
        get_conn().execute("UPDATE profiles SET tags=? WHERE id=?",
                           (json.dumps(tags), pid))
        audit.insert("profile.tag", "profiles", target=row["name"],
                     detail={"id": pid, "tags": tags})
        row = _get_row(pid)

    if undo_restore is not None and undo_label:
        undo_token = undo_store.register("profiles", undo_label, undo_restore, event_id or 0)
    return {"profile": _view(row, with_text=True, tunnel=tunnelctl.summaries([row])[pid]),
            "undo_token": undo_token, "job_id": job_id, "notices": notices, "tunnel_sync": sync}


@router.post("/profiles/{pid}/revert")
def revert_profile(pid: str, body: dict[str, Any] | None = None):
    """Swap config back to the stored previous version (FR-012); revertible itself."""
    row = _get_row(pid)
    if not row["previous_text"]:
        raise api_error(409, "nothing_to_revert", "No previous version is stored for this profile.")
    running = False
    if tunnelctl.has_installed(row):
        tunnelctl.require_host()
        running = tunnelctl.is_running(row)
        if running:
            require_confirm(body or {})  # reverting restarts the running tunnel
    _reparse_update(pid, row["previous_text"], keep_previous=True)  # old↔new swap
    fresh = _get_row(pid)
    audit.insert("profile.revert", "profiles", target=fresh["name"],
                 detail={"id": pid})
    sync = tunnelctl.resync(fresh, _read_text(pid), restart=running, on_unsafe=lambda: _set_enabled(pid, False))
    return {"profile": _view(fresh, with_text=True, tunnel=tunnelctl.summaries([fresh])[pid]),
            "job_id": sync.get("job_id"), "tunnel_sync": sync}


def _delete_row(pid: str) -> dict[str, Any]:
    row = _get_row(pid)
    get_conn().execute("DELETE FROM share_links WHERE profile_id=?", (pid,))
    get_conn().execute("DELETE FROM profiles WHERE id=?", (pid,))
    _file_path(pid).unlink(missing_ok=True)
    return row


@router.delete("/profiles/{pid}")
def delete_profile(pid: str, body: dict[str, Any] | None = None):
    require_confirm(body or {})
    row = _get_row(pid)
    left = tunnelctl.summaries([row])[pid]  # a tunnel it has on the server is left as it is (owner decision)
    _delete_row(pid)
    audit.insert("profile.delete", "profiles", target=row["name"],
                 detail={"id": pid, **({"tunnel_left": left["unit"]} if left["state"] not in ("none", "unknown") else {})})
    return {"ok": True,
            "tunnel_left": left["unit"] if left["state"] not in ("none", "unknown") else None}


@router.post("/profiles/bulk-delete")
def bulk_delete(body: dict[str, Any]):
    ids = body.get("ids") or []
    require_typed(body, "DELETE", f"delete {len(ids)} profiles")
    deleted = []
    for pid in ids:
        try:
            row = _delete_row(pid)
            deleted.append(row["name"])
            audit.insert("profile.delete", "profiles", target=row["name"],
                         detail={"id": pid, "bulk": True})
        except Exception:  # noqa: BLE001 — one bad id must not block the batch
            continue
    return {"deleted": len(deleted), "names": deleted}

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

from .. import audit, ovpn
from ..db import get_conn
from ..searchlang import predicate
from ..settings import CONFIG
from ..undo import store as undo_store
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
    """Insert a parsed profile; returns its id."""
    pid = secrets.token_urlsafe(8)
    meta = ovpn.parse(text)
    _file_path(pid).write_text(text, encoding="utf-8")
    get_conn().execute(
        "INSERT INTO profiles(id, name, tags, file_path, size_bytes, endpoints, cipher,"
        " tls_version_min, has_auth_user_pass, cert_expires_at, parse_error, status,"
        " enabled, config_sha256, updated_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)",
        (
            pid, name, json.dumps(tags or []), str(_file_path(pid)), len(text.encode()),
            json.dumps(meta["endpoints"]), meta["cipher"], meta["tls_version_min"],
            int(meta["has_auth_user_pass"]), meta["cert_expires_at"], meta["parse_error"],
            ovpn.derive_status(meta["cert_expires_at"], True, meta["parse_error"]),
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


def _view(row: dict[str, Any], with_text: bool = False) -> dict[str, Any]:
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
    return {"profiles": [_view(r) for r in rows]}


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
        raise api_error(404, "not_found", "File not found — rescan and try again.") from None
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
    return _view(_get_row(pid), with_text=True)


@router.get("/profiles/{pid}/download")
def download_profile(pid: str) -> Response:
    row = _get_row(pid)
    text = _read_text(pid)
    status = ovpn.derive_status(row["cert_expires_at"], bool(row["enabled"]), row["parse_error"])
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
    return {"profile": _view(row)}


# --- mutations -------------------------------------------------------------------

@router.patch("/profiles/{pid}")
def patch_profile(pid: str, body: dict[str, Any]):
    row = _get_row(pid)
    undo_token = None
    undo_restore = None
    undo_label = None
    event_id = None

    if "config_text" in body and body["config_text"] != _read_text(pid):
        new_text: str = body["config_text"]
        if len(new_text.encode()) > ovpn.MAX_PROFILE_BYTES:
            raise api_error(413, "too_large", "Config exceeds the 1 MiB cap.")
        old_text = _read_text(pid)
        _reparse_update(pid, new_text, keep_previous=True)
        new_row = _get_row(pid)
        event_id = audit.insert("profile.edit", "profiles", target=new_row["name"],
                                detail={"id": pid})
        undo_restore = (lambda pid=pid, old=old_text: _reparse_update(pid, old, keep_previous=False))
        undo_label = "profile.edit"
        row = new_row

    if "enabled" in body and bool(body["enabled"]) != bool(row["enabled"]):
        enabled = bool(body["enabled"])
        previous_enabled = bool(row["enabled"])
        get_conn().execute(
            "UPDATE profiles SET enabled=?, status=? WHERE id=?",
            (int(enabled),
             ovpn.derive_status(row["cert_expires_at"], enabled, row["parse_error"]),
             pid),
        )
        event_id = audit.insert("profile.disable" if not enabled else "profile.enable",
                                "profiles", target=row["name"], detail={"id": pid})

        def _restore_enabled(pid: str = pid, prev: bool = previous_enabled,
                             r: dict[str, Any] = row) -> None:
            get_conn().execute(
                "UPDATE profiles SET enabled=?, status=? WHERE id=?",
                (int(prev), ovpn.derive_status(r["cert_expires_at"], prev, r["parse_error"]), pid),
            )

        undo_restore = _restore_enabled
        undo_label = "profile.disable" if not enabled else "profile.enable"
        row = _get_row(pid)

    if "name" in body and body["name"] != row["name"]:
        new_name = _clean_name(str(body["name"]))
        get_conn().execute("UPDATE profiles SET name=? WHERE id=?", (new_name, pid))
        audit.insert("profile.rename", "profiles", target=new_name,
                     detail={"id": pid, "from": row["name"]})
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
    return {"profile": _view(row, with_text=True), "undo_token": undo_token}


@router.post("/profiles/{pid}/revert")
def revert_profile(pid: str):
    """Swap config back to the stored previous version (FR-012); revertible itself."""
    row = _get_row(pid)
    if not row["previous_text"]:
        raise api_error(409, "nothing_to_revert", "No previous version is stored for this profile.")
    _reparse_update(pid, row["previous_text"], keep_previous=True)  # old↔new swap
    fresh = _get_row(pid)
    audit.insert("profile.revert", "profiles", target=fresh["name"],
                 detail={"id": pid})
    return {"profile": _view(fresh, with_text=True)}


def _delete_row(pid: str) -> dict[str, Any]:
    row = _get_row(pid)
    get_conn().execute("DELETE FROM share_links WHERE profile_id=?", (pid,))
    get_conn().execute("DELETE FROM profiles WHERE id=?", (pid,))
    _file_path(pid).unlink(missing_ok=True)
    return row


@router.delete("/profiles/{pid}")
def delete_profile(pid: str, body: dict[str, Any] | None = None):
    require_confirm(body or {})
    row = _delete_row(pid)
    audit.insert("profile.delete", "profiles", target=row["name"], detail={"id": pid})
    return {"ok": True}


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

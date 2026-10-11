"""Scan the host's usual OpenVPN config locations for importable profiles.

The container sees the host's config dirs through read-only /scan/* mounts
(compose; VPNCONSOLE_SCAN_DIRS lists them). Everything here is read-only:
candidates are previews only — importing goes through the normal pipeline
(``_store_profile``) so parse, dedupe, and audit rules stay identical.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import ovpn
from .db import get_conn
from .settings import CONFIG

# how /scan/<alias> mounts map back to their real host paths for display
_ALIAS_TO_HOST = {"openvpn": "/etc/openvpn", "home": "/home", "root": "/root"}
MAX_CANDIDATES = 200
MAX_DEPTH = 6


def _display_path(p: Path) -> str:
    """Show the real host path (/scan/root/x.ovpn → /root/x.ovpn)."""
    try:
        rel = p.relative_to("/scan")
    except ValueError:
        return str(p)
    host = _ALIAS_TO_HOST.get(rel.parts[0], "/scan/" + rel.parts[0]) if rel.parts else ""
    return str(Path(host) / Path(*rel.parts[1:])) if len(rel.parts) > 1 else host


def _dirs() -> list[Path]:
    return [Path(p.strip()) for p in (CONFIG.scan_dirs or "").split(",") if p.strip()]


def scan() -> list[dict[str, Any]]:
    existing = {
        r["config_sha256"]: r["id"]
        for r in get_conn().execute("SELECT id, config_sha256 FROM profiles")
    }
    out: list[dict[str, Any]] = []
    for base in _dirs():
        if not base.is_dir():
            continue
        try:
            found = sorted(base.rglob("*"))
        except OSError:
            continue
        for p in found:
            if len(out) >= MAX_CANDIDATES:
                return out
            if not p.is_file() or p.suffix.lower() not in (".ovpn", ".conf"):
                continue
            if len(p.relative_to(base).parts) > MAX_DEPTH:
                continue
            row: dict[str, Any] = {
                "path": str(p),
                "display_path": _display_path(p),
                "name": p.stem,
                "size_bytes": None,
                "endpoint": None,
                "cipher": None,
                "cert_expires_at": None,
                "parse_error": None,
                "imported_profile_id": None,
                "status": "new",
            }
            try:
                row["size_bytes"] = p.stat().st_size
                if row["size_bytes"] > ovpn.MAX_PROFILE_BYTES:
                    row["status"] = "too-large"
                    out.append(row)
                    continue
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                row["status"] = "unreadable"
                row["parse_error"] = str(exc)[:120]
                out.append(row)
                continue
            meta = ovpn.parse(text)
            row.update({
                "endpoint": (lambda e: f"{e['host']}:{e['port']}" if e else None)(
                    (meta["endpoints"] or [None])[0]),
                "cipher": meta["cipher"],
                "cert_expires_at": meta["cert_expires_at"],
                "parse_error": meta["parse_error"],
                "imported_profile_id": existing.get(meta["config_sha256"]),
            })
            row["status"] = "imported" if row["imported_profile_id"] else (
                "error" if meta["parse_error"] else "new")
            out.append(row)
    # new profiles first, then already-imported, then broken
    rank = {"new": 0, "imported": 1, "error": 2, "too-large": 3, "unreadable": 4}
    return sorted(out, key=lambda r: rank.get(r["status"], 5))

"""API: share-link admin endpoints (US3) — gated via app wiring."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import Response

from .. import audit, sharelinks
from ..api.schemas import api_error
from ..db import get_conn
from ..undo import store as undo_store

router = APIRouter()


def _profile_or_404(pid: str) -> dict[str, Any]:
    from ..db import get_conn

    row = get_conn().execute("SELECT * FROM profiles WHERE id=?", (pid,)).fetchone()
    if row is None:
        raise api_error(404, "not_found", "Profile not found.")
    return dict(row)


def _read_text_or_404(pid: str) -> str:
    from ..db import get_conn

    row = _profile_or_404(pid)
    path = row["file_path"]
    try:
        return open(path, encoding="utf-8").read()  # noqa: SIM115 — scoped helper
    except OSError:
        raise api_error(410, "file_missing", "Profile file is missing on disk.")  # noqa: B904


# --- admin share endpoints ------------------------------------------------------

@router.post("/profiles/{pid}/share")
def create_share(pid: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    body = body or {}
    _profile_or_404(pid)
    link = sharelinks.create(
        pid,
        expires_hours=body.get("expires_hours", sharelinks.DEFAULT_HOURS),
        one_time=bool(body.get("one_time", False)),
    )
    audit.insert("share.create", "profiles", target=link["profile_id"],
                 detail={"token": link["token"], "one_time": link["one_time"],
                         "expires_at": link["expires_at"]})
    return {
        "token": link["token"],
        "url": f"/s/{link['token']}",
        "expires_at": link["expires_at"],
        "one_time": bool(link["one_time"]),  # raw column is 0/1 — return real JSON booleans
        "status": "active",
    }


@router.get("/profiles/{pid}/shares")
def list_shares(pid: str) -> dict[str, Any]:
    _profile_or_404(pid)
    return {"links": sharelinks.list_for(pid)}


@router.delete("/shares/{token}")
def revoke_share(token: str) -> dict[str, Any]:
    link = sharelinks.get(token)
    if link is None:
        raise api_error(404, "not_found", "Share link not found.")
    sharelinks.revoke(token)
    event_id = audit.insert("share.revoke", "profiles", target=token)
    undo_token = undo_store.register(
        "profiles", "share.revoke",
        lambda: sharelinks.unrevoke(token), event_id,
    )
    return {"ok": True, "undo_token": undo_token}


@router.get("/profiles/{pid}/qr")
def profile_qr(pid: str, mode: str = "url", request: Request = None) -> Response:
    """QR as SVG. url mode encodes a share URL; embed encodes the whole config."""
    import segno

    _profile_or_404(pid)
    try:
        if mode == "embed":
            qr = segno.make(_read_text_or_404(pid), error="l")
        else:
            links = sharelinks.list_for(pid)
            active = [l for l in links if l["status"] == "active"]
            token = active[0]["token"] if active else sharelinks.create(pid)["token"]
            base = str(request.base_url).rstrip("/") if request else ""
            qr = segno.make(f"{base}/s/{token}", error="m")
        svg = qr.svg_inline(scale=6, border=2, dark="#1f2430", light="#ffffff").encode()
    except Exception as exc:  # noqa: BLE001 — oversized payload etc.
        raise api_error(409, "qr_failed",
                        f"Could not build this QR: {exc}. Use URL mode.")  # noqa: B904
    return Response(content=svg, media_type="image/svg+xml")

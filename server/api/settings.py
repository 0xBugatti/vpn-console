"""API: settings — operability + credential rotation (US12).

The Tailscale token is env-preferred (research D7); whatever is configured is
ALREADY masked at GET — after initial entry the full value never crosses the
wire again. Danger-zone endpoints are typed-confirm tier (constitution III).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Request

from .. import audit, auth
from ..db import get_conn, get_setting, set_setting
from ..settings import CONFIG, hash_password, verify_password
from . import common
from .schemas import api_error, require_typed

router = APIRouter()

THEMES = ("light", "dark", "system")


def _mask(token: str) -> str:
    return f"••••{token[-4:]}" if len(token) >= 4 else "••••"


def _token_view() -> dict[str, str]:
    if CONFIG.ts_token_env:
        return {"ts_token": _mask(CONFIG.ts_token_env), "ts_token_source": "env"}
    stored = get_setting("ts_token") or ""
    return {"ts_token": _mask(stored) if stored else "", "ts_token_source": "stored" if stored else ""}


@router.get("/settings")
def get_settings() -> dict[str, Any]:
    return {
        **_token_view(),
        "tailnet_name": get_setting("tailnet_name") or CONFIG.tailnet,
        "poll_status_s": int(get_setting("poll_status_s") or CONFIG.poll_status_s),
        "poll_lists_s": int(get_setting("poll_lists_s") or CONFIG.poll_lists_s),
        "theme": get_setting("theme") or "system",
    }


@router.put("/settings")
def put_settings(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    changed: dict[str, Any] = {}
    if "poll_status_s" in body:
        v = body["poll_status_s"]
        if not isinstance(v, int) or not (2 <= v <= 600):
            raise api_error(422, "bad_interval", "poll_status_s must be 2–600 seconds.")
        set_setting("poll_status_s", str(v))
        changed["poll_status_s"] = v
    if "poll_lists_s" in body:
        v = body["poll_lists_s"]
        if not isinstance(v, int) or not (10 <= v <= 3600):
            raise api_error(422, "bad_interval", "poll_lists_s must be 10–3600 seconds.")
        set_setting("poll_lists_s", str(v))
        changed["poll_lists_s"] = v
    if "theme" in body:
        if body["theme"] not in THEMES:
            raise api_error(422, "bad_theme", "theme must be light, dark or system.")
        set_setting("theme", body["theme"])
        changed["theme"] = body["theme"]
    if "ts_token" in body:
        token = str(body["ts_token"] or "").strip()
        if token:
            set_setting("ts_token", token)
            changed["ts_token"] = _mask(token)  # masked even in the audit trail
        else:
            with get_conn() as c:
                c.execute("DELETE FROM settings WHERE key='ts_token'")
            changed["ts_token"] = "(cleared)"
    if changed:
        audit.insert("settings.update", "settings", detail=changed)
    return get_settings()


@router.post("/settings/password")
def change_password(request: Request, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
    current = str(body.get("current") or "")
    nxt = str(body.get("next") or "")
    if not current:
        raise api_error(422, "missing_current", "Enter the current password to confirm this change.")
    if len(nxt) < 8:
        raise api_error(422, "weak_password", "The new password needs at least 8 characters.")
    stored = get_setting("admin_password_hash") or ""
    if not stored or not verify_password(current, stored):
        raise api_error(401, "bad_password", "Current password is wrong — nothing was changed.")
    set_setting("admin_password_hash", hash_password(nxt))
    killed = auth.revoke_all_except(auth.current_session_token(request))
    audit.insert("settings.password", "settings", outcome="ok",
                 detail={"sessions_revoked": killed})
    return {"ok": True, "sessions_revoked": killed}


@router.post("/settings/test-ts")
def test_ts() -> dict[str, Any]:
    """Reachability + scope probe (research D3) — never returns the credential."""
    try:
        data = common.cloud().tailnet()
    except Exception as exc:  # noqa: BLE001 — the failure IS the answer here
        return {"ok": False, "error": str(exc)[:300]}
    return {
        "ok": True,
        "tailnet": data.get("name") or CONFIG.tailnet,
        "magic_dns": bool(data.get("magicDNSEnabled")),
        "source": _token_view()["ts_token_source"],
    }


def _wipe_profiles() -> int:
    n = 0
    with get_conn() as c:
        rows = c.execute("SELECT id FROM profiles").fetchall()
    for row in rows:
        path = CONFIG.profiles_dir / f"{row['id']}.ovpn"
        if path.is_file():
            path.unlink(missing_ok=True)
        with get_conn() as c:
            c.execute("DELETE FROM profiles WHERE id=?", (row["id"],))  # share_links cascade
        n += 1
    return n


@router.post("/settings/wipe-profiles")
def wipe_profiles(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    require_typed(body, "wipe-profiles", "profile wipe")
    try:
        n = _wipe_profiles()
    except Exception as exc:  # noqa: BLE001 — audited boundary (SC-004)
        audit.insert("settings.wipe-profiles", "settings", outcome="failed",
                     detail={"error": str(exc)[:300]})
        raise api_error(500, "wipe_failed", f"The wipe failed partway: {exc}") from exc
    audit.insert("settings.wipe-profiles", "settings", outcome="ok",
                 detail={"profiles_removed": n})
    return {"ok": True, "profiles_removed": n}


@router.post("/settings/reset-policy")
def reset_policy(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    require_typed(body, "reset-policy", "policy reset")
    row = get_conn().execute(
        "SELECT text FROM policy_versions ORDER BY id DESC LIMIT 1").fetchone()
    if row is None:
        raise api_error(409, "nothing_to_reset",
                        "No applied policy version is recorded — nothing to reset to.")
    from . import acl as acl_api  # the draft lives in that module's memory

    try:
        common.cloud().put_acl_text(row["text"])
    except Exception as exc:  # noqa: BLE001 — audited boundary (SC-004)
        audit.insert("settings.reset-policy", "settings", outcome="failed",
                     detail={"error": str(exc)[:300]})
        raise api_error(502, "action_failed", f"Tailscale rejected the reset: {exc}") from exc
    common.cloud_cache().invalidate("acl")
    acl_api._draft = None
    audit.insert("settings.reset-policy", "settings", outcome="ok",
                 detail={"bytes": len(row["text"])})
    return {"ok": True}

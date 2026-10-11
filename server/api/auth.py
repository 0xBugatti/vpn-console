"""US1 — the single gate (FR-001, SC-001)."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel

from .. import audit, auth, loginlink
from ..db import get_setting, set_setting
from ..settings import CONFIG, hash_password, verify_password
from .schemas import api_error

router = APIRouter()

INDEX_HTML = Path(__file__).resolve().parent.parent / "static" / "index.html"


class LoginBody(BaseModel):
    password: str


def ensure_admin_password() -> None:
    """First-run bootstrap: derive scrypt hash from env/file (research D7)."""
    if get_setting("admin_password_hash"):
        return
    if CONFIG.admin_password_env:
        set_setting("admin_password_hash", hash_password(CONFIG.admin_password_env))


@router.post("/auth/login")
def login(body: LoginBody, request: Request, response: Response):
    ip = request.client.host if request.client else "unknown"
    auth.login_limiter.check(ip)
    stored = get_setting("admin_password_hash") or ""
    if not stored or not verify_password(body.password, stored):
        auth.login_limiter.record_failure(ip)
        audit.insert("auth.login", "auth", target=ip, outcome="failed",
                     detail={"reason": "wrong password"})
        raise api_error(401, "bad_password", "Wrong password. Try again.")
    auth.login_limiter.reset(ip)
    token = auth.make_token()
    auth.set_session_cookie(response, token)
    audit.insert("auth.login", "auth", target=ip, outcome="ok")
    return {"ok": True}


@router.post("/auth/logout")
def logout(request: Request, response: Response):
    token = auth.current_session_token(request)
    if token:
        auth.revoke_token(token)
        audit.insert("auth.logout", "auth", outcome="ok")
    auth.clear_session_cookie(response)
    return {"ok": True}


@router.get("/auth/me")
def me(request: Request):
    token = auth.current_session_token(request)
    if not token or not auth.token_valid(token):
        raise api_error(401, "not_signed_in", "Sign in required.")
    return {"admin": True}


# --- login link: /login?token=… or /?token=… (root-level, see app.py) ---------

link_router = APIRouter()

_NO_LEAK = {
    "Referrer-Policy": "no-referrer",   # the token must not travel onward
    "Cache-Control": "no-store",
}


def _prefix(request: Request) -> str:
    """Mount prefix set by the reverse proxy (e.g. "/vpn"), empty for direct access."""
    return request.headers.get("x-forwarded-prefix", "").rstrip("/")


def _link_login(request: Request, token: str) -> RedirectResponse:
    ip = request.client.host if request.client else "unknown"
    prefix = _prefix(request)
    try:
        auth.login_limiter.check(ip)
    except HTTPException:
        audit.insert("auth.login", "auth", target=ip, outcome="failed",
                     detail={"method": "login_link", "reason": "rate limited"})
        return RedirectResponse(f"{prefix}/#/login", status_code=303, headers=_NO_LEAK)
    if not loginlink.verify(token):
        auth.login_limiter.record_failure(ip)
        audit.insert("auth.login", "auth", target=ip, outcome="failed",
                     detail={"method": "login_link", "reason": "invalid token"})
        return RedirectResponse(f"{prefix}/#/login", status_code=303, headers=_NO_LEAK)
    auth.login_limiter.reset(ip)
    # Redirect to a clean URL so the token leaves the address bar and history.
    response = RedirectResponse(f"{prefix}/#/overview", status_code=303, headers=_NO_LEAK)
    auth.set_session_cookie(response, auth.make_token())
    audit.insert("auth.login", "auth", target=ip, outcome="ok", detail={"method": "login_link"})
    return response


@link_router.get("/login", include_in_schema=False)
def login_link(request: Request, token: str = ""):
    return _link_login(request, token)


@link_router.get("/", include_in_schema=False)
def root(request: Request, token: str = ""):
    if token:
        return _link_login(request, token)
    return FileResponse(INDEX_HTML)

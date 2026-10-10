"""US1 — the single gate (FR-001, SC-001)."""
from __future__ import annotations

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from .. import audit, auth
from ..db import get_setting, set_setting
from ..settings import CONFIG, hash_password, verify_password
from .schemas import api_error

router = APIRouter()


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

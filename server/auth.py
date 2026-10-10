"""Single-admin session auth (FR-001, research D7).

HMAC-signed session cookie, in-memory revocation + per-IP login rate limiting.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable

from fastapi import HTTPException, Request, Response

from .settings import CONFIG

COOKIE_NAME = "vc_session"
SESSION_TTL = 7 * 24 * 3600
RATE_LIMIT_FAILURES = 5
RATE_LIMIT_WINDOW = 60.0


def _sign(payload: str) -> str:
    return hmac.new(CONFIG.session_secret, payload.encode(), hashlib.sha256).hexdigest()


def make_token(expires: int | None = None) -> str:
    expires = expires or int(time.time()) + SESSION_TTL
    nonce = secrets.token_urlsafe(9)  # unique per login: same-second logins must
    payload = f"{expires}.{nonce}"    # not share (or revoke) one session token
    token = f"v1.{payload}.{_sign(payload)}"
    _issued.add(token)
    return token


def token_valid(token: str) -> bool:
    parts = token.split(".")
    if len(parts) != 4:
        return False
    version, expires_s, nonce, mac = parts
    try:
        expires = int(expires_s)
    except ValueError:
        return False
    if version != "v1" or expires < time.time():
        return False
    if not hmac.compare_digest(mac, _sign(f"{expires}.{nonce}")):
        return False
    if token in _revoked:  # signed-out or post-password-change sessions
        return False
    return True


_revoked: set[str] = set()
_issued: set[str] = set()


def revoke_token(token: str) -> None:
    _revoked.add(token)


def revoke_all_except(keep: str | None) -> int:
    """Kill every live session except `keep` (password rotation, US12).
    Same in-memory lifetime as _revoked — a restart ends all sessions anyway."""
    killed = 0
    for token in list(_issued):
        if token != keep:
            _revoked.add(token)
            killed += 1
    _issued.clear()
    if keep:
        _issued.add(keep)
    return killed


def current_session_token(request: Request) -> str | None:
    return request.cookies.get(COOKIE_NAME)


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_TTL,
        httponly=True,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


async def require_admin(request: Request) -> None:
    """Dependency guarding every API router (SC-001)."""
    token = current_session_token(request)
    if not token or not token_valid(token):
        raise HTTPException(status_code=401, detail="not signed in")


class LoginRateLimiter:
    """5 failures/min/remote-addr → 429 (research D7)."""

    def __init__(self) -> None:
        self._failures: dict[str, deque[float]] = defaultdict(deque)

    def check(self, ip: str) -> None:
        fails = self._failures[ip]
        now = time.monotonic()
        while fails and now - fails[0] > RATE_LIMIT_WINDOW:
            fails.popleft()
        if len(fails) >= RATE_LIMIT_FAILURES:
            raise HTTPException(status_code=429, detail="too many attempts; wait a minute")

    def record_failure(self, ip: str) -> None:
        self._failures[ip].append(time.monotonic())

    def reset(self, ip: str) -> None:
        self._failures.pop(ip, None)

    def reset_all(self) -> None:
        self._failures.clear()


login_limiter = LoginRateLimiter()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"

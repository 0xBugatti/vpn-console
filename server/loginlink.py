"""Login link: a URL token that signs the admin in (owner request, 2026-10-11).

A separate secret from the password, so a leaked link never reveals the
password and can be revoked on its own. Off until generated in Settings
(or set via VPNCONSOLE_LOGIN_TOKEN). Only a SHA-256 digest is stored: the
token is 256 random bits, so a plain digest is enough and lookups stay
constant-time via hmac.compare_digest.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import secrets

from .db import get_conn, get_setting, set_setting

SETTING_KEY = "login_link"
ENV_VAR = "VPNCONSOLE_LOGIN_TOKEN"
MIN_ENV_LENGTH = 24


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _stored() -> dict | None:
    raw = get_setting(SETTING_KEY)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) and data.get("sha256") else None


def _env_token() -> str:
    token = os.environ.get(ENV_VAR, "").strip()
    return token if len(token) >= MIN_ENV_LENGTH else ""


def generate() -> str:
    """Create (or replace) the stored link token; the plain token is returned once."""
    token = secrets.token_urlsafe(32)
    created = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    set_setting(SETTING_KEY, json.dumps({"sha256": _digest(token), "created_at": created}))
    return token


def revoke() -> bool:
    if not _stored():
        return False
    with get_conn() as c:
        c.execute("DELETE FROM settings WHERE key=?", (SETTING_KEY,))
    return True


def status() -> dict:
    stored = _stored()
    return {
        "enabled": bool(stored) or bool(_env_token()),
        "created_at": (stored or {}).get("created_at", ""),
        "env": bool(_env_token()),
    }


def verify(token: str) -> bool:
    if not token:
        return False
    ok = False
    stored = _stored()
    if stored:
        ok |= hmac.compare_digest(_digest(token), stored["sha256"])
    env = _env_token()
    if env:
        ok |= hmac.compare_digest(_digest(token), _digest(env))
    return ok

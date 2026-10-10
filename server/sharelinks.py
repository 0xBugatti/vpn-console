"""Share links (US3, FR-022..FR-028): time-boxed, optionally one-time.

Tokens are plaintext by owner decision (Principle II). Status is derived on
read: active | expired | used | revoked — never stored as truth.
"""
from __future__ import annotations

import datetime as dt
import secrets

from .db import get_conn

DEFAULT_HOURS = 24
MAX_HOURS = 168  # one week


class ShareError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(d: dt.datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def create(profile_id: str, expires_hours: float = DEFAULT_HOURS,
           one_time: bool = False) -> dict:
    hours = min(max(float(expires_hours or DEFAULT_HOURS), 0.1), MAX_HOURS)
    token = secrets.token_urlsafe(16)  # 22 chars, url-safe
    get_conn().execute(
        "INSERT INTO share_links(token, profile_id, created_at, expires_at, one_time)"
        " VALUES(?,?,?,?,?)",
        (token, profile_id, _iso(_now()), _iso(_now() + dt.timedelta(hours=hours)),
         int(bool(one_time))),
    )
    return get(token)


def get(token: str) -> dict | None:
    row = get_conn().execute(
        "SELECT * FROM share_links WHERE token=?", (token,)
    ).fetchone()
    return dict(row) if row else None


def list_for(profile_id: str) -> list[dict]:
    rows = get_conn().execute(
        "SELECT * FROM share_links WHERE profile_id=? ORDER BY created_at DESC",
        (profile_id,),
    ).fetchall()
    return [view(dict(r)) for r in rows]


def view(link: dict) -> dict:
    out = dict(link)
    out["one_time"] = bool(link["one_time"])
    if link["revoked_at"]:
        out["status"] = "revoked"
    elif link["one_time"] and link["used_count"] > 0:
        out["status"] = "used"
    elif link["expires_at"] <= _iso(_now()):
        out["status"] = "expired"
    else:
        out["status"] = "active"
    return out


def resolve(token: str) -> tuple[dict, dict]:
    """Token -> (profile row, link row) or raises ShareError (FR-025)."""
    link = get(token)
    if link is None:
        raise ShareError("not_found", "This link does not exist.")
    view(link)
    if link["revoked_at"]:
        raise ShareError("revoked", "This link was revoked.")
    if link["one_time"] and link["used_count"] > 0:
        raise ShareError("used", "This one-time link was already used.")
    if link["expires_at"] <= _iso(_now()):
        raise ShareError("expired", "This link has expired.")
    profile = get_conn().execute(
        "SELECT * FROM profiles WHERE id=?", (link["profile_id"],)
    ).fetchone()
    if profile is None:
        raise ShareError("not_found", "The profile behind this link was deleted.")
    return dict(profile), link


def mark_used(token: str) -> None:
    get_conn().execute(
        "UPDATE share_links SET used_count = used_count + 1 WHERE token=?", (token,)
    )


def revoke(token: str) -> bool:
    if get(token) is None:
        return False
    get_conn().execute(
        "UPDATE share_links SET revoked_at=? WHERE token=?", (_iso(_now()), token)
    )
    return True


def unrevoke(token: str) -> None:
    """Undo counterpart — restore the link to its pre-revoke state."""
    get_conn().execute("UPDATE share_links SET revoked_at=NULL WHERE token=?", (token,))

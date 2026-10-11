"""Login link: /login?token=… signs the admin in (owner request, 2026-10-11)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from server import auth, db, loginlink
from server.app import app


@pytest.fixture(autouse=True)
def no_link(monkeypatch):
    """Each test starts without a stored link, env token or rate-limit history."""
    monkeypatch.delenv(loginlink.ENV_VAR, raising=False)
    db.init_db()  # the fixture can run before the app lifespan creates tables
    loginlink.revoke()
    auth.login_limiter.reset_all()
    yield
    loginlink.revoke()
    auth.login_limiter.reset_all()


def _anon():
    return TestClient(app, follow_redirects=False)


def _create(authed) -> dict:
    r = authed.post("/api/settings/login-link", json={"confirm": True})
    assert r.status_code == 200, r.text
    return r.json()


def test_off_until_generated(authed):
    assert authed.get("/api/settings").json()["login_link"]["enabled"] is False
    with _anon() as c:
        r = c.get("/login", params={"token": "anything-at-all-anything-at-all"})
        assert r.status_code == 303 and r.headers["location"] == "/#/login"
        assert auth.COOKIE_NAME not in r.cookies


def test_generate_requires_confirm(authed):
    r = authed.post("/api/settings/login-link", json={})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "confirm_required"


def test_link_signs_in_and_strips_token(authed):
    body = _create(authed)
    assert body["url"].endswith(f"/login?token={body['token']}")
    assert body["enabled"] is True and body["created_at"]
    with _anon() as c:
        r = c.get("/login", params={"token": body["token"]})
        assert r.status_code == 303
        assert r.headers["location"] == "/#/overview"     # token gone from the URL
        assert r.headers["referrer-policy"] == "no-referrer"
        assert r.headers["cache-control"] == "no-store"
        assert auth.COOKIE_NAME in r.cookies
        assert c.get("/api/auth/me").status_code == 200     # session works
        assert c.get("/api/overview").status_code == 200


def test_root_path_accepts_token_and_still_serves_spa(authed):
    token = _create(authed)["token"]
    with _anon() as c:
        r = c.get("/", params={"token": token})
        assert r.status_code == 303 and r.headers["location"] == "/#/overview"
        page = c.get("/")
        assert page.status_code == 200 and "<div id=\"app\">" in page.text


def test_wrong_token_rejected_audited_and_rate_limited(authed):
    _create(authed)
    with _anon() as c:
        for _ in range(auth.RATE_LIMIT_FAILURES):
            r = c.get("/login", params={"token": "wrong-token-wrong-token-wrong"})
            assert r.headers["location"] == "/#/login"
            assert auth.COOKIE_NAME not in r.cookies
        assert c.get("/api/auth/me").status_code == 401
    events = authed.get("/api/audit", params={"limit": 50}).json()["entries"]
    failed = [e for e in events if e["action"] == "auth.login" and e["outcome"] == "failed"]
    assert failed and failed[0]["detail"]["method"] == "login_link"


def test_token_never_written_to_audit(authed):
    token = _create(authed)["token"]
    with _anon() as c:
        c.get("/login", params={"token": token})
    dump = authed.get("/api/audit", params={"limit": 100}).text
    assert token not in dump


def test_regenerate_replaces_and_revoke_disables(authed):
    first = _create(authed)["token"]
    second = _create(authed)["token"]
    assert first != second
    with _anon() as c:
        assert c.get("/login", params={"token": first}).headers["location"] == "/#/login"
        assert c.get("/login", params={"token": second}).headers["location"] == "/#/overview"
    r = authed.request("DELETE", "/api/settings/login-link", json={"confirm": True})
    assert r.status_code == 200 and r.json()["enabled"] is False
    with _anon() as c:
        assert c.get("/login", params={"token": second}).headers["location"] == "/#/login"


def test_env_token_works_and_short_env_ignored(monkeypatch):
    monkeypatch.setenv(loginlink.ENV_VAR, "short")
    with _anon() as c:
        assert c.get("/login", params={"token": "short"}).headers["location"] == "/#/login"
    env_token = "e" * 32
    monkeypatch.setenv(loginlink.ENV_VAR, env_token)
    with _anon() as c:
        assert c.get("/login", params={"token": env_token}).headers["location"] == "/#/overview"

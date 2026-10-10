"""US1 — the single gate (SC-001): nothing reachable signed out; rate-limited."""
from __future__ import annotations

SECTIONS = ["/api/overview", "/api/profiles", "/api/devices", "/api/acl", "/api/node",
            "/api/exposures", "/api/services", "/api/logs", "/api/audit", "/api/settings",
            "/api/health"]


def test_signed_out_cannot_reach_any_section(client):
    for path in SECTIONS:
        r = client.get(path)
        assert r.status_code == 401, f"{path} → {r.status_code}"
    assert client.get("/api/auth/me").status_code == 401


def test_wrong_password_denied_and_audited(authed):
    r = authed.post("/api/auth/login", json={"password": "nope"})
    assert r.status_code == 401
    body = r.json()["error"]
    assert body["code"] == "bad_password"
    rows, _ = __import__("server.audit", fromlist=["query"]).query(action="auth.login")
    assert any(e["outcome"] == "failed" for e in rows)


def test_correct_password_signs_in(client):
    r = client.post("/api/auth/login", json={"password": "test-password-123"})
    assert r.status_code == 200
    assert "vc_session" in r.cookies
    assert client.get("/api/auth/me").json()["admin"] is True


def test_signout_ends_session(authed):
    assert authed.get("/api/auth/me").status_code == 200
    r = authed.post("/api/auth/logout")
    assert r.status_code == 200
    assert authed.get("/api/auth/me").status_code == 401


def test_rate_limit_after_five_failures(client):
    for _ in range(5):
        client.post("/api/auth/login", json={"password": "bad"})
    r = client.post("/api/auth/login", json={"password": "test-password-123"})
    assert r.status_code == 429  # even the correct password is refused now


def test_static_shell_served_signed_out(client):
    """The HTML shell is public; every API behind it is not (data is what matters)."""
    r = client.get("/")
    assert r.status_code == 200
    assert b"app.js" in r.content

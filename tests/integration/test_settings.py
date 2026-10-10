"""US12 — settings integration (T068): password rotation + session invalidation,
masked credential, test-ts reachability, danger-zone typed confirm.
"""
from __future__ import annotations

import json

NEW_PASS = "brand-new-pass-9"


def _settings(authed):
    return authed.get("/api/settings").json()


def test_get_masks_token_and_never_leaks_full_value(authed):
    from server.db import set_setting

    token = "tskey-auth-secret123456abcdef-CNTRL"
    set_setting("ts_token", token)
    blob = json.dumps(_settings(authed))
    assert token not in blob
    assert "tskey" not in blob
    body = _settings(authed)
    assert body["ts_token"] == "••••" + token[-4:]
    assert body["ts_token_source"] == "stored"


def test_get_defaults_without_token(authed):
    from server.db import get_conn

    with get_conn() as c:  # earlier tests may have stored one — isolate
        c.execute("DELETE FROM settings WHERE key='ts_token'")
    body = _settings(authed)
    assert body["ts_token"] == ""
    assert body["theme"] in ("light", "dark", "system")
    assert body["poll_status_s"] > 0 and body["poll_lists_s"] > 0


def test_put_updates_intervals_theme_and_audits(authed):
    r = authed.put("/api/settings", json={"poll_status_s": 20, "poll_lists_s": 90,
                                          "theme": "dark"})
    assert r.status_code == 200, r.text
    body = _settings(authed)
    assert body["poll_status_s"] == 20
    assert body["poll_lists_s"] == 90
    assert body["theme"] == "dark"
    actions = [e["action"] for e in authed.get("/api/audit", params={"limit": 100}).json()["entries"]]
    assert "settings.update" in actions
    r = authed.put("/api/settings", json={"theme": "neon"})
    assert r.status_code == 422  # enum kept honest


def test_password_change_requires_current(authed):
    r = authed.post("/api/settings/password", json={"next": NEW_PASS})
    assert r.status_code in (400, 422)  # current missing
    r = authed.post("/api/settings/password", json={"current": "wrong-pass", "next": NEW_PASS})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "bad_password"
    # the store is untouched
    r = authed.post("/api/auth/login", json={"password": "test-password-123"})
    assert r.status_code == 200


def test_password_change_audits_keeps_current_kills_others(client):
    from server import auth

    auth.login_limiter.reset_all()
    r_a = client.post("/api/auth/login", json={"password": "test-password-123"})
    r_b = client.post("/api/auth/login", json={"password": "test-password-123"})
    a = r_a.cookies.get("vc_session")
    b = r_b.cookies.get("vc_session")
    assert a and b and a != b  # two distinct live sessions

    # rotate from session A — A must survive, B must die
    r = client.post("/api/settings/password",
                    json={"current": "test-password-123", "next": NEW_PASS},
                    cookies={"vc_session": a})
    assert r.status_code == 200, r.text

    assert client.get("/api/auth/me", cookies={"vc_session": a}).status_code == 200
    assert client.get("/api/auth/me", cookies={"vc_session": b}).status_code == 401

    # future sign-ins: old fails, new works
    r = client.post("/api/auth/login", json={"password": "test-password-123"})
    assert r.status_code == 401
    r = client.post("/api/auth/login", json={"password": NEW_PASS})
    assert r.status_code == 200

    actions = [e["action"] for e in
               client.get("/api/audit", params={"limit": 100},
                          cookies={"vc_session": a}).json()["entries"]]
    assert "settings.password" in actions

    # rotate back so other tests keep the conftest password
    r = client.post("/api/settings/password", json={"current": NEW_PASS, "next": "test-password-123"},
                    cookies={"vc_session": a})
    assert r.status_code == 200


def test_test_ts_reports_scope_via_fake(authed):
    r = authed.post("/api/settings/test-ts")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["tailnet"]  # fake reports the tailnet name
    assert "magic_dns" in body


def test_danger_zone_needs_typed_confirm(authed, ovpn_factory):
    r = authed.post("/api/settings/wipe-profiles", json={})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "typed_confirm_required"

    r = authed.post("/api/settings/wipe-profiles", json={"typed_confirm": "wipe-profiles"})
    assert r.status_code == 200, r.text
    assert authed.get("/api/profiles").json()["profiles"] == []
    actions = [e["action"] for e in authed.get("/api/audit", params={"limit": 100}).json()["entries"]]
    assert "settings.wipe-profiles" in actions


def test_wipe_empties_store_and_drops_links(authed, ovpn_factory):
    from server import sharelinks

    imp = authed.post("/api/profiles/import",
                      files={"files": ("wipe-me.ovpn", ovpn_factory("wipe-me"), "text/plain")}).json()
    pid = imp["results"][0]["id"]
    sharelinks.create(pid)
    assert authed.get("/api/profiles").json()["profiles"]

    r = authed.post("/api/settings/wipe-profiles", json={"typed_confirm": "wipe-profiles"})
    assert r.status_code == 200
    assert authed.get("/api/profiles").json()["profiles"] == []
    assert sharelinks.list_for(pid) == []  # cascaded with the profile


def test_reset_policy_restores_last_applied(authed, fakes):
    from server.db import get_conn

    with get_conn() as c:  # ACL tests (US7) may have applied versions — isolate
        c.execute("DELETE FROM policy_versions")

    # no applied version yet → loud no-op
    r = authed.post("/api/settings/reset-policy", json={"typed_confirm": "reset-policy"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "nothing_to_reset"

    version_text = '{"acls": [{"action": "accept", "src": ["*"], "dst": ["*:*"]}]}'
    with get_conn() as c:
        c.execute("INSERT INTO policy_versions(text, applied_at, note) VALUES (?,?,?)",
                  (version_text, "2026-01-01T00:00:00Z", "seed"))
    # a stray draft the reset must discard
    authed.put("/api/acl/draft", json={"text": '{"acls": []}'})
    fakes["cloud"].acl_text = '{"acls": []}  # drifted'

    r = authed.post("/api/settings/reset-policy", json={"typed_confirm": "reset-policy"})
    assert r.status_code == 200, r.text
    assert fakes["cloud"].acl_text == version_text  # tailnet restored to last applied
    body = authed.get("/api/acl").json()
    assert body["draft"] is None
    assert body["applied_text"] == version_text

    with get_conn() as c:
        n = c.execute("SELECT COUNT(*) AS n FROM policy_versions").fetchone()["n"]
    assert n == 1  # reset does not stack a version of its own

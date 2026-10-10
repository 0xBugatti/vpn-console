"""US3 — share links + QR (T030; FR-022..FR-028, documented /s/ auth exception)."""
from __future__ import annotations

import datetime as dt

from server.db import get_conn


def _mkprofile(authed, ovpn_factory, name: str = "corp") -> str:
    r = authed.post(
        "/api/profiles/import",
        files=[("files", (f"{name}.ovpn", ovpn_factory(cn=name).encode(), "application/octet-stream"))],
    )
    return r.json()["results"][0]["id"]


def test_create_link_and_public_download(authed, fresh_db, ovpn_factory):
    pid = _mkprofile(authed, ovpn_factory)
    r = authed.post(f"/api/profiles/{pid}/share", json={"expires_hours": 24})
    assert r.status_code == 200, r.text
    link = r.json()
    assert link["url"].startswith("/s/") and len(link["token"]) >= 20
    assert link["one_time"] in (False, 0)

    # documented exception: the /s/{token} route requires NO session (FR-027)
    anon_download = authed.get(link["url"] + "/download")
    assert anon_download.status_code == 200
    page = authed.get(link["url"])
    assert page.status_code == 200
    assert "Download" in page.text


def test_one_time_link_dies_after_use(authed, fresh_db, ovpn_factory):
    pid = _mkprofile(authed, ovpn_factory, "onetime")
    link = authed.post(f"/api/profiles/{pid}/share",
                       json={"expires_hours": 1, "one_time": True}).json()
    first = authed.get(link["url"] + "/download")
    assert first.status_code == 200
    second = authed.get(link["url"] + "/download")
    assert second.status_code == 410


def test_expired_link_is_gone(authed, fresh_db, ovpn_factory):
    pid = _mkprofile(authed, ovpn_factory, "shortlived")
    link = authed.post(f"/api/profiles/{pid}/share",
                       json={"expires_hours": 1, "one_time": False}).json()
    get_conn().execute("UPDATE share_links SET expires_at=? WHERE token=?",
                       ("2020-01-01T00:00:00Z", link["token"]))
    r = authed.get(link["url"] + "/download")
    assert r.status_code == 410


def test_revoke(authed, fresh_db, ovpn_factory):
    pid = _mkprofile(authed, ovpn_factory, "revokeme")
    link = authed.post(f"/api/profiles/{pid}/share", json={"expires_hours": 1}).json()
    r = authed.delete(f"/api/shares/{link['token']}")
    assert r.status_code == 200
    assert authed.get(link["url"] + "/download").status_code == 410

    # tier-1 friction: revoke is undoable within the window
    undo = authed.post(f"/api/undo/{r.json()['undo_token']}")
    assert undo.status_code == 200, undo.text
    assert authed.get(f"/api/profiles/{pid}/shares").json()["links"][0]["status"] == "active"
    assert authed.get(link["url"] + "/download").status_code == 200


def test_share_requires_confirm_on_delete_profile_side(authed, fresh_db, ovpn_factory):
    """Shares listed per profile; profile delete cascades (covered) + list works."""
    pid = _mkprofile(authed, ovpn_factory, "listed")
    authed.post(f"/api/profiles/{pid}/share", json={"expires_hours": 2})
    authed.post(f"/api/profiles/{pid}/share", json={"expires_hours": 2, "one_time": True})
    links = authed.get(f"/api/profiles/{pid}/shares").json()["links"]
    assert len(links) == 2
    assert {l["status"] for l in links} == {"active"}


def test_qr_svg_url_mode(authed, fresh_db, ovpn_factory):
    pid = _mkprofile(authed, ovpn_factory, "qred")
    r = authed.get(f"/api/profiles/{pid}/qr")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg+xml")
    assert b"<svg" in r.content


def test_qr_embed_mode_and_capacity(authed, fresh_db, ovpn_factory):
    pid = _mkprofile(authed, ovpn_factory, "embed")
    r = authed.get(f"/api/profiles/{pid}/qr", params={"mode": "embed"})
    assert r.status_code == 200
    assert b"<svg" in r.content


def test_share_expiry_default_24h(authed, fresh_db, ovpn_factory):
    pid = _mkprofile(authed, ovpn_factory, "defexp")
    link = authed.post(f"/api/profiles/{pid}/share", json={}).json()
    expires = dt.datetime.fromisoformat(link["expires_at"].replace("Z", "+00:00"))
    hours = (expires - dt.datetime.now(dt.timezone.utc)).total_seconds() / 3600
    assert 23 < hours <= 24.1

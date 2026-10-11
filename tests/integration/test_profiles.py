"""US2 — profiles import/list/mutate/undo (T023; FR-010..FR-021)."""
from __future__ import annotations

import datetime as dt

import pytest


def _upload(files: list[tuple[str, bytes]]) -> list[dict]:
    return [("files", (name, body, "application/octet-stream")) for name, body in files]


def _import(authed, *pairs: tuple[str, bytes]):
    return authed.post("/api/profiles/import", files=_upload(list(pairs)))


def test_multi_file_import_creates_rows(authed, fresh_db, ovpn_factory):
    r = _import(
        authed,
        ("alpha.ovpn", ovpn_factory(cn="alpha").encode()),
        ("beta.ovpn", ovpn_factory(cn="beta").encode()),
    )
    assert r.status_code == 200, r.text
    results = r.json()["results"]
    assert [x["status"] for x in results] == ["imported", "imported"]

    rows = authed.get("/api/profiles").json()["profiles"]
    assert sorted(p["name"] for p in rows) == ["alpha", "beta"]
    assert all(p["status"] == "Valid" for p in rows)


def test_import_reports_parse_error(authed, fresh_db):
    r = _import(authed, ("broken.ovpn", b"client\ndev tun\n"))
    body = r.json()["results"][0]
    assert body["status"] == "imported"  # stored, not dropped
    assert body["parse_error"]
    row = authed.get("/api/profiles").json()["profiles"][0]
    assert row["status"] == "Parse error"


def test_duplicate_sha_flags_and_resolves(authed, fresh_db, ovpn_factory):
    body = ovpn_factory(cn="dup").encode()
    first = _import(authed, ("corp.ovpn", body)).json()["results"][0]
    dup = _import(authed, ("corp-copy.ovpn", body)).json()["results"][0]
    assert dup["status"] == "duplicate"
    assert dup["duplicate_of"] == first["id"]
    assert dup["stash"]

    # Keep both -> second row with disambiguated name
    r = authed.post("/api/profiles/import/confirm",
                    json={"stash": dup["stash"], "action": "keep_both"})
    assert r.status_code == 200, r.text
    names = [p["name"] for p in authed.get("/api/profiles").json()["profiles"]]
    assert len(names) == 2 and "corp-copy" in names

    # Replace -> target content updated, no extra row
    dup2 = _import(authed, ("again.ovpn", body)).json()["results"][0]
    r = authed.post("/api/profiles/import/confirm",
                    json={"stash": dup2["stash"], "action": "replace",
                          "target": dup2["duplicate_of"]})
    assert r.status_code == 200, r.text
    assert len(authed.get("/api/profiles").json()["profiles"]) == 2


def test_patch_config_keeps_previous_and_returns_undo(authed, fresh_db, ovpn_factory):
    pid = _import(authed, ("corp.ovpn", ovpn_factory(cn="corp").encode())).json()["results"][0]["id"]
    new_text = ovpn_factory(cn="corp-v2")
    r = authed.patch(f"/api/profiles/{pid}", json={"config_text": new_text})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["profile"]["config_sha256"] != data["profile"].get("previous_sha256")
    undo_token = data["undo_token"]
    assert undo_token

    detail = authed.get(f"/api/profiles/{pid}").json()
    assert detail["config_text"] == new_text

    undo = authed.post(f"/api/undo/{undo_token}")
    assert undo.status_code == 200, undo.text
    assert authed.get(f"/api/profiles/{pid}").json()["config_text"] != new_text


def test_enable_toggle_undoable(authed, fresh_db, ovpn_factory):
    pid = _import(authed, ("corp.ovpn", ovpn_factory(cn="corp").encode())).json()["results"][0]["id"]
    r = authed.patch(f"/api/profiles/{pid}", json={"enabled": False})
    assert r.json()["profile"]["status"] == "Disabled"
    token = r.json()["undo_token"]

    undo = authed.post(f"/api/undo/{token}")
    assert undo.status_code == 200
    assert authed.get(f"/api/profiles/{pid}").json()["enabled"] is True


def test_revert_swaps_previous_back(authed, fresh_db, ovpn_factory):
    original = ovpn_factory(cn="corp")
    pid = _import(authed, ("corp.ovpn", original.encode())).json()["results"][0]["id"]
    authed.patch(f"/api/profiles/{pid}", json={"config_text": ovpn_factory(cn="corp-v2")})

    r = authed.post(f"/api/profiles/{pid}/revert")
    assert r.status_code == 200, r.text
    assert r.json()["profile"]["config_text"] == original


def test_revert_without_previous_conflicts(authed, fresh_db, ovpn_factory):
    pid = _import(authed, ("corp.ovpn", ovpn_factory().encode())).json()["results"][0]["id"]
    r = authed.post(f"/api/profiles/{pid}/revert")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "nothing_to_revert"


def test_delete_requires_confirm(authed, fresh_db, ovpn_factory):
    pid = _import(authed, ("corp.ovpn", ovpn_factory().encode())).json()["results"][0]["id"]
    r = authed.request("DELETE", f"/api/profiles/{pid}", json={})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "confirm_required"

    ok = authed.request("DELETE", f"/api/profiles/{pid}", json={"confirm": True})
    assert ok.status_code == 200
    assert authed.get("/api/profiles").json()["profiles"] == []


def test_bulk_delete_requires_typed_confirm(authed, fresh_db, ovpn_factory):
    ids = [
        _import(authed, (f"p{i}.ovpn", ovpn_factory(cn=f"p{i}").encode())).json()["results"][0]["id"]
        for i in range(2)
    ]
    r = authed.post("/api/profiles/bulk-delete", json={"ids": ids})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "typed_confirm_required"

    ok = authed.post("/api/profiles/bulk-delete", json={"ids": ids, "typed_confirm": "DELETE"})
    assert ok.status_code == 200
    assert ok.json()["deleted"] == 2


def test_search_tokens_and_negation(authed, fresh_db, ovpn_factory):
    office = ovpn_factory(cn="office-1", cipher="AES-256-GCM")
    home = ovpn_factory(cn="home-1", cipher="AES-128-GCM")
    _import(authed, ("office.ovpn", office.encode()), ("home.ovpn", home.encode()))
    rows = {p["name"]: p for p in authed.get("/api/profiles").json()["profiles"]}
    authed.patch(f"/api/profiles/{rows['office']['id']}", json={"tags": ["office"]})

    hit = authed.get("/api/profiles", params={"q": "tag:office"}).json()["profiles"]
    assert [p["name"] for p in hit] == ["office"]

    hit = authed.get("/api/profiles", params={"q": "cipher:AES-128-GCM"}).json()["profiles"]
    assert [p["name"] for p in hit] == ["home"]

    hit = authed.get("/api/profiles", params={"q": "server:vpn.example.net"}).json()["profiles"]
    assert len(hit) == 2  # both made by the same factory remote

    hit = authed.get("/api/profiles", params={"q": "!tag:office"}).json()["profiles"]
    assert [p["name"] for p in hit] == ["home"]


def test_oversize_rejected_with_clear_message(authed, fresh_db):
    big = b"client\n" + b"#" * (ovpn_cap() + 10)
    r = _import(authed, ("huge.ovpn", big))
    body = r.json()["results"][0]
    assert body["status"] == "error"
    assert "1 MiB" in body["message"]


def ovpn_cap() -> int:
    from server.ovpn import MAX_PROFILE_BYTES

    return MAX_PROFILE_BYTES


def test_download_serves_bytes_and_status_header(authed, fresh_db, ovpn_factory):
    old = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)
    text = ovpn_factory(cn="lapsed", expires=old)
    pid = _import(authed, ("lapsed.ovpn", text.encode())).json()["results"][0]["id"]

    r = authed.get(f"/api/profiles/{pid}/download")
    assert r.status_code == 200
    assert r.content == text.encode()
    assert r.headers["x-profile-status"] == "Expired"
    assert r.headers["content-disposition"].endswith('.ovpn"')


# --- system scan: host config dirs preview + guarded one-file import ---

@pytest.fixture
def scan_root(tmp_path, monkeypatch):
    from server.settings import CONFIG

    monkeypatch.setattr(CONFIG, "scan_dirs", str(tmp_path))
    return tmp_path


def test_scan_reports_new_and_imported(authed, fresh_db, scan_root, ovpn_factory):
    dup_bytes = ovpn_factory(cn="already-here").encode()
    _import(authed, ("already-here.ovpn", dup_bytes))
    (scan_root / "fresh.ovpn").write_bytes(ovpn_factory(cn="fresh").encode())
    (scan_root / "already-here.ovpn").write_bytes(dup_bytes)
    (scan_root / "broken.ovpn").write_bytes(b"client\ndev tun\n")

    body = authed.get("/api/profiles/scan").json()
    by_name = {c["name"]: c for c in body["candidates"]}
    assert by_name["fresh"]["status"] == "new"
    assert by_name["fresh"]["path"] == str(scan_root / "fresh.ovpn")
    assert by_name["already-here"]["status"] == "imported"
    assert by_name["already-here"]["imported_profile_id"]
    assert by_name["broken"]["status"] == "error"
    # new candidates sort ahead of already-imported ones
    statuses = [c["status"] for c in body["candidates"]]
    assert statuses.index("new") < statuses.index("imported")


def test_scan_ignores_non_configs_and_missing_roots(authed, fresh_db, scan_root):
    (scan_root / "readme.txt").write_text("not a config")
    (scan_root / "sub").mkdir()
    (scan_root / "sub" / "deep.ovpn").write_bytes(b"client\n")  # parse error, still seen
    from server.settings import CONFIG

    monkey_dirs = CONFIG.scan_dirs + ",/nonexistent-xyz"
    CONFIG.scan_dirs = monkey_dirs
    try:
        body = authed.get("/api/profiles/scan").json()
    finally:
        CONFIG.scan_dirs = str(scan_root)
    names = {c["name"] for c in body["candidates"]}
    assert names == {"deep"}  # .txt skipped, missing root skipped


def test_import_system_happy_path(authed, fresh_db, scan_root, ovpn_factory):
    cfg = scan_root / "fromhost.ovpn"
    cfg.write_bytes(ovpn_factory(cn="fromhost").encode())
    r = authed.post("/api/profiles/import-system", json={"path": str(cfg)})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "imported" and r.json()["parse_error"] is None
    assert any(p["name"] == "fromhost" for p in authed.get("/api/profiles").json()["profiles"])
    # re-import the same file → duplicate, not a second row
    r2 = authed.post("/api/profiles/import-system", json={"path": str(cfg)})
    assert r2.json()["status"] == "duplicate"


def test_import_system_rejects_outside_scan_roots(authed, fresh_db, scan_root, tmp_path):
    outside = tmp_path.parent / "elsewhere.ovpn"
    outside.write_bytes(b"client\n")
    r = authed.post("/api/profiles/import-system", json={"path": "/etc/passwd"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "outside_scan_roots"

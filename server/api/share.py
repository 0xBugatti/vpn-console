"""Public share routes at the root: /s/{token} (US3) — the documented auth
exception (FR-027): these links are the product of a share, carry no session,
are time-boxed, optionally one-time, and audited. Admin share endpoints live
in shares.py under /api. Nothing else at the root is public."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import Response

from .. import audit, ovpn, sharelinks
from ..api.schemas import api_error

router = APIRouter()

# mirror of the UI's STATUS_KIND — used for X-Profile-Status-Kind only
STATUS_KIND = {
    "Valid": "ok", "Expiring": "warn", "Expired": "err",
    "Disabled": "off", "Parse error": "err",
}


# --- public /s/{token} ----------------------------------------------------------

def _download_response(profile: dict, disposition: str) -> Response:
    try:
        text = open(profile["file_path"], encoding="utf-8").read()  # noqa: SIM115
    except OSError:
        raise api_error(410, "file_missing", "Profile file is missing on disk.")  # noqa: B904
    status = ovpn.derive_status(profile["cert_expires_at"], bool(profile["enabled"]),
                                profile["parse_error"])
    kind = STATUS_KIND.get(status, "off")
    return Response(
        content=text,
        media_type="application/x-openvpn-profile",
        headers={
            "Content-Disposition": f'{disposition}; filename="{profile["name"]}.ovpn"',
            "X-Profile-Status": status,
            "X-Profile-Status-Kind": kind,
        },
    )


@router.get("/s/{token}")
def share_page(token: str) -> Response:
    """Minimal session-less landing: name, status warning, one Download button."""
    try:
        profile, _link = sharelinks.resolve(token)
    except sharelinks.ShareError as exc:
        return Response(_gone_page(exc.message), media_type="text/html", status_code=410)
    # NOTE: one-time links are consumed by the DOWNLOAD, not by viewing the page.
    status = ovpn.derive_status(profile["cert_expires_at"], bool(profile["enabled"]),
                                profile["parse_error"])
    warning = ""
    if status in ("Expired", "Parse error", "Disabled"):
        warning = f'<div class="warn">This profile is {status}. It may not connect.</div>'
    elif status == "Expiring":
        warning = '<div class="warn soft">The certificate in this profile expires soon.</div>'
    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Download {profile['name']} · VPN Console</title>
<style>
 body {{ margin:0; font:15px/1.5 system-ui, sans-serif; background:#f2f4f8;
        display:grid; place-items:center; min-height:100vh; color:#1f2430; }}
 main {{ background:#fff; border-radius:14px; box-shadow:0 10px 30px rgb(15 23 42 / .08);
        padding:34px 30px; width:min(400px, calc(100vw - 32px)); text-align:center; }}
 h1 {{ font-size:19px; margin:0 0 4px; }}
 p {{ margin:0 0 16px; color:#64748b; font-size:13px; }}
 .warn {{ background:#fef3c7; color:#92400e; border-radius:8px; padding:8px 12px;
         font-size:13px; margin-bottom:16px; }}
 .warn.soft {{ background:#e0e7ff; color:#3730a3; }}
 a.btn {{ display:inline-block; background:#4f46e5; color:#fff; text-decoration:none;
         font-weight:600; border-radius:9px; padding:10px 22px; font-size:14px; }}
 small {{ display:block; margin-top:14px; color:#94a3b8; }}
</style></head><body><main>
 <h1>{profile['name']}</h1>
 <p>OpenVPN profile from your administrator</p>
 {warning}
 <a class="btn" href="/s/{token}/download">Download .ovpn</a>
 <small>Import it into your OpenVPN client. This link may expire.</small>
</main></body></html>"""
    return Response(html, media_type="text/html")


@router.get("/s/{token}/download")
def share_download(token: str) -> Response:
    try:
        profile, _link = sharelinks.resolve(token)
    except sharelinks.ShareError as exc:
        return Response(_gone_page(exc.message), media_type="text/html", status_code=410)
    sharelinks.mark_used(token)
    audit.insert("share.download", "profiles", target=profile["name"],
                 detail={"token": token})
    return _download_response(profile, "attachment")


def _gone_page(message: str) -> str:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Link unavailable</title>
<style>body {{ margin:0; font:15px/1.5 system-ui, sans-serif; background:#f2f4f8;
display:grid; place-items:center; min-height:100vh; color:#1f2430; }}
main {{ text-align:center; padding:32px; }}</style></head><body><main>
<h1>This link is no longer available</h1><p>{message}</p></main></body></html>"""

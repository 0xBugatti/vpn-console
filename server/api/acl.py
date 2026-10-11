"""API: acl — policy editor backend (US7, FR-040/041, D14).

The applied file is canonical bytes; drafts and the session rollback pin live
in memory (single admin, one instance). Apply is confirm-tier; validation
failures refuse at 409 before the tailnet is touched.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body

from .. import acl, audit, db
from . import common
from .schemas import api_error, require_confirm

router = APIRouter()

_draft: str | None = None
_rollback_text: str | None = None


def _applied() -> tuple[str, dict]:
    result = common.cloud_get("acl", ttl=60.0, fetch=common.cloud().get_acl_text)
    return (result.data or ""), result.health.as_dict()


@router.get("/acl")
def get_acl() -> dict[str, Any]:
    text, health = _applied()
    parsed, _ = acl.parse(text) if text else (None, [])
    return {
        "applied_text": text,
        "structured": acl.structured(parsed) if parsed else [],
        "draft": _draft,
        "_health": health,
    }


@router.put("/acl/draft")
def put_draft(body: dict = Body(...)) -> dict[str, Any]:
    global _draft
    text = str(body.get("text") or "")
    if not text.strip():
        raise api_error(422, "empty_draft", "The draft is empty, so there is nothing to validate.")
    errors = acl.validate(text)
    _draft = text  # keep the editor's text even when invalid
    return {"valid": not errors, "errors": errors}


@router.get("/acl/diff")
def diff_draft() -> dict[str, Any]:
    applied, _ = _applied()
    if _draft is None:
        return {"added": [], "removed": []}
    return acl.diff(applied, _draft)


@router.post("/acl/apply")
def apply_draft(body: dict = Body(default={})) -> dict[str, Any]:
    global _draft, _rollback_text
    require_confirm(body)
    if _draft is None:
        raise api_error(409, "no_draft", "No draft to apply. Edit the policy first.")

    errors = acl.validate(_draft)
    if errors:
        raise api_error(409, "validation_failed",
                        "The draft has errors. Fix them before applying.",
                        errors=errors)

    applied, health = _applied()
    common.require_ok(
        common.cloud_get("acl", ttl=60.0, fetch=common.cloud().get_acl_text),
        "Tailscale",
    )
    draft = _draft
    try:
        common.cloud().put_acl_text(draft)
    except Exception as exc:
        audit.insert("acl.apply", "acl", outcome="failed",
                     detail={"error": str(exc)[:300]})
        raise api_error(502, "action_failed", f"Tailscale rejected the policy: {exc}")
    common.cloud_cache().invalidate("acl")  # the cache now lies about applied text

    with db.get_conn() as c:
        c.execute("INSERT INTO policy_versions(text, applied_at, note) VALUES (?,?,?)",
                  (draft, audit.now_iso(), "applied from editor"))
    _rollback_text = applied  # one-click rollback pinned for this session
    _draft = None
    audit.insert("acl.apply", "acl", detail={"bytes": len(draft)})
    return {"ok": True, "rollback_available": True}


@router.post("/acl/rollback")
def rollback() -> dict[str, Any]:
    global _rollback_text
    if _rollback_text is None:
        raise api_error(409, "nothing_pinned",
                        "No previous policy is pinned. Rollback becomes available right after an apply.")
    text, pinned = _rollback_text, None
    _rollback_text = None
    try:
        common.cloud().put_acl_text(text)
    except Exception as exc:
        _rollback_text = text  # keep the pin so the retry stays possible
        audit.insert("acl.rollback", "acl", outcome="failed",
                     detail={"error": str(exc)[:300]})
        raise api_error(502, "action_failed", f"Tailscale rejected the rollback: {exc}")
    common.cloud_cache().invalidate("acl")

    with db.get_conn() as c:
        c.execute("INSERT INTO policy_versions(text, applied_at, note) VALUES (?,?,?)",
                  (text, audit.now_iso(), "rollback"))
    audit.insert("acl.rollback", "acl", detail={"bytes": len(text)})
    return {"ok": True}

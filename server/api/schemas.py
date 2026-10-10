"""Shared API helpers: error envelope + friction-tier guards (Principle III).

Mutating endpoints require their friction evidence inline (contracts/api.md):
  - simple: direct call → audit + undo_token
  - confirm: body {"confirm": true} else 409 confirm_required
  - typed:   body {"typed_confirm": "<...>"} matching exactly else 409
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException


def api_error(status: int, code: str, message: str, **detail: Any) -> HTTPException:
    return HTTPException(
        status_code=status,
        detail={"code": code, "message": message, **({"detail": detail} if detail else {})},
    )


def require_confirm(body: dict[str, Any]) -> None:
    if not body.get("confirm"):
        raise api_error(
            409,
            "confirm_required",
            "This action needs an explicit confirmation (confirm: true).",
        )


def require_typed(body: dict[str, Any], expected: str, label: str | None = None) -> None:
    typed = (body.get("typed_confirm") or "").strip()
    if typed != expected:
        raise api_error(
            409,
            "typed_confirm_required",
            f'Type "{expected}" to confirm' + (f" {label}" if label else "") + ".",
        )


def subsystem_unavailable(subsystem: str, detail: str) -> HTTPException:
    return api_error(
        409,
        "subsystem_unavailable",
        f"{subsystem} is not reachable; showing stale data. Mutations are disabled.",
        subsystem=subsystem,
        health=detail,
    )

"""Shared API plumbing: subsystem caches, health aggregation, guards (D10)."""
from __future__ import annotations

from typing import Any, Callable

from fastapi import HTTPException

from ..adapters import get_adapters
from ..adapters.base import DEGRADED, OK, Result, SubsystemCache
from .schemas import api_error

_cloud_cache = SubsystemCache("tscloud")
_local_cache = SubsystemCache("tslocal")
_host_cache = SubsystemCache("host")


def cloud() -> Any:
    return get_adapters()["cloud"]


def local() -> Any:
    return get_adapters()["local"]


def host() -> Any:
    return get_adapters()["host"]


def cloud_get(key: str, ttl: float, fetch: Callable[[], Any]) -> Result[Any]:
    return _cloud_cache.get(key, ttl, fetch)


def cloud_cache() -> SubsystemCache:
    return _cloud_cache


def local_get(key: str, ttl: float, fetch: Callable[[], Any]) -> Result[Any]:
    return _local_cache.get(key, ttl, fetch)


def host_get(key: str, ttl: float, fetch: Callable[[], Any]) -> Result[Any]:
    return _host_cache.get(key, ttl, fetch)


def local_cache() -> SubsystemCache:
    return _local_cache


def host_cache() -> SubsystemCache:
    return _host_cache


def all_health() -> dict[str, dict[str, Any]]:
    # Active probe (FR-053): the health endpoint re-checks each subsystem with a
    # cheap call, so recovery is visible immediately instead of after the next
    # page poll. A failed probe leaves the last-good cache untouched.
    _cloud_cache.get("probe", ttl=0.0, fetch=cloud().dns_preferences)
    _local_cache.get("probe", ttl=0.0, fetch=local().status)
    _host_cache.get("probe", ttl=0.0, fetch=host().units)
    return {
        "tscloud": _cloud_cache.health().as_dict(),
        "tslocal": _local_cache.health().as_dict(),
        "host": _host_cache.health().as_dict(),
    }


def require_ok(result: Result, subsystem: str) -> None:
    """Mutations are refused while a subsystem cannot refresh (FR-053)."""
    if result.health.state != OK:
        raise api_error(
            409,
            "subsystem_unavailable",
            f"{subsystem} is {result.health.state}; mutations are disabled.",
            subsystem=subsystem,
            health=result.health.as_dict(),
        )


def degrade_notice(result: Result) -> None:
    """Soft guard for reads: attach stale age; caller includes _health anyway."""
    return None

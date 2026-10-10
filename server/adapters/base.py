"""Adapter foundation: Health envelope, Result, per-subsystem TTL cache (D7/D10).

Principle VI: external systems live behind these interfaces.
Principle VII: adapters never raise across the boundary — failures become state.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Generic, TypeVar

T = TypeVar("T")

OK = "ok"
DEGRADED = "degraded"
UNAVAILABLE = "unavailable"


@dataclass
class Health:
    state: str = OK
    detail: str = ""
    last_ok: float = 0.0  # epoch seconds of last successful call
    age_seconds: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "detail": self.detail,
            "last_ok": self.last_ok,
            "age_seconds": round(self.age_seconds, 1),
        }


@dataclass
class Result(Generic[T]):
    data: T | None
    health: Health


class SubsystemCache:
    """TTL cache with last-good retention (research D10).

    On a failed fetch, serves the previous payload with its age and a
    degraded/unavailable state — never silently (FR-053).
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.last_ok: float = 0.0
        self.last_error: str = ""
        self._entries: dict[str, tuple[float, Any]] = {}

    def _fresh(self, key: str, ttl: float) -> bool:
        entry = self._entries.get(key)
        return bool(entry and (time.monotonic() - entry[0]) < ttl)

    def get(self, key: str, ttl: float, fetch: Callable[[], Any]) -> Result[Any]:
        if self._fresh(key, ttl):
            stamp, data = self._entries[key]
            return Result(data, Health(OK, "", self.last_ok, time.monotonic() - stamp))
        try:
            data = fetch()
        except Exception as exc:  # noqa: BLE001 — the boundary (Principle VII)
            self.last_error = f"{type(exc).__name__}: {exc}"
            if key in self._entries:
                stamp, data = self._entries[key]
                return Result(
                    data,
                    Health(DEGRADED, self.last_error, self.last_ok, time.monotonic() - stamp),
                )
            return Result(
                None, Health(UNAVAILABLE, self.last_error, self.last_ok, 0.0)
            )
        self._entries[key] = (time.monotonic(), data)
        self.last_ok = time.time()
        self.last_error = ""
        return Result(data, Health(OK, "", self.last_ok, 0.0))

    def invalidate(self, key: str | None = None) -> None:
        if key is None:
            self._entries.clear()
        else:
            self._entries.pop(key, None)

    def health(self) -> Health:
        if self.last_error:
            state = UNAVAILABLE if not self._entries else DEGRADED
            return Health(state, self.last_error, self.last_ok)
        if not self.last_ok:
            return Health(UNAVAILABLE, "never reached", 0.0)
        return Health(OK, "", self.last_ok)


def mutations_blocked(health: Health) -> bool:
    """Mutations are disabled while a subsystem cannot be refreshed (FR-053)."""
    return health.state != OK

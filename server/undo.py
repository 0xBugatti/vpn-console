"""Undo tokens: friction tier 1 — local recoverable ops (FR-013/FR-051).

In-memory, 10-second window (single instance). Every registration is paired
with an audit event; executing an undo writes a linked audit entry.
"""
from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

UNDO_WINDOW_S = 10.0


@dataclass
class UndoEntry:
    section: str
    label: str
    restore: Callable[[], Any]
    event_id: int
    created: float
    done: bool = False


class UndoStore:
    def __init__(self) -> None:
        self._entries: dict[str, UndoEntry] = {}
        self._lock = threading.Lock()

    def register(self, section: str, label: str, restore: Callable[[], Any],
                 event_id: int) -> str:
        token = secrets.token_urlsafe(16)
        with self._lock:
            self._entries[token] = UndoEntry(section, label, restore, event_id,
                                             time.monotonic())
        return token

    def pop(self, token: str) -> UndoEntry:
        """Claim the token; raises KeyError if absent/expired/already used."""
        with self._lock:
            entry = self._entries.get(token)
            if entry is None or entry.done:
                raise KeyError(token)
            if time.monotonic() - entry.created > UNDO_WINDOW_S:
                del self._entries[token]
                raise KeyError(token)
            entry.done = True
            return entry

    def sweep(self) -> None:
        """Expire silently (spec: browser closed mid-undo)."""
        now = time.monotonic()
        with self._lock:
            for token in [t for t, e in self._entries.items() if now - e.created > UNDO_WINDOW_S]:
                del self._entries[token]


store = UndoStore()

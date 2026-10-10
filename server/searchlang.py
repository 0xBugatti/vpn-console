"""Shared `key:value` filter language for profiles and devices (FR-021).

Tokens: `os:` `tag:` `user:` `version:` `is:expiring|offline|unapproved|expired`
`status:` `cipher:` `server:` plus `!` negation and bare free text (matched
against the caller-provided text blob). Unknown keys never match — explicit,
not silent.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

TOKEN_RE = re.compile(r"^(!?)([a-z]+):(.+)$")


def parse(query: str) -> list[tuple[bool, str, str]]:
    """-> list of (negated, key, value); plain words become ('text')."""
    tokens: list[tuple[bool, str, str]] = []
    for raw in query.split():
        m = TOKEN_RE.match(raw)
        if m:
            tokens.append((m.group(1) == "!", m.group(2), m.group(3)))
        else:
            tokens.append((False, "text", raw))
    return tokens


def predicate(query: str, getters: dict[str, Callable[[Any], Any]]) -> Callable[[Any], bool]:
    """Build a row predicate.

    getters: token key -> accessor; optional special accessors
      "_text": row -> free-text blob for bare words
      "_flags": row -> dict of boolean flags used by `is:` (e.g. expiring)
    """
    tokens = parse(query)

    def match_one(row: Any, neg: bool, key: str, value: str) -> bool:
        if key == "text":
            blob = getters.get("_text")
            hit = value.lower() in blob(row).lower() if blob else False
        elif key == "is":
            flags = getters.get("_flags")
            hit = bool(flags and flags(row).get(value, False))
        else:
            getter = getters.get(key)
            if getter is None:
                hit = False
            else:
                actual = getter(row)
                if isinstance(actual, (list, tuple, set)):
                    hit = value.lower() in [str(a).lower() for a in actual]
                else:
                    text = str(actual or "").lower()
                    hit = value.lower() in text if key in ("server", "version", "name") else text == value.lower()
        return (not hit) if neg else hit

    def match(row: Any) -> bool:
        return all(match_one(row, neg, key, value) for neg, key, value in tokens)

    return match

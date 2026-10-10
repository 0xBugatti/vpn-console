"""Adapter registry (research D12): VPNCONSOLE_ADAPTERS=real|fake.

The real-adapter imports are module-level on purpose: a wrong name then
breaks every mode at import time instead of hiding until a live deploy
(this file shipped with get_setting imported from the wrong module, and
fake-mode tests never executed the real branch to catch it).
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any

import httpx

from ..db import get_setting
from ..settings import CONFIG
from .host import HostControl
from .tscloud import TailscaleCloud
from .tslocal import TailscaleLocal


@lru_cache(maxsize=1)
def get_adapters() -> dict[str, Any]:
    if CONFIG.adapters == "fake":
        import sys
        from pathlib import Path

        tests_dir = str(Path(__file__).resolve().parents[2] / "tests")
        if tests_dir not in sys.path:
            sys.path.insert(0, tests_dir)
        import fakes

        return {
            "cloud": fakes.FakeCloud(),
            "local": fakes.FakeLocal(),
            "host": fakes.FakeHost(),
            "kind": "fake",
        }

    token = CONFIG.ts_token_env or get_setting("ts_token") or ""
    cloud = TailscaleCloud(httpx.Client(), CONFIG.tailnet, token)
    return {
        "cloud": cloud,
        "local": TailscaleLocal(),
        "host": HostControl(),
        "kind": "real",
    }

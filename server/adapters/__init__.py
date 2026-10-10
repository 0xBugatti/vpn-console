"""Adapter registry (research D12): VPNCONSOLE_ADAPTERS=real|fake."""
from __future__ import annotations

from functools import lru_cache
from typing import Any

from ..settings import CONFIG


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

    import httpx

    from ..settings import get_setting
    from .host import HostControl
    from .tscloud import TailscaleCloud
    from .tslocal import TailscaleLocal

    token = CONFIG.ts_token_env or get_setting("ts_token") or ""
    cloud = TailscaleCloud(httpx.Client(), CONFIG.tailnet, token)
    return {
        "cloud": cloud,
        "local": TailscaleLocal(),
        "host": HostControl(),
        "kind": "real",
    }

"""Tailscale cloud REST adapter — api.tailscale.com/api/v2 (research D3).

Thin + raising; the SubsystemCache in base.py is the Principle-VII boundary
that converts failures into Health states. Transport client is injected so
tests run httpx.MockTransport with recorded fixtures (Constitution VI).
"""
from __future__ import annotations

import time
from typing import Any

import httpx

from .base import DEGRADED, OK, UNAVAILABLE, Health, Result, SubsystemCache

BASE = "https://api.tailscale.com/api/v2"
TIMEOUT = 10.0


class TailscaleCloud:
    def __init__(self, client: httpx.Client, tailnet: str, token: str) -> None:
        self.client = client
        self.tailnet = tailnet
        self.token = token
        self.cache = SubsystemCache("tscloud")

    # --- transport -------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{BASE}{path}"
        resp = self.client.request(method, url, headers=self._headers(), timeout=TIMEOUT, **kwargs)
        resp.raise_for_status()
        if resp.status_code == 204 or not resp.content:
            return {}
        return resp.json()

    def _call(self, fn: Any) -> Result[Any]:
        """Direct (uncached) call with error→health mapping."""
        try:
            return Result(fn(), Health(OK, "", time.time(), 0.0))
        except httpx.HTTPStatusError as exc:
            detail = f"HTTP {exc.response.status_code}"
            try:
                body = exc.response.json()
                if isinstance(body, dict) and body.get("message"):
                    detail += f": {body['message']}"
            except ValueError:
                pass
            return Result(None, Health(DEGRADED, detail, self.cache.last_ok))
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            return Result(None, Health(UNAVAILABLE, f"{type(exc).__name__}: {exc}", self.cache.last_ok))

    # --- cached reads (10 s/60 s TTLs applied by callers via cache) --------

    def tailnet(self) -> dict[str, Any]:
        return self._request("GET", f"/tailnet/{self.tailnet}")

    def list_devices(self) -> list[dict[str, Any]]:
        data = self._request("GET", f"/tailnet/{self.tailnet}/devices")
        return data.get("devices", [])

    def list_users(self) -> list[dict[str, Any]]:
        data = self._request("GET", f"/tailnet/{self.tailnet}/users")
        return data.get("users", [])

    def get_acl_text(self) -> str:
        data = self._request("GET", f"/tailnet/{self.tailnet}/acl")
        acl = data.get("acls")
        return acl if isinstance(acl, str) else ""

    # --- mutations (contracts/api.md friction enforced at the API layer) ---

    def approve_device(self, device_id: str) -> None:
        self._request("POST", f"/device/{device_id}/authorized", json={"authorized": True})

    def delete_device(self, device_id: str) -> None:
        self._request("DELETE", f"/device/{device_id}")

    def expire_key(self, device_id: str) -> None:
        self._request(
            "POST", f"/device/{device_id}/key-expiry",
            json={"keyExpiry": "1970-01-01T00:00:00Z"},
        )

    def set_key_expiry_disabled(self, device_id: str, disabled: bool) -> None:
        # disabling = null expiry; re-enabling = re-issue a 180-day horizon
        expiry: str | None = None
        if not disabled:
            import datetime as dt
            expiry = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=180)).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            )
        self._request(
            "POST", f"/device/{device_id}/key-expiry", json={"keyExpiry": expiry}
        )

    def set_tags(self, device_id: str, tags: list[str]) -> None:
        self._request("POST", f"/device/{device_id}/tags", json={"tags": tags})

    def set_approved_routes(self, device_id: str, routes: list[str]) -> None:
        self._request(
            "POST", f"/device/{device_id}/approved-routes", json={"routes": routes}
        )

    def put_acl_text(self, text: str) -> None:
        self._request("POST", f"/tailnet/{self.tailnet}/acl", json={"acls": text})

    def create_auth_key(self, reusable: bool = False, expiry_seconds: int = 600,
                        ephemeral: bool = False, tags: list[str] | None = None) -> str:
        capabilities: dict[str, Any] = {"devices": {"create": {"reusable": reusable, "ephemeral": ephemeral}}}
        if tags:
            capabilities["devices"]["create"]["tags"] = tags
        data = self._request(
            "POST", f"/tailnet/{self.tailnet}/keys",
            json={"expirySeconds": expiry_seconds, "capabilities": capabilities},
        )
        return data.get("key", "")

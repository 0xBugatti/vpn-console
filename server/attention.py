"""Attention queue derivation (US6, FR-031, data-model AttentionItem).

Pure functions: everything the Overview page leads with is derived here from
already-view-modeled rows. One item per device at most — the most severe
condition wins — so the queue stays glanceable (SC-003). Red = broken or
internet-facing; amber = act soon. Sorted severity → age (oldest first).
"""
from __future__ import annotations

import datetime as dt

STALE_OFFLINE = dt.timedelta(days=7)  # offline longer than this = stale (data-model)


def _item(severity: str, code: str, message: str, target_href: str,
          target_label: str, action: dict, age_seconds: float = 0.0) -> dict:
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "target_href": target_href,
        "target_label": target_label,
        "inline_action": action,
        "age": age_seconds,
    }


def _age(iso_ts: str, now: dt.datetime) -> float:
    try:
        ts = dt.datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        return max(0.0, (now - ts).total_seconds())
    except (ValueError, AttributeError, TypeError):
        return 0.0


def _profile_items(profiles: list[dict], now: dt.datetime) -> list[dict]:
    out = []
    for p in profiles:
        if p.get("status") == "Expired":
            out.append(_item(
                "red", "profile.cert_expired",
                f'Profile "{p["name"]}" has an expired certificate — connections fail until it is renewed.',
                "#/profiles", p["name"],
                {"label": "Open profile", "href": "#/profiles", "method": "GET"},
                _age(p.get("cert_expires_at") or "", now),
            ))
        elif p.get("status") == "Expiring":
            out.append(_item(
                "amber", "profile.cert_expiring",
                f'Profile "{p["name"]}" certificate expires within 14 days.',
                "#/profiles", p["name"],
                {"label": "Open profile", "href": "#/profiles", "method": "GET"},
                _age(p.get("cert_expires_at") or "", now),
            ))
    return out


_DEVICE_PRIORITY = [("expired", "red"), ("unapproved", "amber"), ("stale", "amber")]
_DEVICE_TEXT = {
    "expired": 'Device "{name}" has an expired key — it cannot connect until re-authenticated.',
    "unapproved": 'Device "{name}" is waiting for your approval.',
    "stale": 'Device "{name}" has not been seen for more than 7 days.',
}


def _device_items(devices: list[dict], now: dt.datetime) -> list[dict]:
    out = []
    for d in devices:
        # NOT _flags: its "stale" is version staleness; offline staleness is derived here
        conditions = {
            "expired": d.get("key_expiry_state") == "expired",
            "unapproved": not d.get("authorized", True),
            "stale": (not d.get("online"))
            and _age(d.get("last_seen") or "", now) > STALE_OFFLINE.total_seconds(),
        }
        for state, severity in _DEVICE_PRIORITY:
            if not conditions[state]:
                continue
            name = d.get("hostname") or d.get("name") or d.get("id", "")
            action = (
                {"label": "Approve", "path": f"/api/devices/{d['id']}/approve",
                 "method": "POST", "body": None}
                if state == "unapproved" else
                {"label": "Open device", "href": "#/devices", "method": "GET"}
            )
            out.append(_item(
                severity, f"device.{"key_expired" if state == "expired" else state}",
                   _DEVICE_TEXT[state].format(name=name),
                "#/devices", name, action, _age(d.get("last_seen") or "", now),
            ))
            break  # one item per device — the most severe condition wins
    return out


def _node_items(local_status: dict | None) -> list[dict]:
    if not local_status:
        return []
    state = (local_status.get("BackendState") or "").lower()
    if state in ("running", "starting"):  # "NeedsLogin" etc. still means down here
        return []
    host = (local_status.get("Self") or {}).get("HostName") or "This server"
    return [_item(
        "red", "node.down",
        f"Tailscale is {local_status.get('BackendState') or 'down'} on {host} — the node is off the tailnet.",
        "#/node", host, {"label": "Open Local Node", "href": "#/node", "method": "GET"},
    )]


def _service_items(services: list[dict]) -> list[dict]:
    out = []
    for s in services:
        if s.get("state") == "failed":
            unit = s.get("unit") or "unknown unit"
            out.append(_item(
                "red", "service.failed",
                f'Service {unit.removesuffix(".service")} has failed.',
                "#/services", unit,
                {"label": "Open Services", "href": "#/services", "method": "GET"},
            ))
    return out


def _exposure_items(exposures: list[dict] | None) -> list[dict]:
    out = []
    for e in exposures or []:
        if e.get("scope") == "public":
            name = e.get("name") or e.get("kind") or "a service"
            out.append(_item(
                "red", "exposure.public",
                f'"{name}" is exposed to the public internet via Funnel.',
                "#/exposures", name,
                {"label": "Open Exposures", "href": "#/exposures", "method": "GET"},
            ))
    return out


def _policy_items(policy_errors: list[str] | None) -> list[dict]:
    if not policy_errors:
        return []
    return [_item(
        "amber", "policy.errors",
        f"Tailnet policy has {len(policy_errors)} validation error(s).",
        "#/acl", "Tailnet policy",
        {"label": "Open editor", "href": "#/acl", "method": "GET"},
    )]


_SEVERITY_ORDER = {"red": 0, "amber": 1}


def attention_items(
    profiles: list[dict],
    devices: list[dict],
    local_status: dict | None,
    services: list[dict],
    exposures: list[dict] | None = None,
    policy_errors: list[str] | None = None,
    now: dt.datetime | None = None,
) -> list[dict]:
    """Every actionable problem, sorted severity → age (FR-031, SC-003)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    items = [
        *_profile_items(profiles, now),
        *_device_items(devices, now),
        *_node_items(local_status),
        *_service_items(services),
        *_exposure_items(exposures),
        *_policy_items(policy_errors),
    ]
    items.sort(key=lambda i: (_SEVERITY_ORDER[i["severity"]], -i["age"]))
    return items

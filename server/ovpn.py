""".ovpn parsing + status derivation (research D4, FR-010/FR-011).

Pure functions — no I/O. Status is recomputed from (cert date, enabled) on
every read; the server's clock is the only clock (spec: clock-skew edge case).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
from typing import Any

MAX_PROFILE_BYTES = 1_048_576  # 1 MiB cap (spec edge case)
EXPIRING_WINDOW = dt.timedelta(days=14)

_BLOCK_RE = re.compile(r"<(ca|cert|key|tls-auth|tls-crypt)>(.*?)</\1>", re.DOTALL)
_REMOTE_RE = re.compile(r"^\s*remote\s+(\S+)\s+(\d+)(?:\s+(udp6?|tcp6?))?\s*$", re.MULTILINE)
_KV_RE = re.compile(r"^\s*(cipher|data-ciphers|tls-version-min|proto)\s+(\S+)\s*$", re.MULTILINE)


class ProfileTooLarge(Exception):
    pass


def parse(text: str) -> dict[str, Any]:
    """Parse an .ovpn body into display metadata (never raises for content)."""
    out: dict[str, Any] = {
        "endpoints": [],
        "cipher": None,
        "tls_version_min": None,
        "proto": None,
        "has_auth_user_pass": False,
        "cert_expires_at": None,
        "parse_error": None,
        "config_sha256": hashlib.sha256(text.encode()).hexdigest(),
    }

    for host, port, proto in _REMOTE_RE.findall(text):
        out["endpoints"].append({"host": host, "port": int(port), "proto": proto or None})

    for key, value in _KV_RE.findall(text):
        if key == "cipher" and out["cipher"] is None:
            out["cipher"] = value
        elif key == "data-ciphers" and out["cipher"] is None:
            out["cipher"] = value.split(":")[0]
        elif key == "tls-version-min":
            out["tls_version_min"] = value
        elif key == "proto" and out["proto"] is None:
            out["proto"] = value

    out["has_auth_user_pass"] = bool(re.search(r"^\s*auth-user-pass\b", text, re.MULTILINE))

    blocks = {name: body.strip() for name, body in _BLOCK_RE.findall(text)}
    cert_pem = blocks.get("cert")
    if cert_pem and "-----BEGIN CERTIFICATE-----" in cert_pem:
        try:
            from cryptography import x509

            cert = x509.load_pem_x509_certificate(cert_pem.encode())
            expiry = cert.not_valid_after_utc
            out["cert_expires_at"] = expiry.strftime("%Y-%m-%dT%H:%M:%SZ")
        except Exception:  # noqa: BLE001 — a bad cert is a parse error, not a crash
            out["parse_error"] = "client certificate block could not be parsed"
    else:
        out["parse_error"] = "missing certificate block"

    if not out["endpoints"] and out["parse_error"] is None:
        out["parse_error"] = "no remote endpoint found"
    return out


def derive_status(parsed_cert_expires_at: str | None, enabled: bool,
                  parse_error: str | None, now: dt.datetime | None = None) -> str:
    """The one status derivation — FR-011's exact five states."""
    if parse_error:
        return "Parse error"
    if not enabled:
        return "Disabled"
    if not parsed_cert_expires_at:
        return "Valid"  # user-pass auth or expiry unknown-but-parsed
    expiry = dt.datetime.strptime(parsed_cert_expires_at, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=dt.timezone.utc
    )
    now = now or dt.datetime.now(dt.timezone.utc)
    if expiry <= now:
        return "Expired"
    if expiry - now <= EXPIRING_WINDOW:
        return "Expiring"
    return "Valid"

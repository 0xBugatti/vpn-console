"""Environment/config + password hashing (Constitution II, research D7/D12).

Secrets live in env (or a chmod-600 file) and the local SQLite settings table —
never in the repository. The Tailscale token is env-preferred.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1


# --- password hashing (stdlib scrypt) ---------------------------------------

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32
    )
    return "scrypt$%d$%d$%d$%s$%s" % (
        SCRYPT_N,
        SCRYPT_R,
        SCRYPT_P,
        base64.b64encode(salt).decode(),
        base64.b64encode(digest).decode(),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        expected = base64.b64decode(digest_b64)
        actual = hashlib.scrypt(
            password.encode(),
            salt=base64.b64decode(salt_b64),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


# --- configuration -----------------------------------------------------------

@dataclass
class Config:
    data_dir: Path
    admin_password_env: str | None
    ts_token_env: str | None
    tailnet: str
    poll_status_s: int = 10
    poll_lists_s: int = 60
    adapters: str = "real"  # VPNCONSOLE_ADAPTERS=real|fake (research D12)
    scan_dirs: str = ""  # comma-separated read-only host mounts to scan
    session_secret: bytes = field(repr=False, default=b"")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "vpn-console.db"

    @property
    def profiles_dir(self) -> Path:
        return self.data_dir / "profiles"


def load_config() -> Config:
    data_dir = Path(os.environ.get("VPNCONSOLE_DATA", "./data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "profiles").mkdir(parents=True, exist_ok=True)

    admin_password = os.environ.get("ADMIN_PASSWORD")
    password_file = os.environ.get("ADMIN_PASSWORD_FILE")
    if not admin_password and password_file:
        p = Path(password_file)
        if p.is_file():
            admin_password = p.read_text(encoding="utf-8").strip()

    secret = os.environ.get("VPNCONSOLE_SESSION_SECRET", "")
    return Config(
        data_dir=data_dir,
        admin_password_env=admin_password,
        ts_token_env=os.environ.get("TS_API_TOKEN"),
        tailnet=os.environ.get("TS_TAILNET", "-"),
        poll_status_s=int(os.environ.get("VPNCONSOLE_POLL_STATUS_S", "10")),
        poll_lists_s=int(os.environ.get("VPNCONSOLE_POLL_LISTS_S", "60")),
        adapters=os.environ.get("VPNCONSOLE_ADAPTERS", "real"),
        scan_dirs=os.environ.get("VPNCONSOLE_SCAN_DIRS", ""),
        session_secret=secret.encode() or secrets.token_bytes(32),
    )


CONFIG = load_config()

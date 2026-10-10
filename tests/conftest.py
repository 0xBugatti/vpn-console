"""Shared pytest fixtures: fake-mode app, signed-in client, ovpn factory (T005)."""
from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile
from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).parent
sys.path.insert(0, str(TESTS_DIR))  # fakes.py
sys.path.insert(0, str(TESTS_DIR.parent))  # server package

_TMP = tempfile.mkdtemp(prefix="vpnconsole-test-")
os.environ["VPNCONSOLE_ADAPTERS"] = "fake"
os.environ["VPNCONSOLE_DATA"] = _TMP
os.environ["VPNCONSOLE_SESSION_SECRET"] = "test-secret"
os.environ["ADMIN_PASSWORD"] = "test-password-123"

from fastapi.testclient import TestClient  # noqa: E402

from cryptography import x509  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402
from cryptography.x509.oid import NameOID  # noqa: E402

from server.app import app  # noqa: E402


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def authed(client):
    from server import auth

    auth.login_limiter.reset_all()  # other tests may have exhausted the window
    r = client.post("/api/auth/login", json={"password": "test-password-123"})
    assert r.status_code == 200, r.text
    return client


def make_ovpn(cn: str = "test-client", expires: dt.datetime | None = None,
              remotes: tuple = (("vpn.example.net", "1194", "udp"),),
              cipher: str = "AES-256-GCM") -> str:
    """Generate an .ovpn body with a real inline client cert (never goes stale)."""
    from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat

    expires = expires or (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=365))
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(expires - dt.timedelta(days=365))  # valid for expiries in the past too
        .not_valid_after(expires)
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(Encoding.PEM).decode()
    key_pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()).decode()
    remote_lines = "\n".join(f"remote {host} {port} {proto}" for host, port, proto in remotes)
    return (
        "client\ndev tun\nproto udp\n"
        f"{remote_lines}\n"
        f"cipher {cipher}\ndata-ciphers {cipher}:AES-128-GCM\n"
        f"<cert>\n{cert_pem}</cert>\n<key>\n{key_pem}</key>\n"
    )


@pytest.fixture()
def ovpn_factory():
    return make_ovpn


@pytest.fixture(autouse=True)
def fresh_adapters():
    """Every test starts from pristine fake state — adapters are process
    singletons and subsystem caches outlive tests (T040 lesson)."""
    from server.adapters import get_adapters
    from server.api import common

    adapters = get_adapters()
    adapters["cloud"].reset()
    adapters["local"].reset()
    adapters["host"].reset()
    for cache in (common.cloud_cache(), common.local_cache(), common.host_cache()):
        cache.invalidate()
    yield


@pytest.fixture()
def fakes():
    from server.adapters import get_adapters

    return get_adapters()


@pytest.fixture()
def fresh_db():
    """Wipe profiles between tests that count rows."""
    from server import db

    with db.get_conn() as c:
        c.execute("DELETE FROM share_links")
        c.execute("DELETE FROM profiles")
    yield

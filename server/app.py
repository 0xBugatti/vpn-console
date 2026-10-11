"""FastAPI wiring (research D12): routers, static SPA, error envelope, lifespan."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import audit, auth
from .db import init_db
from .api import (
    acl,
    audit as audit_api,
    auth as auth_api,
    devices,
    exposures,
    logs,
    node,
    overview,
    profiles,
    services,
    settings as settings_api,
    share,
    shares,
    undo,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    auth_api.ensure_admin_password()
    audit.insert("app.start", "settings", outcome="ok", detail={"adapters": _adapters_kind()})
    yield


def _adapters_kind() -> str:
    from .adapters import get_adapters

    return str(get_adapters().get("kind", "real"))


app = FastAPI(title="VPN Console", lifespan=lifespan, docs_url=None, redoc_url=None)

# Guarded routers (everything under /api requires the session — SC-001).
for module in (overview, profiles, shares, devices, acl, node, exposures,
               services, logs, audit_api, settings_api, undo):
    app.include_router(module.router, prefix="/api",
                       dependencies=[Depends(auth.require_admin)])

# Auth router handles its own gating per-endpoint (login must be reachable).
app.include_router(auth_api.router, prefix="/api")
# Share routes live at the root: /s/{token} is the QR-encoded public URL.
app.include_router(share.router)
# Login link (/login?token=… and /?token=…) — must precede the static mount.
app.include_router(auth_api.link_router)


@app.exception_handler(HTTPException)
async def http_error(_req: Request, exc: HTTPException) -> JSONResponse:
    detail = exc.detail
    if isinstance(detail, dict):
        body = {"error": detail}
    else:
        body = {"error": {"code": "error", "message": str(detail)}}
    return JSONResponse(status_code=exc.status_code, content=body)


@app.exception_handler(RequestValidationError)
async def validation_error(_req: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"error": {"code": "validation_failed",
                           "message": "Invalid request body.",
                           "detail": {"errors": exc.errors()[:5]}}},
    )


STATIC_DIR = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

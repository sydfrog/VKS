"""FastAPI application exposing /status, /enable and /disable.

Every endpoint requires the bearer token in API_TOKEN. There is no unauthenticated
route at all, health check included, so an open port leaks nothing.
"""

from __future__ import annotations

import asyncio
import hmac
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Annotated

import httpx

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from . import __version__
from .config import Settings, load_settings
from .unifi import PolicyState, UniFiClient, UniFiError

log = logging.getLogger("unifi_toggle")

bearer_scheme = HTTPBearer(auto_error=False)


class StatusResponse(BaseModel):
    policy_id: str
    name: str
    enabled: bool
    kind: str
    site: str
    changed: bool = False
    checked_at: str


class ErrorResponse(BaseModel):
    error: str
    hint: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _as_response(state: PolicyState, changed: bool = False) -> StatusResponse:
    return StatusResponse(
        policy_id=state.policy_id,
        name=state.name,
        enabled=state.enabled,
        kind=state.kind,
        site=state.site,
        changed=changed,
        checked_at=_now(),
    )


def create_app(
    settings: Settings | None = None,
    http_client: "httpx.AsyncClient | None" = None,
) -> FastAPI:
    """Build the app.

    http_client exists so the test suite can point the UniFi client at an
    in-process fake console. Production leaves it None.
    """
    resolved = settings or load_settings()
    for warning in resolved.warnings:
        log.warning("%s", warning)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = resolved
        app.state.unifi = UniFiClient(resolved, http_client)
        # Serialises read-modify-write so two taps cannot interleave.
        app.state.write_lock = asyncio.Lock()
        log.info(
            "unifi-toggle %s ready. console=%s site=%s auth=%s policy=%s kind=%s",
            __version__,
            resolved.unifi_base_url,
            resolved.unifi_site,
            app.state.unifi.auth_mode,
            resolved.policy_id,
            resolved.policy_kind,
        )
        try:
            state = await app.state.unifi.get_state()
            log.info(
                "startup probe found policy %r (%s) currently %s",
                state.name,
                state.kind,
                "enabled" if state.enabled else "disabled",
            )
        except UniFiError as exc:
            # Do not abort startup. systemd would just restart into the same
            # failure, and /status is the right place to surface it.
            log.warning("startup probe failed: %s", exc)
        try:
            yield
        finally:
            await app.state.unifi.aclose()

    app = FastAPI(
        title="UniFi policy toggle",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    def require_token(
        request: Request,
        credentials: Annotated[
            HTTPAuthorizationCredentials | None, Depends(bearer_scheme)
        ],
    ) -> None:
        expected = request.app.state.settings.api_token
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise HTTPException(
                status_code=401,
                detail="missing bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not hmac.compare_digest(credentials.credentials, expected):
            raise HTTPException(status_code=403, detail="invalid bearer token")

    Auth = Depends(require_token)

    @app.exception_handler(UniFiError)
    async def _unifi_error_handler(request: Request, exc: UniFiError) -> JSONResponse:
        log.error("UniFi error: %s", exc)
        return JSONResponse(
            status_code=exc.status,
            content=ErrorResponse(error=str(exc), hint=exc.hint).model_dump(),
        )

    @app.get("/healthz", response_model=dict, dependencies=[Auth])
    async def healthz() -> dict:
        """Liveness only. Does not touch the console."""
        return {"ok": True, "version": __version__, "checked_at": _now()}

    @app.get("/status", response_model=StatusResponse, dependencies=[Auth])
    async def status(request: Request) -> StatusResponse:
        state = await request.app.state.unifi.get_state()
        return _as_response(state)

    @app.post("/enable", response_model=StatusResponse, dependencies=[Auth])
    async def enable(request: Request) -> StatusResponse:
        async with request.app.state.write_lock:
            state, changed = await request.app.state.unifi.set_enabled(True)
        log.info("enable: policy %s changed=%s", state.policy_id, changed)
        return _as_response(state, changed)

    @app.post("/disable", response_model=StatusResponse, dependencies=[Auth])
    async def disable(request: Request) -> StatusResponse:
        async with request.app.state.write_lock:
            state, changed = await request.app.state.unifi.set_enabled(False)
        log.info("disable: policy %s changed=%s", state.policy_id, changed)
        return _as_response(state, changed)

    return app


app_factory = create_app

"""FastAPI application factory."""

from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app import __version__
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger, request_id_ctx
from app.core.redis import get_redis
from app.db.session import engine

log = get_logger("app.access")


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging(settings.log_level, settings.log_json)
    if settings.is_production and settings.secret_key.startswith("change-me"):
        raise RuntimeError("SECRET_KEY must be set in production")
    log.info("startup", extra={"version": __version__, "environment": settings.environment})
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version=__version__,
        openapi_url=f"{settings.api_prefix}/openapi.json",
        docs_url=f"{settings.api_prefix}/docs",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):  # noqa: ANN001
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        token = request_id_ctx.set(rid)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_ctx.reset(token)
        elapsed = round((time.perf_counter() - start) * 1000, 1)
        response.headers["X-Request-ID"] = rid
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        if request.url.path not in ("/health", "/ready"):
            log.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "ms": elapsed,
                    "request_id": rid,
                },
            )
        return response

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_prefix)

    @app.get("/health", tags=["ops"])
    async def health() -> dict:
        return {"status": "ok", "version": __version__}

    @app.get("/ready", tags=["ops"])
    async def ready() -> dict:
        checks = {}
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as exc:  # noqa: BLE001
            checks["database"] = f"error: {type(exc).__name__}"
        try:
            await get_redis().ping()
            checks["redis"] = "ok"
        except Exception as exc:  # noqa: BLE001
            checks["redis"] = f"error: {type(exc).__name__}"
        ok = all(v == "ok" for v in checks.values())
        from fastapi.responses import JSONResponse

        return JSONResponse({"status": "ready" if ok else "degraded", "checks": checks}, status_code=200 if ok else 503)  # type: ignore[return-value]

    return app


app = create_app()

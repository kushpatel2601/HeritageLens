"""ASGI entry point: `uvicorn app.main:app`."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app import __version__
from app.api.deps import Services
from app.api.routes import assets, jobs, journeys, ops, search, sites, twins, workers
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, request_id_var
from app.db.session import Database
from app.services.embeddings import warm_text_embedder
from app.services.events import EventHub
from app.services.jobs import JobQueue
from app.services.search import SearchService
from app.services.storage import build_storage
from app.workers.local import LocalWorker

log = logging.getLogger("app.access")

API_PREFIX = "/api/v1"


class RequestContextMiddleware:
    """Request id propagation + access log. Pure ASGI (unlike BaseHTTPMiddleware) so SSE streams
    and file responses are never buffered."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        rid = (headers.get(b"x-request-id") or b"").decode()[:64] or uuid.uuid4().hex[:16]
        token = request_id_var.set(rid)
        start = time.perf_counter()
        status = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message.setdefault("headers", [])
                message["headers"] = [
                    *message["headers"],
                    (b"x-request-id", rid.encode()),
                    (b"server-timing", f"app;dur={(time.perf_counter() - start) * 1000:.1f}".encode()),
                ]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            ms = (time.perf_counter() - start) * 1000
            if not scope["path"].endswith(("/health", "/events")):
                log.info(
                    "%s %s %s %.1fms", scope["method"], scope["path"], status, ms, extra={"duration_ms": round(ms, 1)}
                )
            request_id_var.reset(token)


def build_services(settings: Settings) -> Services:
    db = Database(settings)
    storage = build_storage(settings)
    return Services(
        settings=settings,
        db=db,
        storage=storage,
        queue=JobQueue(settings),
        search=SearchService(settings),
        events=EventHub(db),
    )


def create_app(settings: Settings | None = None, *, services: Services | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        svc: Services = app.state.services
        if settings.is_sqlite and settings.auto_create_schema:
            await svc.db.create_all()
        if settings.embedded_worker:
            svc.worker = LocalWorker(
                svc.ctx, concurrency=settings.embedded_worker_concurrency, name="embedded cpu worker"
            )
            await svc.worker.start()
        warm_up = (
            asyncio.create_task(warm_text_embedder(settings), name="embedder-warm-up")
            if settings.warm_embedder
            else None
        )
        log.info(
            "%s %s ready (db=%s, storage=%s)", settings.app_name, __version__, svc.db.dialect, settings.storage_backend
        )
        try:
            yield
        finally:
            if warm_up is not None and not warm_up.done():
                warm_up.cancel()
            if svc.worker is not None:
                await svc.worker.stop()
            await svc.events.close()
            await svc.db.dispose()

    app = FastAPI(
        title=f"{settings.app_name} API",
        version=__version__,
        summary="Turn unstructured heritage archives into a searchable, mappable, immersive atlas.",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
        openapi_url=f"{API_PREFIX}/openapi.json",
    )
    app.state.services = services or build_services(settings)

    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["*"],
        expose_headers=["x-request-id", "server-timing"],
    )
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)

    api = APIRouter(prefix=API_PREFIX)
    for module in (ops, search, sites, journeys, assets, twins, jobs):
        api.include_router(module.router)
    api.include_router(workers.router)
    api.include_router(workers.protected)
    app.include_router(api)

    @app.get("/", include_in_schema=False)
    async def root() -> dict[str, Any]:
        return {"name": settings.app_name, "version": __version__, "docs": "/docs", "api": API_PREFIX}

    return app


app = create_app()

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.logging import request_id_var

log = logging.getLogger(__name__)


class AppError(Exception):
    """Domain error rendered as RFC 9457 problem+json."""

    status_code = 400
    title = "Bad request"

    def __init__(self, detail: str, *, status_code: int | None = None, title: str | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        if status_code is not None:
            self.status_code = status_code
        if title is not None:
            self.title = title


class NotFoundError(AppError):
    status_code = 404
    title = "Not found"


class ConflictError(AppError):
    status_code = 409
    title = "Conflict"


class UnsupportedMediaError(AppError):
    status_code = 415
    title = "Unsupported media type"


class PayloadTooLargeError(AppError):
    status_code = 413
    title = "Payload too large"


def _problem(status: int, title: str, detail: object, request: Request) -> JSONResponse:
    body: dict[str, object] = {
        "type": "about:blank",
        "title": title,
        "status": status,
        "detail": detail,
        "instance": request.url.path,
    }
    if rid := request_id_var.get():
        body["request_id"] = rid
    return JSONResponse(body, status_code=status, media_type="application/problem+json")


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return _problem(exc.status_code, exc.title, exc.detail, request)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _problem(exc.status_code, "HTTP error", exc.detail, request)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
        return _problem(422, "Validation failed", errors, request)

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return _problem(500, "Internal server error", "An unexpected error occurred.", request)

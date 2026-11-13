from datetime import datetime, timezone
from http import HTTPStatus
import json
import logging
import time
import traceback
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.schema.errors import APIErrorResponse
from app.config.config import CORS_ALLOWED_ORIGINS

logger = logging.getLogger("app.api")
ERROR_RESPONSES = {
    status: {"model": APIErrorResponse}
    for status in (400, 403, 404, 405, 409, 422, 500, 503)
}


def log_event(level: int, event: str, **fields) -> None:
    logger.log(level, json.dumps({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event, **fields,
    }))


def error_response(request: Request, status: int, code: str, message: str, *, details=None, headers=None):
    request_id = request.state.request_id
    return JSONResponse(
        status_code=status,
        content={
            "detail": message,
            "error": {"code": code, "message": message, "details": details or []},
            "request_id": request_id,
        },
        headers={**(headers or {}), "X-Request-ID": request_id, "Cache-Control": "no-store"},
    )


async def http_error(request: Request, exc: HTTPException):
    try:
        status = HTTPStatus(exc.status_code)
        code, default_message = status.name, status.phrase
    except ValueError:
        code, default_message = "HTTP_ERROR", "Request failed"
    message = exc.detail if isinstance(exc.detail, str) else default_message
    log_event(logging.WARNING if exc.status_code < 500 else logging.ERROR,
              "http_error", request_id=request.state.request_id, status=exc.status_code, code=code)
    return error_response(request, exc.status_code, code, message, headers=exc.headers)


async def validation_error(request: Request, exc: RequestValidationError):
    # Exclude input, body, and exception context, which can contain credentials.
    details = [
        {"location": list(error["loc"]), "message": error["msg"], "type": error["type"]}
        for error in exc.errors()
    ]
    log_event(logging.WARNING, "validation_error", request_id=request.state.request_id,
              status=422, issue_count=len(details))
    return error_response(request, 422, "VALIDATION_ERROR", "Request validation failed", details=details)


def safe_trace(exc: Exception) -> list[dict]:
    # No exception messages, SQL parameters, source text, or local variables.
    return [{"file": frame.filename, "line": frame.lineno, "function": frame.name}
            for frame in traceback.extract_tb(exc.__traceback__)]


async def database_error(request: Request, exc: Exception):
    conflict = isinstance(exc, IntegrityError)
    status = 409 if conflict else 503
    code = "DATABASE_CONFLICT" if conflict else "SERVICE_UNAVAILABLE"
    message = "Database constraint conflict" if conflict else "Service unavailable"
    log_event(logging.ERROR, "database_error", request_id=request.state.request_id,
              status=status, exception_type=type(exc).__name__, traceback=safe_trace(exc))
    return error_response(request, status, code, message)


class ErrorHandlingMiddleware:
    """Handle unexpected errors inside CORS so error responses get its headers."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        response_started = False

        async def tracked_send(message: Message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, tracked_send)
        except Exception as exc:
            log_event(logging.ERROR, "unexpected_error", request_id=scope["state"]["request_id"],
                      status=500, exception_type=type(exc).__name__, traceback=safe_trace(exc))
            if response_started:
                raise
            response = error_response(Request(scope), 500, "INTERNAL_SERVER_ERROR", "Internal server error")
            await response(scope, receive, send)


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = str(uuid4())
        scope.setdefault("state", {})["request_id"] = request_id
        started = time.perf_counter()
        status = 500

        async def tracked_send(message: Message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message)["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, tracked_send)
        finally:
            # Use route templates rather than user-supplied path/query values.
            route = getattr(scope.get("route"), "path", "<unmatched>")
            log_event(logging.INFO, "api_request", request_id=request_id,
                      method=scope["method"], route=route, status=status,
                      duration_ms=round((time.perf_counter() - started) * 1000, 2))


def configure_api(app: FastAPI) -> None:
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    # Uvicorn's default access log includes the query string; ours does not.
    logging.getLogger("uvicorn.access").disabled = True
    # Last added runs first: logging -> CORS -> error handling -> routes.
    app.add_middleware(ErrorHandlingMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=CORS_ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Request-ID", "Accept"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(RequestLoggingMiddleware)
    app.add_exception_handler(HTTPException, http_error)
    app.add_exception_handler(RequestValidationError, validation_error)
    app.add_exception_handler(SQLAlchemyError, database_error)
    app.add_exception_handler(OSError, database_error)

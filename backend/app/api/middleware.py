"""API middleware: request id + access logging."""

from __future__ import annotations

import time

from fastapi import Request

from ..infra.logging import (
    get_logger,
    new_request_id,
    reset_request_id,
    set_request_id,
)

logger = get_logger(__name__)


async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or new_request_id()
    token = set_request_id(request_id)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("request failed: %s %s", request.method, request.url.path)
        reset_request_id(token)
        raise
    elapsed_ms = (time.perf_counter() - started) * 1000
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "%s %s -> %s %.1fms",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    reset_request_id(token)
    return response

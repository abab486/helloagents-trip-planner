"""UTF-8 logging with request_id propagation.

The old code used print() with emoji, which can crash on a GBK Windows console.
New API/service code uses this logger; request_id is carried in a ContextVar.
"""

from __future__ import annotations

import logging
import sys
import uuid
from contextvars import ContextVar

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")
_CONFIGURED = False


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


def get_request_id() -> str:
    return request_id_ctx.get()


def set_request_id(value: str):
    return request_id_ctx.set(value)


def reset_request_id(token) -> None:
    request_id_ctx.reset(token)


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        return True


def configure_logging(level: str = "INFO") -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return

    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 - some streams do not support it
        pass

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"
        )
    )
    handler.addFilter(RequestIdFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

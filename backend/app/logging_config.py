"""Structured logging with request context propagation.

Provides:
- ``request_ctx``  — per-request context (request_id, user_id, …)
- ``ContextFilter`` — injects context into every log record
- ``JsonFormatter`` / ``DevFormatter`` — production / development formatters
- ``setup_logging(app_env)`` — one-call bootstrap
- ``log_external_call(service, op)`` — context manager that times external calls
"""
from __future__ import annotations

import contextvars
import json
import logging
import time
from contextlib import contextmanager

# ---------------------------------------------------------------------------
# Request context
# ---------------------------------------------------------------------------

request_ctx: contextvars.ContextVar[dict] = contextvars.ContextVar(
    "request_ctx", default={}
)


def enrich_ctx(**kwargs: str) -> None:
    """Add fields to the current request context (in-place)."""
    ctx = request_ctx.get()
    ctx.update(kwargs)
    request_ctx.set(ctx)


# ---------------------------------------------------------------------------
# Logging filter — injects context into every log record
# ---------------------------------------------------------------------------

_CTX_FIELDS = ("request_id", "user_id", "conversation_id", "agent_role")


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        ctx = request_ctx.get()
        for field in _CTX_FIELDS:
            setattr(record, field, ctx.get(field, "-"))
        return True


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

class JsonFormatter(logging.Formatter):
    """Single-line JSON per log record — for production / Render logs."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
            "user_id": getattr(record, "user_id", "-"),
            "conversation_id": getattr(record, "conversation_id", "-"),
            "agent_role": getattr(record, "agent_role", "-"),
        }
        if record.exc_info and record.exc_info[1]:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


class DevFormatter(logging.Formatter):
    """Coloured, human-readable format — for local development."""

    fmt = "%(levelname)-8s [%(request_id)s] %(name)s: %(message)s"

    def format(self, record: logging.LogRecord) -> str:
        # Ensure context fields exist even outside request scope
        for field in _CTX_FIELDS:
            if not hasattr(record, field):
                setattr(record, field, "-")
        self._style._fmt = self.fmt
        return super().format(record)


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def setup_logging(app_env: str = "development") -> None:
    """Configure root logger. Call once, before any other module creates loggers."""
    root = logging.getLogger()
    root.handlers.clear()

    handler = logging.StreamHandler()
    handler.addFilter(ContextFilter())

    if app_env == "production":
        handler.setFormatter(JsonFormatter())
        root.setLevel(logging.INFO)
    else:
        handler.setFormatter(DevFormatter())
        root.setLevel(logging.DEBUG)

    root.addHandler(handler)

    # Suppress noisy third-party loggers
    for noisy in ("httpx", "httpcore", "openai", "urllib3", "asyncio", "watchfiles"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# External call timing
# ---------------------------------------------------------------------------

@contextmanager
def log_external_call(service: str, operation: str):
    """Context manager that logs timing for external service calls.

    Usage::

        with log_external_call("amocrm", "POST /leads"):
            resp = httpx.post(...)
    """
    log = logging.getLogger(f"external.{service}")
    start = time.perf_counter()
    try:
        yield
    except Exception as exc:
        duration_ms = int((time.perf_counter() - start) * 1000)
        log.error("%s failed duration_ms=%d error=%s", operation, duration_ms, str(exc)[:200])
        raise
    else:
        duration_ms = int((time.perf_counter() - start) * 1000)
        log.info("%s ok duration_ms=%d", operation, duration_ms)

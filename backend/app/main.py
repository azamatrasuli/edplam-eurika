from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from time import perf_counter, time as _time

from app.config import get_settings

settings = get_settings()

# --- Logging must be configured before any other module creates loggers ---
from app.logging_config import request_ctx, setup_logging  # noqa: E402

setup_logging(settings.app_env)

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.exceptions import RequestValidationError  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

from app.api.chat import router as chat_router  # noqa: E402
from app.api.conversations import router as conversations_router  # noqa: E402
from app.api.dashboard import router as dashboard_router  # noqa: E402
from app.api.onboarding import router as onboarding_router  # noqa: E402
from app.api.renewal import router as renewal_router  # noqa: E402
from app.api.telegram import router as telegram_router  # noqa: E402
from app.db.pool import close_pool, init_pool  # noqa: E402
from app.errors import error_response  # noqa: E402


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_pool()
    from app.services.scheduler import start_scheduler, stop_scheduler
    start_scheduler()
    yield
    stop_scheduler()
    close_pool()


app = FastAPI(title="EdPalm AI Seller API", version="0.1.0", lifespan=lifespan)

def _is_allowed_origin(origin: str) -> bool:
    """Check if origin is allowed — supports .vercel.app wildcard."""
    if origin in settings.cors_origins:
        return True
    if origin.endswith(".vercel.app") and origin.startswith("https://"):
        return True
    return False


class DynamicCORSMiddleware(CORSMiddleware):
    """CORS middleware that allows any *.vercel.app origin dynamically."""

    def is_allowed_origin(self, origin: str) -> bool:
        return _is_allowed_origin(origin)


app.add_middleware(
    DynamicCORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---- Simple in-memory rate limiter ----------------------------------------
# Limits per-IP requests to expensive endpoints (LLM, Whisper).
# Not a substitute for WAF/CDN rate limiting in production.

_rate_buckets: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT = 30          # max requests per window
_RATE_WINDOW = 60.0       # seconds
_RATE_PATHS = {"/api/v1/chat/stream", "/api/v1/chat/voice", "/api/v1/chat/transcribe"}


def _check_rate_limit(key: str) -> bool:
    """Return True if the request is allowed, False if rate-limited."""
    now = _time()
    bucket = _rate_buckets[key]
    # Prune old entries
    cutoff = now - _RATE_WINDOW
    _rate_buckets[key] = bucket = [t for t in bucket if t > cutoff]
    if len(bucket) >= _RATE_LIMIT:
        return False
    bucket.append(now)
    return True


@app.middleware("http")
async def with_request_id(request: Request, call_next):
    req_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    started = perf_counter()

    # Set request context for structured logging
    token = request_ctx.set({"request_id": req_id})

    # Rate limit expensive endpoints
    if request.url.path in _RATE_PATHS:
        client_ip = request.client.host if request.client else "unknown"
        if not _check_rate_limit(client_ip):
            request_ctx.reset(token)
            resp = error_response("rate_limit")
            resp.headers["Retry-After"] = "60"
            resp.headers["x-request-id"] = req_id
            return resp

    response = await call_next(request)
    duration_ms = int((perf_counter() - started) * 1000)
    response.headers["x-request-id"] = req_id
    response.headers["x-response-time-ms"] = str(duration_ms)

    logger = logging.getLogger("app.request")
    logger.info(
        "request_complete path=%s method=%s status=%d duration_ms=%d",
        request.url.path, request.method, response.status_code, duration_ms,
    )

    request_ctx.reset(token)
    return response


# --- Pydantic validation errors → user-friendly Russian messages ---

_FIELD_ERROR_MAP = {
    "message": {
        "string_too_long": "message_too_long",
        "string_too_short": "message_empty",
        "value_error": "message_empty",
    },
}


@app.exception_handler(RequestValidationError)
async def validation_exc_handler(request: Request, exc: RequestValidationError):
    for err in exc.errors():
        loc = err.get("loc", ())
        field = loc[-1] if loc else None
        err_type = err.get("type", "")
        field_map = _FIELD_ERROR_MAP.get(field, {})
        code = field_map.get(err_type)
        if code:
            return error_response(code)
    return error_response("validation_error")


@app.exception_handler(Exception)
async def unhandled_exc_handler(request: Request, exc: Exception):
    logger = logging.getLogger("app")
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return error_response("internal_error")


@app.get("/health")
def health():
    return {"status": "ok", "service": "ai-agent-seller", "version": "0.1.0"}


app.include_router(chat_router)
app.include_router(conversations_router)
app.include_router(dashboard_router)
app.include_router(onboarding_router)
app.include_router(renewal_router)
app.include_router(telegram_router)

# Alias: amoCRM Chat API webhook registered without /v1 prefix
from app.api.chat import amocrm_chat_webhook as _wh  # noqa: E402
app.post("/api/amocrm/chat/webhook/{scope_id}", include_in_schema=False)(_wh)

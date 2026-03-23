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
    # Close httpx clients to prevent resource leaks
    try:
        from app.api.chat import chat_service, imbox_service
        if hasattr(chat_service, 'crm') and chat_service.crm and hasattr(chat_service.crm, '_http'):
            chat_service.crm._http.close()
        if hasattr(imbox_service, '_service') and hasattr(imbox_service._service, '_http'):
            imbox_service._service._http.close()
    except Exception:
        pass
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


# ---- Rate limiting (per-user + per-IP) ------------------------------------

from app.rate_limit import check_ip_rate, check_user_rate, get_endpoint_group, is_force_new_conversation


def _extract_actor_id_from_request(body_bytes: bytes, path: str) -> str | None:
    """Try to extract actor_id from request body auth payload. Lightweight, no full auth."""
    import json as _json
    try:
        body = _json.loads(body_bytes)
        auth = body.get("auth") if isinstance(body, dict) else None
        if not auth:
            return None
        # Guest
        if auth.get("guest_id"):
            return f"guest:{auth['guest_id']}"
        # Portal JWT — extract user_id from payload without full verification
        if auth.get("portal_token"):
            import base64
            parts = auth["portal_token"].split(".")
            if len(parts) >= 2:
                padded = parts[1] + "=" * (4 - len(parts[1]) % 4)
                payload = _json.loads(base64.b64decode(padded))
                uid = payload.get("user_id")
                if uid:
                    return f"portal:{uid}"
        # Telegram
        if auth.get("telegram_init_data"):
            from urllib.parse import parse_qs
            params = parse_qs(auth["telegram_init_data"])
            user_json = params.get("user", [None])[0]
            if user_json:
                user = _json.loads(user_json)
                if user.get("id"):
                    return f"telegram:{user['id']}"
        # External
        if auth.get("external_token"):
            parts = auth["external_token"].split(":")
            if len(parts) >= 1:
                return f"external:{parts[0]}"
    except Exception:
        pass
    return None


@app.middleware("http")
async def with_request_id(request: Request, call_next):
    req_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    started = perf_counter()

    # Set request context for structured logging
    token = request_ctx.set({"request_id": req_id})

    path = request.url.path
    client_ip = request.client.host if request.client else "unknown"

    # 1. Global per-IP rate limit (DDoS protection)
    if get_endpoint_group(path) is not None:
        ip_allowed, ip_retry = check_ip_rate(client_ip)
        if not ip_allowed:
            request_ctx.reset(token)
            resp = error_response("rate_limit")
            resp.headers["Retry-After"] = str(ip_retry)
            resp.headers["x-request-id"] = req_id
            return resp

    # 2. Per-user rate limit (read body for auth)
    if get_endpoint_group(path) is not None and request.method == "POST":
        try:
            body_bytes = await request.body()
            actor_id = _extract_actor_id_from_request(body_bytes, path)
            if actor_id:
                # Special handling: only rate-limit conversation_create for force_new
                import json as _json
                body_dict = _json.loads(body_bytes) if body_bytes else {}
                if path == "/api/v1/conversations/start" and not body_dict.get("force_new"):
                    pass  # Resume existing conversation — no rate limit
                else:
                    allowed, msg, retry_after = check_user_rate(actor_id, path)
                    if not allowed:
                        request_ctx.reset(token)
                        from fastapi.responses import JSONResponse
                        resp = JSONResponse(
                            status_code=429,
                            content={"error": msg, "code": "rate_limit", "retry_after": retry_after},
                        )
                        resp.headers["Retry-After"] = str(retry_after)
                        resp.headers["x-request-id"] = req_id
                        return resp
        except Exception:
            pass  # Rate limit extraction failed — allow request through

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
from app.api.chat import amocrm_chat_webhook as _wh, amocrm_chat_webhook_no_scope as _wh_ns  # noqa: E402
app.post("/api/amocrm/chat/webhook/{scope_id}", include_in_schema=False)(_wh)
app.post("/api/amocrm/chat/webhook", include_in_schema=False)(_wh_ns)

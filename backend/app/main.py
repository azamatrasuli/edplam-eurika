from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from time import perf_counter

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s: %(message)s")

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.chat import router as chat_router
from app.api.conversations import router as conversations_router
from app.api.dashboard import router as dashboard_router
from app.api.onboarding import router as onboarding_router
from app.api.renewal import router as renewal_router
from app.api.telegram import router as telegram_router
from app.config import get_settings
from app.db.pool import close_pool, init_pool

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_pool()
    from app.services.scheduler import start_scheduler, stop_scheduler
    start_scheduler()
    yield
    stop_scheduler()
    close_pool()


app = FastAPI(title="EdPalm AI Seller API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def with_request_id(request: Request, call_next):
    req_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    started = perf_counter()
    response = await call_next(request)
    duration_ms = int((perf_counter() - started) * 1000)
    response.headers["x-request-id"] = req_id
    response.headers["x-response-time-ms"] = str(duration_ms)
    return response


@app.exception_handler(Exception)
async def unhandled_exc_handler(request: Request, exc: Exception):
    logger = logging.getLogger("app")
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"error": "internal_error", "detail": "Внутренняя ошибка сервера"})


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

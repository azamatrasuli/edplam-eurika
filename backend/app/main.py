from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.chat import router as chat_router
from app.config import get_settings
from app.db.pool import close_pool, init_pool

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_pool()
    yield
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
async def unhandled_exc_handler(_: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"error": "internal_error", "detail": str(exc)})


@app.get("/health")
def health():
    return {"status": "ok", "service": "ai-agent-seller", "version": "0.1.0"}


app.include_router(chat_router)

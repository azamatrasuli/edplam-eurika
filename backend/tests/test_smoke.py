from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.parse

import jwt

from fastapi.testclient import TestClient

os.environ.setdefault("EXTERNAL_LINK_SECRET", "test_secret")
os.environ.setdefault("PORTAL_JWT_SECRET", "test_portal")
os.environ.setdefault("SESSION_SIGNING_SECRET", "test_session")
os.environ.setdefault("OPENAI_API_KEY", "")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_tg_token")

from app.main import app  # noqa: E402

client = TestClient(app)


def _external_token(lead_id: str) -> str:
    exp = str(int(time.time()) + 3600)
    payload = f"{lead_id}:{exp}".encode("utf-8")
    sign = hmac.new(b"test_secret", payload, hashlib.sha256).hexdigest()
    return f"{lead_id}:{exp}:{sign}"


def _portal_jwt(user_id: str = "user-1") -> str:
    payload = {
        "user_id": user_id,
        "name": "Parent Test",
        "phone": "+79990000000",
        "exp": int(time.time()) + 900,
    }
    return jwt.encode(payload, "test_portal", algorithm="HS256")


def _telegram_init_data() -> str:
    user = {
        "id": 123456,
        "first_name": "Ivan",
        "last_name": "Petrov",
        "username": "ivanpetrov",
    }
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAEAAAE",
        "user": json.dumps(user, separators=(",", ":")),
    }
    data_check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields.keys()))
    secret = hmac.new(b"WebAppData", b"test_tg_token", hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, data_check.encode("utf-8"), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(fields)


def test_health_ok() -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_start_conversation_external_token() -> None:
    token = _external_token("lead-123")
    r = client.post("/api/v1/conversations/start", json={"auth": {"external_token": token}})
    assert r.status_code == 200
    body = r.json()
    assert body["conversation_id"]
    assert body["actor"]["channel"] == "external"


def test_start_conversation_portal_token() -> None:
    token = _portal_jwt()
    r = client.post("/api/v1/conversations/start", json={"auth": {"portal_token": token}})
    assert r.status_code == 200
    body = r.json()
    assert body["conversation_id"]
    assert body["actor"]["channel"] == "portal"
    assert body["actor"]["display_name"] == "Parent Test"


def test_start_conversation_telegram_init_data() -> None:
    init_data = _telegram_init_data()
    r = client.post("/api/v1/conversations/start", json={"auth": {"telegram_init_data": init_data}})
    assert r.status_code == 200
    body = r.json()
    assert body["conversation_id"]
    assert body["actor"]["channel"] == "telegram"
    assert body["actor"]["display_name"] == "Ivan Petrov"


def test_stream_chat_external_token() -> None:
    token = _external_token("lead-abc")
    r = client.post(
        "/api/v1/chat/stream",
        json={"auth": {"external_token": token}, "message": "Привет"},
    )
    assert r.status_code == 200
    assert "event: done" in r.text

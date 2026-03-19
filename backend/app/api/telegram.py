"""Telegram Bot webhook handler — responds to /start with Mini App button."""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Request

from app.config import get_settings

logger = logging.getLogger("api.telegram")
router = APIRouter(tags=["telegram"])


def _send_message(bot_token: str, chat_id: int, text: str, reply_markup: dict | None = None) -> None:
    payload: dict = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        resp = httpx.post(f"https://api.telegram.org/bot{bot_token}/sendMessage", json=payload, timeout=10)
        logger.info("[telegram] sendMessage chat_id=%s status=%s", chat_id, resp.status_code)
    except Exception as e:
        logger.error("[telegram] sendMessage failed: %s", e)


@router.post("/api/telegram/webhook/{token}")
async def telegram_webhook(token: str, request: Request):
    """Handle Telegram Bot updates (webhook mode)."""
    settings = get_settings()
    if token != settings.telegram_bot_token:
        return {"ok": False}

    try:
        update = await request.json()
    except Exception:
        return {"ok": False}

    message = update.get("message")
    if not message:
        return {"ok": True}

    text = message.get("text", "")
    chat_id = message["chat"]["id"]
    first_name = message.get("from", {}).get("first_name", "")

    if text.startswith("/start"):
        logger.info("[telegram] /start from chat_id=%s name=%s", chat_id, first_name)
        greeting = first_name or "друг"
        _send_message(
            settings.telegram_bot_token,
            chat_id,
            f"Привет, {greeting}! 👋\n\n"
            f"Я <b>Эврика</b> — ИИ-помощник школы EdPalm.\n\n"
            f"Могу рассказать об обучении, помочь с выбором программы "
            f"или ответить на вопросы по учёбе.\n\n"
            f"Нажми кнопку ниже, чтобы начать 👇",
            reply_markup={
                "inline_keyboard": [[
                    {"text": "🚀 Открыть Эврику", "web_app": {"url": settings.frontend_url}}
                ]]
            },
        )
    elif text.startswith("/help"):
        _send_message(
            settings.telegram_bot_token,
            chat_id,
            "🤖 <b>Эврика — AI-помощник EdPalm</b>\n\n"
            "Нажми кнопку «Открыть Эврику» в меню или отправь /start.\n\n"
            "Я помогу с:\n"
            "• Информацией о школе и программах\n"
            "• Вопросами по обучению\n"
            "• Оформлением и документами",
        )

    return {"ok": True}

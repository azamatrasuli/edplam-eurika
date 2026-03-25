"""Shared Telegram notification helper.

Centralises the duplicated _send_telegram() pattern from:
  followup.py, support_onboarding.py, auto_escalation.py

All functions are fire-and-forget — never raise, return bool for logging.
"""
from __future__ import annotations

import logging

import httpx

from app.config import get_settings

logger = logging.getLogger("services.telegram_sender")

# HTML escape helper — reused everywhere
def esc(s: str) -> str:
    """Escape HTML special chars for Telegram HTML parse mode."""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def send_telegram_message(
    chat_id: str,
    text: str,
    parse_mode: str = "HTML",
    inline_keyboard: list | None = None,
) -> bool:
    """Send a Telegram message. Fire-and-forget. Returns True on success."""
    settings = get_settings()
    bot_token = settings.telegram_bot_token
    if not bot_token or not chat_id:
        return False

    payload: dict = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    if inline_keyboard:
        payload["reply_markup"] = {"inline_keyboard": inline_keyboard}

    try:
        resp = httpx.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json=payload,
            timeout=10,
        )
        if not resp.is_success:
            logger.warning("Telegram sendMessage failed: %s %s", resp.status_code, resp.text[:200])
            return False
        return True
    except Exception:
        logger.warning("Failed to send Telegram message to %s", chat_id, exc_info=True)
        return False


def send_telegram_to_actor(
    actor_id: str,
    text: str,
    parse_mode: str = "HTML",
    role: str = "support",
    with_open_button: bool = True,
) -> bool:
    """Send push to a telegram:* actor. Skips non-Telegram actors silently.

    Args:
        actor_id: e.g. "telegram:123456789"
        text: message body (HTML formatted)
        role: agent role for "Open Eurika" deep link (sales/support/teacher)
        with_open_button: whether to attach inline "Open Eurika" button
    """
    if not actor_id or not actor_id.startswith("telegram:"):
        return False

    chat_id = actor_id.replace("telegram:", "")

    inline_keyboard: list | None = None
    if with_open_button:
        settings = get_settings()
        frontend_url = settings.frontend_url or ""
        if frontend_url:
            inline_keyboard = [[
                {"text": "💬 Открыть Эврику", "web_app": {"url": f"{frontend_url}?role={role}"}}
            ]]

    return send_telegram_message(chat_id, text, parse_mode=parse_mode, inline_keyboard=inline_keyboard)


def send_telegram_to_manager(text: str, parse_mode: str = "HTML") -> bool:
    """Send alert to the manager group / chat. Uses MANAGER_TELEGRAM_CHAT_ID from settings."""
    settings = get_settings()
    chat_id = settings.manager_telegram_chat_id
    if not chat_id:
        logger.debug("Manager chat_id not configured, skipping Telegram alert")
        return False
    return send_telegram_message(chat_id, text, parse_mode=parse_mode)

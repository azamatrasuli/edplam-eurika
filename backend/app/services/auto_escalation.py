"""Auto-escalation: escalate support conversations idle for 48+ hours."""

from __future__ import annotations

import logging

import httpx

from app.config import get_settings
from app.db.events import EventTracker
from app.db.repository import ConversationRepository

logger = logging.getLogger("auto_escalation")


def process_idle_escalations() -> None:
    """Scheduled job: auto-escalate support conversations idle for 48h.

    Runs every 30 minutes via APScheduler. Finds active support conversations
    with no activity for 48+ hours and escalates them with a Telegram notification.
    """
    repo = ConversationRepository()
    tracker = EventTracker()

    try:
        idle_convs = repo.get_idle_support_conversations(hours=48)
    except Exception:
        logger.exception("Failed to query idle support conversations")
        return

    if not idle_convs:
        return

    logger.info("Auto-escalation: found %d idle support conversations", len(idle_convs))

    for conv in idle_convs:
        conv_id = str(conv["id"])
        actor_id = conv.get("actor_id", "")
        try:
            reason = "Автоэскалация: клиент не отвечает более 48 часов"

            repo.update_escalation_metadata(conv_id, reason)

            tracker.track_escalation(
                conv_id, actor_id, reason,
                channel=conv.get("channel"),
                agent_role="support",
            )

            _notify_auto_escalation(conv, reason)

            logger.info("Auto-escalated conv=%s actor=%s", conv_id, actor_id)
        except Exception:
            logger.exception("Auto-escalation failed for conv=%s", conv_id)


def _notify_auto_escalation(conv: dict, reason: str) -> None:
    """Send Telegram notification about auto-escalation."""
    settings = get_settings()
    chat_id = settings.manager_telegram_chat_id
    bot_token = settings.telegram_bot_token

    if not chat_id or not bot_token:
        return

    def esc(t: str) -> str:
        return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    title = esc(conv.get("title", "Без заголовка") or "Без заголовка")
    actor_id = esc(conv.get("actor_id", "—"))
    channel = esc(conv.get("channel", "—"))
    conv_id = esc(str(conv.get("id", "—")))

    text = (
        f"<b>⏰ Автоэскалация (поддержка)</b>\n\n"
        f"<b>Диалог:</b> {title}\n"
        f"<b>Клиент:</b> {actor_id}\n"
        f"<b>Канал:</b> {channel}\n"
        f"<b>Причина:</b> {esc(reason)}\n\n"
        f"<b>ID:</b> <code>{conv_id}</code>"
    )

    try:
        httpx.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception:
        logger.warning("Failed to send auto-escalation notification for conv=%s", conv.get("id"))

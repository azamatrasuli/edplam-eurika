"""Follow-up chain: automated reminders after payment link generation."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx

from app.config import get_settings
from app.db.events import EventTracker
from app.db.repository import ConversationRepository

logger = logging.getLogger("services.followup")

FOLLOWUP_DELAYS: dict[int, timedelta] = {
    1: timedelta(hours=24),
    2: timedelta(hours=48),
    3: timedelta(days=7),
}

FOLLOWUP_TEMPLATES: dict[int, str] = {
    1: (
        "Добрый день, {name}! Хотела напомнить, что ссылка на оплату "
        "{product} ещё активна. Если есть вопросы — я с радостью отвечу."
    ),
    2: (
        "Здравствуйте, {name}! Заметила, что оплата пока не прошла. "
        "Может быть, что-то смущает? Буду рада помочь разобраться."
    ),
    3: (
        "Добрый день, {name}! Это последнее напоминание о записи на {product}. "
        "Напишите, если рассматриваете наше предложение — подберу оптимальный вариант."
    ),
}


def create_followup_chain(
    repo: ConversationRepository,
    conversation_id: str,
    actor_id: str,
    payment_order_id: str,
) -> None:
    """Schedule all 3 follow-up steps for a payment order."""
    now = datetime.now(timezone.utc)
    for step, delay in FOLLOWUP_DELAYS.items():
        fire_at = now + delay
        try:
            repo.save_followup(
                conversation_id=conversation_id,
                actor_id=actor_id,
                payment_order_id=payment_order_id,
                step=step,
                next_fire_at=fire_at,
            )
            logger.info(
                "Follow-up step %d scheduled for %s (conv=%s)",
                step, fire_at.isoformat(), conversation_id,
            )
        except Exception:
            logger.exception("Failed to save follow-up step %d", step)


def process_pending_followups() -> None:
    """Scheduled job: send due follow-up messages."""
    repo = ConversationRepository()

    try:
        due = repo.get_pending_followups()
    except Exception:
        logger.exception("Failed to fetch pending follow-ups")
        return

    if not due:
        return

    logger.info("Processing %d due follow-ups", len(due))
    now = datetime.now(timezone.utc)

    for f in due:
        try:
            # Route onboarding follow-ups to dedicated handler
            if f.get("chain_type") == "onboarding":
                from app.services.support_onboarding import process_onboarding_followup
                process_onboarding_followup(f)
                continue

            # Skip if payment already confirmed
            if f.get("payment_status") == "paid":
                repo.update_followup_status(f["id"], "cancelled")
                continue

            step = f["step"]
            name = f.get("actor_name") or "клиент"
            product = f.get("product_name") or "обучение"

            template = FOLLOWUP_TEMPLATES.get(step)
            if not template:
                logger.warning("No template for follow-up step %d", step)
                repo.update_followup_status(f["id"], "cancelled")
                continue

            text = template.format(name=name, product=product)

            # Save as assistant message in the conversation
            repo.save_message(
                conversation_id=f["conversation_id"],
                role="assistant",
                content=text,
            )
            repo.update_followup_status(f["id"], "sent", sent_at=now)
            EventTracker().track_followup(
                f["conversation_id"], f.get("actor_id", ""), step,
                payment_order_id=str(f.get("payment_order_id", "")),
            )
            logger.info("Follow-up step %d sent for conv=%s", step, f["conversation_id"])

            # Send Telegram push if user has telegram_id
            _send_telegram_notification(f.get("actor_id"), text)

            # After step 3 — escalate to manager
            if step == 3:
                _escalate_after_followup(f)

        except Exception:
            logger.exception("Error processing follow-up id=%s", f["id"])


def _send_telegram_notification(actor_id: str | None, text: str) -> None:
    """Send push notification via Telegram bot (for telegram users)."""
    if not actor_id or not actor_id.startswith("telegram:"):
        return

    settings = get_settings()
    bot_token = settings.telegram_bot_token
    if not bot_token:
        return

    chat_id = actor_id.replace("telegram:", "")
    try:
        httpx.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
        logger.info("Telegram follow-up sent to %s", chat_id)
    except Exception:
        logger.exception("Failed to send Telegram follow-up to %s", chat_id)


def _escalate_after_followup(followup: dict) -> None:
    """Escalate to manager after 3 unanswered follow-ups."""
    settings = get_settings()
    chat_id = settings.manager_telegram_chat_id
    bot_token = settings.telegram_bot_token

    if not chat_id or not bot_token:
        return

    def _esc(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    product = followup.get("product_name", "—")
    actor_name = followup.get("actor_name", "—")
    conv_id = followup.get("conversation_id", "—")

    text = (
        f"<b>Follow-up: 3 напоминания без ответа</b>\n\n"
        f"<b>Клиент:</b> {_esc(actor_name)}\n"
        f"<b>Продукт:</b> {_esc(product)}\n"
        f"<b>ID диалога:</b> <code>{conv_id}</code>\n\n"
        "Рекомендуется связаться с клиентом лично."
    )

    try:
        httpx.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        logger.info("Follow-up escalation sent to manager for conv=%s", conv_id)
    except Exception:
        logger.exception("Failed to send follow-up escalation")

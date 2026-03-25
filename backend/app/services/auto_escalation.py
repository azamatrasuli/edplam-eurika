"""Auto-escalation: escalate support conversations idle for 48+ hours."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.db.events import EventTracker
from app.db.repository import ConversationRepository
from app.services.telegram_sender import esc, send_telegram_to_manager

logger = logging.getLogger("auto_escalation")


def process_idle_escalations() -> None:
    """Scheduled job: auto-escalate support conversations idle for 48h.

    Runs every 30 minutes via APScheduler. Finds active support conversations
    with no activity for 48+ hours and escalates them with a Telegram notification.
    Also records alert in agent_notifications for Sprint 6 metrics.
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

            _notify_auto_escalation(conv)
            _record_nonresponsive_alert(actor_id, conv)

            logger.info("Auto-escalated conv=%s actor=%s", conv_id, actor_id)
        except Exception:
            logger.exception("Auto-escalation failed for conv=%s", conv_id)


def _notify_auto_escalation(conv: dict) -> None:
    """Send enriched Telegram alert to manager about idle conversation."""
    conv_id = str(conv.get("id") or "—")
    actor_id = conv.get("actor_id") or "—"
    channel = conv.get("channel") or "—"
    title = conv.get("title") or "Без заголовка"

    # Compute hours idle
    updated_at = conv.get("updated_at")
    hours_idle = "48+"
    if updated_at:
        try:
            if isinstance(updated_at, datetime):
                delta = datetime.now(timezone.utc) - updated_at.replace(tzinfo=timezone.utc) if updated_at.tzinfo is None else datetime.now(timezone.utc) - updated_at
                hours_idle = str(int(delta.total_seconds() // 3600))
        except Exception:
            pass

    text = (
        f"<b>⏰ Клиент не отвечает</b>\n\n"
        f"<b>Клиент:</b> {esc(actor_id)}\n"
        f"<b>Диалог:</b> {esc(title)}\n"
        f"<b>Ожидаем:</b> ответа клиента\n"
        f"<b>Без ответа:</b> {esc(hours_idle)}ч\n"
        f"<b>Канал:</b> {esc(channel)}\n"
        f"<b>ID:</b> <code>{esc(conv_id)}</code>\n\n"
        f"Рекомендуется связаться лично."
    )

    send_telegram_to_manager(text)


def _record_nonresponsive_alert(actor_id: str, conv: dict) -> None:
    """Record alert in agent_notifications for Sprint 6 metrics tracking."""
    try:
        from datetime import date
        from app.services.notifications import schedule_notification

        conv_id = str(conv.get("id") or "")
        dedup_key = f"alert_nonresponsive:{actor_id}:{date.today().isoformat()}"

        # Compute hours idle
        updated_at = conv.get("updated_at")
        hours_idle = "48"
        if updated_at:
            try:
                if isinstance(updated_at, datetime):
                    delta = datetime.now(timezone.utc) - (
                        updated_at.replace(tzinfo=timezone.utc) if updated_at.tzinfo is None else updated_at
                    )
                    hours_idle = str(int(delta.total_seconds() // 3600))
            except Exception:
                pass

        schedule_notification(
            actor_id=actor_id,
            notification_type="alert_nonresponsive",
            scheduled_at=datetime.now(timezone.utc),
            template_data={
                "name": conv.get("actor_id") or "—",
                "waiting_for": "ответа клиента",
                "hours": hours_idle,
                "product": "",
                "channel": conv.get("channel") or "—",
                "conv_id": conv_id,
            },
            dedup_key=dedup_key,
            conversation_id=conv_id or None,
        )
    except Exception:
        logger.warning("Failed to record nonresponsive alert in notifications for actor=%s", actor_id, exc_info=True)

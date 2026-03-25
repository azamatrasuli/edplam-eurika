"""Notification service: schedule, process, and cancel proactive notifications.

Handles all 7 notification types defined in Sprint 4:
  Client notifications:
    - payment_reminder (3d / 1d / same-day)
    - classes_reminder     [STUB — awaiting DMS schedule API]
    - homework_reminder    [STUB — awaiting DMS homework API]
    - document_reminder    (day 3 after payment)
    - enrollment_congrats  [STUB — awaiting DMS enrollment event clarity]
  Manager alerts:
    - alert_nonresponsive  (client silent 48h+)
    - alert_performance_drop [STUB — awaiting DMS grades API]

Architecture:
  - schedule_notification()  → INSERT into agent_notifications (dedup via unique index)
  - process_pending()        → SELECT due rows → render → send → mark sent
  - cancel_notifications()   → UPDATE status='cancelled'
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.types.json import Json

from app.db.events import EventTracker
from app.db.pool import get_connection, has_pool
from app.services.telegram_sender import esc, send_telegram_to_actor, send_telegram_to_manager

logger = logging.getLogger("services.notifications")

# ---------------------------------------------------------------------------
# Message templates
# ---------------------------------------------------------------------------

_PAYMENT_REMINDER_3D = (
    "{name}, добрый день! 🗓\n\n"
    "Через 3 дня подходит срок оплаты по программе «{product}» ({grade} класс).\n"
    "Сумма: <b>{amount} ₽</b>\n"
    "Оплатить: {payment_url}\n\n"
    "Если есть вопросы — напишите мне!"
)

_PAYMENT_REMINDER_1D = (
    "{name}, завтра срок оплаты по программе «{product}» ⏰\n\n"
    "Сумма: <b>{amount} ₽</b>\n"
    "Оплатить: {payment_url}\n\n"
    "Если уже оплатили — напишите, проверю статус."
)

_PAYMENT_REMINDER_0D = (
    "{name}, сегодня последний день оплаты по программе «{product}» 🔔\n\n"
    "Сумма: <b>{amount} ₽</b>\n"
    "Оплатить: {payment_url}\n\n"
    "Если возникли сложности — пишите, помогу разобраться!"
)

_DOCUMENT_REMINDER = (
    "{name}, добрый день! 📄\n\n"
    "Прошло 3 дня после оплаты. Напоминаю про важный шаг:\n"
    "загрузите документы в личном кабинете (регистрационная форма).\n\n"
    "Срок: 10 рабочих дней с момента оплаты.\n"
    "Куда: edpalm-exam.online › Личный кабинет › Документы\n\n"
    "Нужна помощь с загрузкой? Напишите мне!"
)

_ENROLLMENT_CONGRATS = (
    "🎓 {name}, поздравляю!\n\n"
    "{child_name} официально зачислен(а) в EdPalm!\n"
    "Программа: «{product}», {grade} класс.\n\n"
    "Что дальше:\n"
    "1️⃣ Расписание появится в личном кабинете\n"
    "2️⃣ Куратор свяжется с вами в ближайшие дни\n"
    "3️⃣ Все инструкции — в разделе «Информация» › «Всё для старта»\n\n"
    "Если есть вопросы — я всегда рядом!"
)

_ALERT_NONRESPONSIVE = (
    "<b>⏰ Клиент не отвечает</b>\n\n"
    "<b>Клиент:</b> {name}\n"
    "<b>Ожидаем:</b> {waiting_for}\n"
    "<b>Без ответа:</b> {hours}ч\n"
    "<b>Продукт:</b> {product}\n"
    "<b>Канал:</b> {channel}\n"
    "<b>ID диалога:</b> <code>{conv_id}</code>\n\n"
    "Рекомендуется связаться лично."
)

_ALERT_PERFORMANCE_DROP = (
    "<b>📉 Падение успеваемости</b>\n\n"
    "<b>Ученик:</b> {student_name}, {grade} класс\n"
    "<b>Программа:</b> {product}\n"
    "<b>Родитель:</b> {parent_name}\n"
    "<b>Показатели (2 нед.):</b> посещаемость {attendance}%\n\n"
    "Рекомендуем care-call."
)

# Stubs for blocked features
_CLASSES_REMINDER = (
    "{name}, завтра уроки! 📚\n\n"
    "Расписание: {schedule}\n"
    "Войти на платформу: {platform_url}"
)

_HOMEWORK_REMINDER = (
    "{name}, не забудь! ✏️\n\n"
    "Домашнее задание «{homework_name}» нужно сдать до завтра.\n"
    "Удачи!"
)


# ---------------------------------------------------------------------------
# Template renderer
# ---------------------------------------------------------------------------

def _render_template(notification_type: str, data: dict[str, Any]) -> str | None:
    """Render notification text from template_data. Returns None if type is stub/unknown."""

    def _safe(key: str, default: str = "—") -> str:
        return esc(str(data.get(key) or default))

    if notification_type == "payment_reminder":
        days = data.get("days_before", 0)
        tpl = {3: _PAYMENT_REMINDER_3D, 1: _PAYMENT_REMINDER_1D, 0: _PAYMENT_REMINDER_0D}.get(days)
        if not tpl:
            return None
        return tpl.format(
            name=_safe("name", "друг"),
            product=_safe("product"),
            grade=_safe("grade"),
            amount=_safe("amount"),
            payment_url=data.get("payment_url") or "—",
        )

    if notification_type == "document_reminder":
        return _DOCUMENT_REMINDER.format(name=_safe("name", "друг"))

    if notification_type == "enrollment_congrats":
        return _ENROLLMENT_CONGRATS.format(
            name=_safe("name", "друг"),
            child_name=_safe("child_name"),
            product=_safe("product"),
            grade=_safe("grade"),
        )

    if notification_type == "alert_nonresponsive":
        return _ALERT_NONRESPONSIVE.format(
            name=_safe("name"),
            waiting_for=_safe("waiting_for", "ответа клиента"),
            hours=_safe("hours", "48"),
            product=_safe("product"),
            channel=_safe("channel"),
            conv_id=_safe("conv_id"),
        )

    if notification_type == "alert_performance_drop":
        return _ALERT_PERFORMANCE_DROP.format(
            student_name=_safe("student_name"),
            grade=_safe("grade"),
            product=_safe("product"),
            parent_name=_safe("parent_name"),
            attendance=_safe("attendance", "?"),
        )

    if notification_type == "classes_reminder":
        return _CLASSES_REMINDER.format(
            name=_safe("name", "друг"),
            schedule=_safe("schedule", "смотри в ЛК"),
            platform_url=data.get("platform_url") or "edpalm-exam.online",
        )

    if notification_type == "homework_reminder":
        return _HOMEWORK_REMINDER.format(
            name=_safe("name", "друг"),
            homework_name=_safe("homework_name"),
        )

    logger.warning("Unknown notification_type: %s", notification_type)
    return None


# ---------------------------------------------------------------------------
# Core service functions
# ---------------------------------------------------------------------------

def schedule_notification(
    actor_id: str,
    notification_type: str,
    scheduled_at: datetime,
    template_data: dict[str, Any],
    dedup_key: str | None = None,
    conversation_id: str | None = None,
    channel: str = "telegram",
) -> str | None:
    """Schedule a notification. Returns notification ID or None on failure/dedup skip.

    Dedup: if dedup_key already exists with status != 'cancelled', silently skips.
    """
    if not has_pool():
        logger.debug("No DB pool — notification not scheduled (type=%s actor=%s)", notification_type, actor_id)
        return None
    try:
        with get_connection() as conn:
            if conn is None:
                return None
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO agent_notifications
                        (actor_id, conversation_id, notification_type, scheduled_at,
                         template_data, dedup_key, channel)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (dedup_key) WHERE dedup_key IS NOT NULL DO NOTHING
                    RETURNING id
                    """,
                    (
                        actor_id,
                        conversation_id,
                        notification_type,
                        scheduled_at,
                        Json(template_data),
                        dedup_key,
                        channel,
                    ),
                )
                row = cur.fetchone()
            conn.commit()

        if row:
            notif_id = str(row["id"])
            logger.info(
                "Notification scheduled: type=%s actor=%s at=%s id=%s",
                notification_type, actor_id, scheduled_at.isoformat(), notif_id,
            )
            return notif_id
        else:
            logger.debug("Notification dedup skip: key=%s", dedup_key)
            return None
    except (psycopg.Error, OSError):
        logger.exception("Failed to schedule notification type=%s actor=%s", notification_type, actor_id)
        return None


def cancel_notifications(
    actor_id: str,
    notification_type: str | None = None,
    conversation_id: str | None = None,
) -> int:
    """Cancel pending notifications for an actor. Returns count cancelled."""
    if not has_pool():
        return 0
    try:
        with get_connection() as conn:
            if conn is None:
                return 0
            with conn.cursor() as cur:
                conditions = ["actor_id = %s", "status = 'pending'"]
                params: list[Any] = [actor_id]

                if notification_type:
                    conditions.append("notification_type = %s")
                    params.append(notification_type)
                if conversation_id:
                    conditions.append("conversation_id = %s")
                    params.append(conversation_id)

                cur.execute(
                    f"""
                    UPDATE agent_notifications
                    SET status = 'cancelled', cancelled_at = NOW(), updated_at = NOW()
                    WHERE {" AND ".join(conditions)}
                    """,
                    params,
                )
                count = cur.rowcount
            conn.commit()
        if count:
            logger.info("Cancelled %d notifications for actor=%s type=%s", count, actor_id, notification_type)
        return count
    except (psycopg.Error, OSError):
        logger.exception("Failed to cancel notifications for actor=%s", actor_id)
        return 0


def process_pending_notifications() -> None:
    """Scheduled job: find due notifications, send them, mark sent.

    Runs every 2 minutes via APScheduler.
    Handles client notifications via Telegram + manager alerts to manager chat.
    """
    if not has_pool():
        return
    try:
        with get_connection() as conn:
            if conn is None:
                return
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, actor_id, conversation_id, notification_type, template_data, channel
                    FROM agent_notifications
                    WHERE status = 'pending' AND scheduled_at <= NOW()
                    ORDER BY scheduled_at
                    LIMIT 50
                    """,
                )
                rows = cur.fetchall()
    except (psycopg.Error, OSError):
        logger.exception("Failed to query pending notifications")
        return

    if not rows:
        return

    logger.info("Processing %d pending notifications", len(rows))
    tracker = EventTracker()

    for row in rows:
        notif_id = str(row["id"])
        actor_id = row["actor_id"]
        notification_type = row["notification_type"]
        template_data = dict(row["template_data"]) if row["template_data"] else {}
        conversation_id = row["conversation_id"]

        try:
            text = _render_template(notification_type, template_data)
            if text is None:
                _mark_notification(notif_id, "failed")
                logger.warning("Could not render template for notif_id=%s type=%s", notif_id, notification_type)
                continue

            # Route: manager alerts → manager chat, client notifications → actor
            is_manager_alert = notification_type.startswith("alert_")
            if is_manager_alert:
                ok = send_telegram_to_manager(text)
            else:
                ok = send_telegram_to_actor(actor_id, text, role="support")

            status = "sent" if ok else "failed"
            _mark_notification(notif_id, status)

            if ok:
                tracker.track(
                    "notification_sent",
                    conversation_id=str(conversation_id) if conversation_id else None,
                    actor_id=actor_id,
                    agent_role="support",
                    data={"notification_type": notification_type, "notification_id": notif_id},
                )
                logger.info("Notification sent: type=%s actor=%s id=%s", notification_type, actor_id, notif_id)
            else:
                logger.warning("Notification failed to send: type=%s id=%s", notification_type, notif_id)

        except Exception:
            logger.exception("Unexpected error processing notification id=%s", notif_id)
            _mark_notification(notif_id, "failed")


def _mark_notification(notif_id: str, status: str) -> None:
    """Update notification status (sent/failed/cancelled)."""
    if not has_pool():
        return
    try:
        with get_connection() as conn:
            if conn is None:
                return
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE agent_notifications
                    SET status = %s,
                        sent_at = CASE WHEN %s = 'sent' THEN NOW() ELSE NULL END,
                        cancelled_at = CASE WHEN %s = 'cancelled' THEN NOW() ELSE NULL END,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (status, status, status, notif_id),
                )
            conn.commit()
    except (psycopg.Error, OSError):
        logger.warning("Failed to mark notification %s as %s", notif_id, status, exc_info=True)

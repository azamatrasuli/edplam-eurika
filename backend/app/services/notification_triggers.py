"""Notification triggers: scanners that detect when notifications should be sent.

Scheduled jobs:
  scan_payment_reminders() — every 6h — DMS payment schedule → payment_reminder
  scan_alerts()            — every 30min — nonresponsive clients + performance drops

Document reminder is triggered inline from support_onboarding.trigger_support_onboarding().
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from app.db.repository import ConversationRepository
from app.integrations.dms import get_dms_service
from app.services.notifications import schedule_notification

logger = logging.getLogger("services.notification_triggers")


# ---------------------------------------------------------------------------
# Payment reminders
# ---------------------------------------------------------------------------

# Days before due_date to send reminders
_REMINDER_DAYS = [3, 1, 0]


def scan_payment_reminders() -> None:
    """Scheduled job (every 6h): check DMS payment schedules for all known clients.

    For each upcoming payment within the reminder window, schedule a payment_reminder
    notification (deduplicated — won't send twice for the same due_date/days_before).
    """
    repo = ConversationRepository()
    dms = get_dms_service()

    actors = repo.get_active_actors_with_dms()
    if not actors:
        logger.debug("scan_payment_reminders: no actors with DMS profiles found")
        return

    logger.info("scan_payment_reminders: checking %d clients", len(actors))
    today = date.today()
    scheduled = 0

    for actor_row in actors:
        actor_id: str = actor_row["actor_id"]
        dms_contact_id: int = actor_row["dms_contact_id"]

        try:
            schedule_items = dms.get_payment_schedule(dms_contact_id)
        except Exception:
            logger.warning("Failed to get payment schedule for contact_id=%d", dms_contact_id, exc_info=True)
            continue

        for item in schedule_items:
            if not item.due_date:
                continue
            try:
                due = date.fromisoformat(item.due_date)
            except ValueError:
                logger.warning("Invalid due_date format: %s", item.due_date)
                continue

            for days_before in _REMINDER_DAYS:
                target_day = due - timedelta(days=days_before)
                if target_day != today:
                    continue

                # Compute amount in rubles (DMS stores kopecks)
                amount_rub = item.amount_kopecks // 100 if item.amount_kopecks else 0

                # Build payment URL: use existing one or generate stub
                payment_url = item.payment_url or _get_payment_url(dms, item)

                dedup_key = f"payment_reminder:{actor_id}:{item.due_date}:d{days_before}"
                notif_id = schedule_notification(
                    actor_id=actor_id,
                    notification_type="payment_reminder",
                    scheduled_at=_today_noon_utc(),
                    template_data={
                        "name": "",          # will be enriched from profile at send-time if needed
                        "product": item.product_name or "обучение",
                        "grade": "",
                        "amount": str(amount_rub),
                        "payment_url": payment_url or "",
                        "days_before": days_before,
                        "due_date": item.due_date,
                    },
                    dedup_key=dedup_key,
                )
                if notif_id:
                    scheduled += 1
                    logger.info(
                        "Payment reminder scheduled: actor=%s due=%s days_before=%d",
                        actor_id, item.due_date, days_before,
                    )

    logger.info("scan_payment_reminders: scheduled %d new reminders", scheduled)


def _get_payment_url(dms, item) -> str | None:
    """Try to get payment URL from existing order UUID."""
    if item.order_uuid:
        try:
            return dms.get_payment_link(item.order_uuid)
        except Exception:
            pass
    return None


def _today_noon_utc() -> datetime:
    """Return today's noon UTC for scheduling same-day notifications."""
    now = datetime.now(timezone.utc)
    # If already past noon, send immediately (within 2-min processor window)
    if now.hour >= 12:
        return now
    return now.replace(hour=12, minute=0, second=0, microsecond=0)


# ---------------------------------------------------------------------------
# Manager alerts
# ---------------------------------------------------------------------------

def scan_alerts() -> None:
    """Scheduled job (every 30min): scan for nonresponsive clients and performance drops.

    Non-responsive: handled primarily by auto_escalation.py (escalates conversation).
    Here we supplement: schedule alert_nonresponsive notification for metrics tracking.

    Performance drop: STUB — awaiting DMS grades API.
    """
    _scan_performance_drops()


def _scan_performance_drops() -> None:
    """STUB: scan for students with attendance/grades below threshold.

    Will be activated when DMS team provides grades/attendance API.
    Currently logs a debug message and returns.
    """
    dms = get_dms_service()
    repo = ConversationRepository()

    actors = repo.get_active_actors_with_dms()
    drop_count = 0

    for actor_row in actors:
        dms_contact_id: int = actor_row["dms_contact_id"]
        actor_id: str = actor_row["actor_id"]

        try:
            dms_svc = get_dms_service()
            students = dms_svc.get_students_by_contact(dms_contact_id)
        except Exception:
            continue

        for student in students:
            if not student.moodle_id:
                continue
            grades = dms.get_student_grades(student.moodle_id, days=14)
            if grades is None:
                # API not available yet — skip
                continue

            attendance = grades.get("attendance_pct", 100)
            if attendance >= 50:
                continue

            dedup_key = f"alert_performance_drop:{actor_id}:{student.student_id}:{date.today().isoformat()}"
            schedule_notification(
                actor_id=actor_id,
                notification_type="alert_performance_drop",
                scheduled_at=datetime.now(timezone.utc),
                template_data={
                    "student_name": student.fio,
                    "grade": str(student.grade or ""),
                    "product": student.product_name or "—",
                    "parent_name": "",
                    "attendance": str(int(attendance)),
                },
                dedup_key=dedup_key,
            )
            drop_count += 1
            logger.info("Performance drop alert scheduled: actor=%s student=%s attendance=%s%%",
                        actor_id, student.fio, attendance)

    if drop_count:
        logger.info("scan_alerts: scheduled %d performance drop alerts", drop_count)
    else:
        logger.debug("scan_alerts: no performance drop alerts (API may be unavailable)")

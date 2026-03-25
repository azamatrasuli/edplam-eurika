"""APScheduler setup: payment polling + follow-up processing."""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger("services.scheduler")

scheduler = BackgroundScheduler()


def start_scheduler() -> None:
    """Start background jobs for payment checking, follow-ups, memory, and auto-escalation."""
    from app.services.payment import check_pending_payments
    from app.services.followup import process_pending_followups
    from app.services.summarizer import summarize_idle_conversations
    from app.services.auto_escalation import process_idle_escalations
    # Sprint 4: notifications
    from app.services.notifications import process_pending_notifications
    from app.services.notification_triggers import scan_payment_reminders, scan_alerts

    scheduler.add_job(
        check_pending_payments,
        "interval",
        seconds=60,
        id="check_payments",
        replace_existing=True,
    )
    scheduler.add_job(
        process_pending_followups,
        "interval",
        minutes=5,
        id="process_followups",
        replace_existing=True,
    )
    scheduler.add_job(
        summarize_idle_conversations,
        "interval",
        minutes=3,
        id="summarize_conversations",
        replace_existing=True,
    )
    scheduler.add_job(
        process_idle_escalations,
        "interval",
        minutes=30,
        id="auto_escalate_idle",
        replace_existing=True,
    )
    # Sprint 4: process outbound notifications (client + manager alerts)
    scheduler.add_job(
        process_pending_notifications,
        "interval",
        minutes=2,
        id="process_notifications",
        replace_existing=True,
    )
    # Sprint 4: scan DMS for upcoming payment deadlines
    scheduler.add_job(
        scan_payment_reminders,
        "interval",
        hours=6,
        id="scan_payment_reminders",
        replace_existing=True,
    )
    # Sprint 4: scan for performance drops (stub until DMS API available)
    scheduler.add_job(
        scan_alerts,
        "interval",
        minutes=30,
        id="scan_alerts",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(
        "Scheduler started: check_payments (60s), process_followups (5min), "
        "summarize_conversations (3min), auto_escalate_idle (30min), "
        "process_notifications (2min), scan_payment_reminders (6h), scan_alerts (30min)"
    )


def stop_scheduler() -> None:
    """Gracefully shut down the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")

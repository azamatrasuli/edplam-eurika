"""NPS: save client ratings after support conversation closure."""

from __future__ import annotations

import logging

from app.db.events import EventTracker
from app.db.repository import ConversationRepository

logger = logging.getLogger("services.nps")


def save_nps(
    conversation_id: str,
    actor_id: str,
    rating: int,
    comment: str | None = None,
    agent_role: str = "support",
) -> str:
    """Save NPS rating for a conversation. Returns result message for LLM."""
    if not (1 <= rating <= 5):
        return f"Ошибка: оценка {rating} вне диапазона 1–5."

    repo = ConversationRepository()
    tracker = EventTracker()

    try:
        saved = repo.save_nps(
            conversation_id=conversation_id,
            actor_id=actor_id,
            rating=rating,
            comment=comment,
            agent_role=agent_role,
        )
        if not saved:
            return "Оценка уже сохранена для этого диалога."

        tracker.track_nps(
            conversation_id=conversation_id,
            actor_id=actor_id,
            rating=rating,
            comment=comment,
        )
        logger.info("NPS saved: conv=%s actor=%s rating=%d", conversation_id, actor_id, rating)
        return f"Оценка {rating}/5 сохранена. Спасибо!"

    except Exception:
        logger.exception("Failed to save NPS for conv=%s", conversation_id)
        return "Не удалось сохранить оценку."

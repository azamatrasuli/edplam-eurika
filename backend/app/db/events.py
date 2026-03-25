"""Fire-and-forget event tracking for dashboard analytics."""

from __future__ import annotations

import logging
from typing import Any

import psycopg
from psycopg.types.json import Json

from app.db.pool import get_connection, has_pool

logger = logging.getLogger("db.events")


class EventTracker:
    """Writes structured events to agent_events. Never raises — always fire-and-forget."""

    def _has_db(self) -> bool:
        return has_pool()

    def track(
        self,
        event_type: str,
        *,
        conversation_id: str | None = None,
        actor_id: str = "",
        channel: str | None = None,
        agent_role: str = "sales",
        data: dict[str, Any] | None = None,
    ) -> None:
        if not self._has_db():
            return
        try:
            with get_connection() as conn:
                if conn is None:
                    return
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO agent_events
                          (conversation_id, actor_id, channel, agent_role, event_type, event_data)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            conversation_id,
                            actor_id,
                            channel,
                            agent_role,
                            event_type,
                            Json(data or {}),
                        ),
                    )
                conn.commit()
        except (psycopg.Error, OSError):
            logger.warning("Failed to track event %s", event_type, exc_info=True)

    def track_tool_call(
        self,
        conversation_id: str | None,
        actor_id: str,
        tool_name: str,
        args: dict[str, Any],
        result_summary: str,
        success: bool,
        *,
        agent_role: str = "sales",
    ) -> None:
        self.track(
            "tool_called",
            conversation_id=conversation_id,
            actor_id=actor_id,
            agent_role=agent_role,
            data={
                "tool_name": tool_name,
                "args_summary": {k: str(v)[:100] for k, v in args.items()},
                "result_summary": result_summary[:200],
                "success": success,
            },
        )

    def track_rag_miss(
        self,
        conversation_id: str | None,
        actor_id: str,
        query: str,
        namespace: str,
    ) -> None:
        self.track(
            "rag_miss",
            conversation_id=conversation_id,
            actor_id=actor_id,
            agent_role=namespace,
            data={"query": query, "namespace": namespace},
        )

    def track_escalation(
        self,
        conversation_id: str | None,
        actor_id: str,
        reason: str,
        *,
        channel: str | None = None,
        agent_role: str = "sales",
    ) -> None:
        self.track(
            "escalation",
            conversation_id=conversation_id,
            actor_id=actor_id,
            channel=channel,
            agent_role=agent_role,
            data={"reason": reason},
        )

    def track_payment(
        self,
        event_type: str,
        conversation_id: str | None,
        actor_id: str,
        order_uuid: str,
        amount_kopecks: int,
        product_name: str | None = None,
    ) -> None:
        self.track(
            event_type,
            conversation_id=conversation_id,
            actor_id=actor_id,
            data={
                "order_uuid": order_uuid,
                "amount_kopecks": amount_kopecks,
                "product_name": product_name,
            },
        )

    def track_followup(
        self,
        conversation_id: str | None,
        actor_id: str,
        step: int,
        payment_order_id: str | None = None,
    ) -> None:
        self.track(
            "followup_sent",
            conversation_id=conversation_id,
            actor_id=actor_id,
            data={"step": step, "payment_order_id": payment_order_id},
        )

    def track_notification_sent(
        self,
        notification_type: str,
        actor_id: str,
        notification_id: str,
        conversation_id: str | None = None,
    ) -> None:
        """Track outbound client notification (Sprint 4)."""
        self.track(
            "notification_sent",
            conversation_id=conversation_id,
            actor_id=actor_id,
            agent_role="support",
            data={"notification_type": notification_type, "notification_id": notification_id},
        )

    def track_nps(
        self,
        conversation_id: str | None,
        actor_id: str,
        rating: int,
        comment: str | None = None,
    ) -> None:
        """Track NPS rating submission (Sprint 4)."""
        self.track(
            "nps_collected",
            conversation_id=conversation_id,
            actor_id=actor_id,
            agent_role="support",
            data={"rating": rating, "has_comment": bool(comment)},
        )

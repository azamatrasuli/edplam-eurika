from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.types.json import Json

from app.db.pool import get_connection, has_pool
from app.models.chat import ActorContext, ChatMessage

logger = logging.getLogger(__name__)


@dataclass
class StoredConversation:
    id: str
    actor_id: str
    channel: str


class ConversationRepository:
    def __init__(self) -> None:
        self._memory_lock = Lock()
        self._memory_conversations: dict[str, dict[str, Any]] = {}
        self._memory_messages: dict[str, list[dict[str, Any]]] = {}

    def _has_db(self) -> bool:
        return has_pool()

    def start_or_resume_conversation(self, actor: ActorContext, conversation_id: str | None = None) -> StoredConversation:
        if self._has_db():
            try:
                return self._start_or_resume_db(actor, conversation_id)
            except (psycopg.Error, OSError):
                pass
        return self._start_or_resume_memory(actor, conversation_id)

    def save_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        model: str | None = None,
        token_usage: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        metadata = metadata or {}
        if self._has_db():
            try:
                with get_connection() as conn:
                    if conn is None:
                        raise OSError("No DB connection")
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            insert into chat_messages(conversation_id, role, content, model, token_usage, metadata)
                            values (%s, %s, %s, %s, %s, %s)
                            """,
                            (conversation_id, role, content, model, token_usage, Json(metadata)),
                        )
                        cur.execute(
                            """
                            update conversations set updated_at = now() where id = %s
                            """,
                            (conversation_id,),
                        )
                    conn.commit()
                return
            except (psycopg.Error, OSError):
                logger.warning("Failed to save message to DB, falling back to memory", exc_info=True)

        with self._memory_lock:
            self._memory_messages.setdefault(conversation_id, []).append(
                {
                    "role": role,
                    "content": content,
                    "created_at": datetime.now(tz=timezone.utc),
                }
            )

    def get_messages(self, conversation_id: str, limit: int = 100) -> list[ChatMessage]:
        if self._has_db():
            try:
                with get_connection() as conn:
                    if conn is None:
                        raise OSError("No DB connection")
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            select role, content, created_at
                            from chat_messages
                            where conversation_id = %s
                            order by created_at asc
                            limit %s
                            """,
                            (conversation_id, limit),
                        )
                        rows = cur.fetchall()
                return [ChatMessage(**row) for row in rows]
            except (psycopg.Error, OSError):
                logger.warning("Failed to get messages from DB", exc_info=True)

        with self._memory_lock:
            rows = self._memory_messages.get(conversation_id, [])[-limit:]
            return [ChatMessage(**row) for row in rows]

    def _start_or_resume_db(self, actor: ActorContext, conversation_id: str | None) -> StoredConversation:
        with get_connection() as conn:
            if conn is None:
                raise OSError("No DB connection")
            with conn.cursor() as cur:
                if conversation_id:
                    cur.execute(
                        """
                        select id, actor_id, channel
                        from conversations
                        where id = %s and actor_id = %s
                        """,
                        (conversation_id, actor.actor_id),
                    )
                    row = cur.fetchone()
                    if row:
                        return StoredConversation(
                            id=str(row["id"]),
                            actor_id=row["actor_id"],
                            channel=row["channel"],
                        )

                cur.execute(
                    """
                    insert into conversations(actor_id, channel, metadata)
                    values (%s, %s, %s)
                    returning id, actor_id, channel
                    """,
                    (actor.actor_id, actor.channel.value, Json(actor.metadata)),
                )
                created = cur.fetchone()
            conn.commit()
        return StoredConversation(
            id=str(created["id"]),
            actor_id=created["actor_id"],
            channel=created["channel"],
        )

    # ---- CRM mapping methods -----------------------------------------------

    def save_contact_mapping(self, actor_id: str, amocrm_contact_id: int, contact_name: str | None = None) -> None:
        if not self._has_db():
            return
        try:
            with get_connection() as conn:
                if conn is None:
                    raise OSError("No DB connection")
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO agent_contact_mapping (actor_id, amocrm_contact_id, contact_name)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (actor_id) DO UPDATE
                        SET amocrm_contact_id = EXCLUDED.amocrm_contact_id,
                            contact_name      = EXCLUDED.contact_name
                        """,
                        (actor_id, amocrm_contact_id, contact_name),
                    )
                conn.commit()
        except (psycopg.Error, OSError):
            pass

    def get_contact_mapping(self, actor_id: str) -> int | None:
        if not self._has_db():
            return None
        try:
            with get_connection() as conn:
                if conn is None:
                    raise OSError("No DB connection")
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT amocrm_contact_id FROM agent_contact_mapping WHERE actor_id = %s",
                        (actor_id,),
                    )
                    row = cur.fetchone()
                    return row["amocrm_contact_id"] if row else None
        except (psycopg.Error, OSError):
            return None

    def save_deal_mapping(
        self,
        conversation_id: str,
        amocrm_lead_id: int,
        amocrm_contact_id: int | None = None,
        pipeline_id: int | None = None,
        status_id: int | None = None,
    ) -> None:
        if not self._has_db():
            return
        try:
            with get_connection() as conn:
                if conn is None:
                    raise OSError("No DB connection")
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO agent_deal_mapping
                          (conversation_id, amocrm_lead_id, amocrm_contact_id, pipeline_id, status_id)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (conversation_id) DO UPDATE
                        SET amocrm_lead_id    = EXCLUDED.amocrm_lead_id,
                            amocrm_contact_id = EXCLUDED.amocrm_contact_id,
                            pipeline_id       = EXCLUDED.pipeline_id,
                            status_id         = EXCLUDED.status_id
                        """,
                        (conversation_id, amocrm_lead_id, amocrm_contact_id, pipeline_id, status_id),
                    )
                conn.commit()
        except (psycopg.Error, OSError):
            pass

    def get_deal_mapping(self, conversation_id: str) -> dict | None:
        if not self._has_db():
            return None
        try:
            with get_connection() as conn:
                if conn is None:
                    raise OSError("No DB connection")
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT amocrm_lead_id, amocrm_contact_id, pipeline_id, status_id "
                        "FROM agent_deal_mapping WHERE conversation_id = %s",
                        (conversation_id,),
                    )
                    return cur.fetchone()
        except (psycopg.Error, OSError):
            return None

    def update_conversation_status(self, conversation_id: str, status: str) -> None:
        if not self._has_db():
            return
        try:
            with get_connection() as conn:
                if conn is None:
                    raise OSError("No DB connection")
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE conversations SET status = %s WHERE id = %s",
                        (status, conversation_id),
                    )
                conn.commit()
        except (psycopg.Error, OSError):
            pass

    # ---- in-memory fallback -----------------------------------------------

    def _start_or_resume_memory(self, actor: ActorContext, conversation_id: str | None) -> StoredConversation:
        with self._memory_lock:
            if conversation_id and conversation_id in self._memory_conversations:
                c = self._memory_conversations[conversation_id]
                if c["actor_id"] == actor.actor_id:
                    return StoredConversation(id=conversation_id, actor_id=c["actor_id"], channel=c["channel"])

            new_id = str(uuid4())
            self._memory_conversations[new_id] = {
                "actor_id": actor.actor_id,
                "channel": actor.channel.value,
                "created_at": datetime.now(tz=timezone.utc),
            }
            self._memory_messages.setdefault(new_id, [])
            return StoredConversation(id=new_id, actor_id=actor.actor_id, channel=actor.channel.value)

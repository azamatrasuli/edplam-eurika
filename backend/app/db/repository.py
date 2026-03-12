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
    agent_role: str = "sales"


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
                logger.warning("Failed to start/resume conversation in DB, falling back to memory", exc_info=True)
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
        agent_role = actor.agent_role.value if hasattr(actor.agent_role, "value") else str(actor.agent_role)
        with get_connection() as conn:
            if conn is None:
                raise OSError("No DB connection")
            with conn.cursor() as cur:
                if conversation_id:
                    cur.execute(
                        """
                        select id, actor_id, channel, agent_role
                        from conversations
                        where id = %s and actor_id = %s and agent_role = %s
                        """,
                        (conversation_id, actor.actor_id, agent_role),
                    )
                    row = cur.fetchone()
                    if row:
                        return StoredConversation(
                            id=str(row["id"]),
                            actor_id=row["actor_id"],
                            channel=row["channel"],
                            agent_role=row.get("agent_role", "sales") or "sales",
                        )

                cur.execute(
                    """
                    insert into conversations(actor_id, channel, metadata, agent_role)
                    values (%s, %s, %s, %s)
                    returning id, actor_id, channel, agent_role
                    """,
                    (actor.actor_id, actor.channel.value, Json(actor.metadata), agent_role),
                )
                created = cur.fetchone()
            conn.commit()
        return StoredConversation(
            id=str(created["id"]),
            actor_id=created["actor_id"],
            channel=created["channel"],
            agent_role=created.get("agent_role", "sales") or "sales",
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
            logger.warning("Failed to save contact mapping for actor=%s", actor_id, exc_info=True)

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
            logger.warning("Failed to save deal mapping for conv=%s", conversation_id, exc_info=True)

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

    def get_conversation_owner(self, conversation_id: str) -> str | None:
        """Return actor_id that owns this conversation, or None."""
        if not self._has_db():
            with self._memory_lock:
                c = self._memory_conversations.get(conversation_id)
                return c["actor_id"] if c else None
        try:
            with get_connection() as conn:
                if conn is None:
                    return None
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT actor_id FROM conversations WHERE id = %s",
                        (conversation_id,),
                    )
                    row = cur.fetchone()
                    return row["actor_id"] if row else None
        except (psycopg.Error, OSError):
            logger.warning("Failed to get conversation owner", exc_info=True)
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
            logger.warning("Failed to update conversation status for conv=%s", conversation_id, exc_info=True)

    # ---- Chat API mapping methods -------------------------------------------

    def get_or_create_chat_mapping(self, actor_id: str) -> str:
        """Return stable amoCRM conversation_id for this actor (format: agent_chat_{safe_id})."""
        safe_id = actor_id.replace(":", "_")
        conversation_id = f"agent_chat_{safe_id}"
        if not self._has_db():
            return conversation_id
        try:
            with get_connection() as conn:
                if conn is None:
                    return conversation_id
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO agent_chat_mapping (actor_id, amocrm_conversation_id)
                        VALUES (%s, %s)
                        ON CONFLICT (actor_id) DO UPDATE SET updated_at = NOW()
                        RETURNING amocrm_conversation_id
                        """,
                        (actor_id, conversation_id),
                    )
                    row = cur.fetchone()
                conn.commit()
                return row["amocrm_conversation_id"] if row else conversation_id
        except (psycopg.Error, OSError):
            return conversation_id

    def get_chat_mapping_details(self, actor_id: str) -> dict | None:
        """Return full chat mapping row for actor, or None."""
        if not self._has_db():
            return None
        try:
            with get_connection() as conn:
                if conn is None:
                    return None
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT actor_id, amocrm_conversation_id, amocrm_chat_id FROM agent_chat_mapping WHERE actor_id = %s",
                        (actor_id,),
                    )
                    return cur.fetchone()
        except (psycopg.Error, OSError):
            return None

    def update_chat_mapping_amocrm_id(self, actor_id: str, amocrm_chat_id: str) -> None:
        if not self._has_db():
            return
        try:
            with get_connection() as conn:
                if conn is None:
                    return
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE agent_chat_mapping SET amocrm_chat_id = %s WHERE actor_id = %s",
                        (amocrm_chat_id, actor_id),
                    )
                conn.commit()
        except (psycopg.Error, OSError):
            logger.warning("Failed to update chat mapping for actor=%s", actor_id, exc_info=True)

    def save_manager_message(
        self, actor_id: str, content: str,
        conversation_id: str | None = None,
        amocrm_msgid: str | None = None,
        sender_name: str | None = None,
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
                        INSERT INTO agent_manager_messages
                          (actor_id, conversation_id, amocrm_msgid, sender_name, content)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (actor_id, conversation_id, amocrm_msgid, sender_name, content),
                    )
                conn.commit()
        except (psycopg.Error, OSError):
            logger.warning("Failed to save manager message", exc_info=True)

    def find_actor_by_chat_conversation_id(self, amocrm_conversation_id: str) -> str | None:
        if not self._has_db():
            return None
        try:
            with get_connection() as conn:
                if conn is None:
                    return None
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT actor_id FROM agent_chat_mapping WHERE amocrm_conversation_id = %s",
                        (amocrm_conversation_id,),
                    )
                    row = cur.fetchone()
                    return row["actor_id"] if row else None
        except (psycopg.Error, OSError):
            return None

    # ---- User Profile methods (onboarding) -----------------------------------

    def save_user_profile(
        self,
        actor_id: str,
        client_type: str,
        user_role: str,
        phone: str,
        phone_raw: str | None = None,
        fio: str | None = None,
        grade: int | None = None,
        children: list | None = None,
        dms_verified: bool = False,
        dms_contact_id: int | None = None,
        dms_data: dict | None = None,
        verification_status: str = "pending",
    ) -> str | None:
        """Upsert user profile. Returns profile id."""
        children = children or []
        if self._has_db():
            try:
                with get_connection() as conn:
                    if conn is None:
                        raise OSError("No DB connection")
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            INSERT INTO agent_user_profiles
                              (actor_id, client_type, user_role, phone, phone_raw,
                               fio, grade, children, dms_verified, dms_contact_id,
                               dms_data, verification_status)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                            ON CONFLICT (actor_id) DO UPDATE SET
                              client_type = EXCLUDED.client_type,
                              user_role = EXCLUDED.user_role,
                              phone = EXCLUDED.phone,
                              phone_raw = EXCLUDED.phone_raw,
                              fio = EXCLUDED.fio,
                              grade = EXCLUDED.grade,
                              children = EXCLUDED.children,
                              dms_verified = EXCLUDED.dms_verified,
                              dms_contact_id = EXCLUDED.dms_contact_id,
                              dms_data = EXCLUDED.dms_data,
                              verification_status = EXCLUDED.verification_status
                            RETURNING id
                            """,
                            (
                                actor_id, client_type, user_role, phone, phone_raw,
                                fio, grade, Json(children), dms_verified, dms_contact_id,
                                Json(dms_data) if dms_data else None, verification_status,
                            ),
                        )
                        row = cur.fetchone()
                    conn.commit()
                    return str(row["id"]) if row else None
            except (psycopg.Error, OSError):
                logger.warning("Failed to save user profile for actor=%s", actor_id, exc_info=True)
        return None

    def get_user_profile(self, actor_id: str) -> dict | None:
        """Get user profile by actor_id."""
        if not self._has_db():
            return None
        try:
            with get_connection() as conn:
                if conn is None:
                    return None
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, actor_id, client_type, user_role, phone, fio, grade,
                               children, dms_verified, dms_contact_id, dms_data,
                               verification_status
                        FROM agent_user_profiles
                        WHERE actor_id = %s
                        """,
                        (actor_id,),
                    )
                    row = cur.fetchone()
                    if row:
                        row["id"] = str(row["id"])
                    return row
        except (psycopg.Error, OSError):
            logger.warning("Failed to get user profile for actor=%s", actor_id, exc_info=True)
            return None

    # ---- in-memory fallback -----------------------------------------------

    def _start_or_resume_memory(self, actor: ActorContext, conversation_id: str | None) -> StoredConversation:
        agent_role = actor.agent_role.value if hasattr(actor.agent_role, "value") else str(actor.agent_role)
        with self._memory_lock:
            if conversation_id and conversation_id in self._memory_conversations:
                c = self._memory_conversations[conversation_id]
                if c["actor_id"] == actor.actor_id and c.get("agent_role") == agent_role:
                    return StoredConversation(
                        id=conversation_id,
                        actor_id=c["actor_id"],
                        channel=c["channel"],
                        agent_role=c.get("agent_role", "sales"),
                    )

            new_id = str(uuid4())
            self._memory_conversations[new_id] = {
                "actor_id": actor.actor_id,
                "channel": actor.channel.value,
                "agent_role": agent_role,
                "created_at": datetime.now(tz=timezone.utc),
            }
            self._memory_messages.setdefault(new_id, [])
            return StoredConversation(id=new_id, actor_id=actor.actor_id, channel=actor.channel.value, agent_role=agent_role)

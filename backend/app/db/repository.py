from __future__ import annotations

import json
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
    status: str = "active"
    title: str | None = None
    message_count: int = 0
    last_user_message: str | None = None
    escalated_at: datetime | None = None
    escalated_reason: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    archived_at: datetime | None = None


class ConversationRepository:
    def __init__(self) -> None:
        self._memory_lock = Lock()
        self._memory_conversations: dict[str, dict[str, Any]] = {}
        self._memory_messages: dict[str, list[dict[str, Any]]] = {}

    def _has_db(self) -> bool:
        return has_pool()

    def start_or_resume_conversation(
        self, actor: ActorContext, conversation_id: str | None = None, *, force_new: bool = False,
    ) -> StoredConversation:
        if self._has_db():
            try:
                return self._start_or_resume_db(actor, conversation_id, force_new=force_new)
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
                            select role, content, created_at, metadata
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

    def _start_or_resume_db(
        self, actor: ActorContext, conversation_id: str | None, *, force_new: bool = False,
    ) -> StoredConversation:
        agent_role = actor.agent_role.value if hasattr(actor.agent_role, "value") else str(actor.agent_role)
        with get_connection() as conn:
            if conn is None:
                raise OSError("No DB connection")
            with conn.cursor() as cur:
                # Resume existing conversation (unless force_new)
                if conversation_id and not force_new:
                    cur.execute(
                        """
                        select id, actor_id, channel, agent_role, status,
                               title, message_count, last_user_message,
                               escalated_at, escalated_reason,
                               created_at, updated_at, archived_at
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
                            status=row.get("status", "active") or "active",
                            title=row.get("title"),
                            message_count=row.get("message_count", 0) or 0,
                            last_user_message=row.get("last_user_message"),
                            escalated_at=row.get("escalated_at"),
                            escalated_reason=row.get("escalated_reason"),
                            created_at=row.get("created_at"),
                            updated_at=row.get("updated_at"),
                            archived_at=row.get("archived_at"),
                        )

                # Guard: reuse existing empty conversation instead of creating new
                # Only reuse conversations that are truly empty: no user messages AND no title
                if force_new:
                    cur.execute(
                        """
                        SELECT id, actor_id, channel, agent_role, status,
                               title, message_count, last_user_message,
                               escalated_at, escalated_reason,
                               created_at, updated_at, archived_at
                        FROM conversations
                        WHERE actor_id = %s AND agent_role = %s
                          AND archived_at IS NULL
                          AND (message_count IS NULL OR message_count = 0)
                          AND title IS NULL
                        ORDER BY created_at DESC LIMIT 1
                        """,
                        (actor.actor_id, agent_role),
                    )
                    empty_row = cur.fetchone()
                    if empty_row:
                        # Clear old greeting messages so a fresh greeting is generated
                        cur.execute(
                            "DELETE FROM chat_messages WHERE conversation_id = %s",
                            (empty_row["id"],),
                        )
                        # Reset metadata for clean reuse
                        cur.execute(
                            """
                            UPDATE conversations
                            SET message_count = 0, title = NULL, last_user_message = NULL,
                                status = 'active', escalated_at = NULL, escalated_reason = NULL,
                                updated_at = now()
                            WHERE id = %s
                            """,
                            (empty_row["id"],),
                        )
                        conn.commit()
                        return StoredConversation(
                            id=str(empty_row["id"]),
                            actor_id=empty_row["actor_id"],
                            channel=empty_row["channel"],
                            agent_role=empty_row.get("agent_role", "sales") or "sales",
                            status="active",
                            title=None,
                            message_count=0,
                            last_user_message=None,
                            escalated_at=None,
                            escalated_reason=None,
                            created_at=empty_row.get("created_at"),
                            updated_at=datetime.now(tz=timezone.utc),
                            archived_at=None,
                        )

                    # Hard limit: max 20 conversations per hour
                    cur.execute(
                        "SELECT COUNT(*) AS cnt FROM conversations WHERE actor_id = %s AND created_at > NOW() - INTERVAL '1 hour'",
                        (actor.actor_id,),
                    )
                    hourly = cur.fetchone()
                    if hourly and (hourly.get("cnt", 0) or 0) > 20:
                        raise ValueError("conversation_limit_exceeded")

                # Create new conversation
                cur.execute(
                    """
                    insert into conversations(actor_id, channel, metadata, agent_role)
                    values (%s, %s, %s, %s)
                    returning id, actor_id, channel, agent_role, created_at, updated_at
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
            created_at=created.get("created_at"),
            updated_at=created.get("updated_at"),
        )

    # ---- Chat History methods ------------------------------------------------

    def list_conversations(
        self,
        actor_id: str,
        agent_role: str | None = None,
        offset: int = 0,
        limit: int = 20,
        include_archived: bool = False,
    ) -> tuple[list[StoredConversation], int]:
        """List conversations for an actor. Returns (conversations, total_count)."""
        if not self._has_db():
            return [], 0
        try:
            with get_connection() as conn:
                if conn is None:
                    return [], 0
                with conn.cursor() as cur:
                    where = "WHERE actor_id = %s"
                    params: list[Any] = [actor_id]

                    if agent_role:
                        where += " AND agent_role = %s"
                        params.append(agent_role)

                    if not include_archived:
                        where += " AND archived_at IS NULL"

                    # Total count
                    cur.execute(f"SELECT COUNT(*) AS cnt FROM conversations {where}", params)
                    total = cur.fetchone()["cnt"]

                    # Paginated results
                    cur.execute(
                        f"""
                        SELECT id, actor_id, channel, agent_role, status,
                               title, message_count, last_user_message,
                               created_at, updated_at, archived_at
                        FROM conversations
                        {where}
                        ORDER BY updated_at DESC
                        LIMIT %s OFFSET %s
                        """,
                        [*params, limit, offset],
                    )
                    rows = cur.fetchall()

                convs = [
                    StoredConversation(
                        id=str(row["id"]),
                        actor_id=row["actor_id"],
                        channel=row["channel"],
                        agent_role=row.get("agent_role", "sales") or "sales",
                        status=row.get("status", "active") or "active",
                        title=row.get("title"),
                        message_count=row.get("message_count", 0) or 0,
                        last_user_message=row.get("last_user_message"),
                        created_at=row.get("created_at"),
                        updated_at=row.get("updated_at"),
                        archived_at=row.get("archived_at"),
                    )
                    for row in rows
                ]
                return convs, total
        except (psycopg.Error, OSError):
            logger.warning("Failed to list conversations for actor=%s", actor_id, exc_info=True)
            return [], 0

    def archive_conversation(self, conversation_id: str, actor_id: str) -> bool:
        """Soft-delete a conversation. Returns True if archived."""
        if not self._has_db():
            return False
        try:
            with get_connection() as conn:
                if conn is None:
                    return False
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE conversations
                        SET archived_at = NOW()
                        WHERE id = %s AND actor_id = %s AND archived_at IS NULL
                        """,
                        (conversation_id, actor_id),
                    )
                    affected = cur.rowcount
                conn.commit()
                return affected > 0
        except (psycopg.Error, OSError):
            logger.warning("Failed to archive conversation %s", conversation_id, exc_info=True)
            return False

    def unarchive_conversation(self, conversation_id: str, actor_id: str) -> bool:
        """Restore an archived conversation. Returns True if unarchived."""
        if not self._has_db():
            return False
        try:
            with get_connection() as conn:
                if conn is None:
                    return False
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE conversations
                        SET archived_at = NULL
                        WHERE id = %s AND actor_id = %s AND archived_at IS NOT NULL
                        """,
                        (conversation_id, actor_id),
                    )
                    affected = cur.rowcount
                conn.commit()
                return affected > 0
        except (psycopg.Error, OSError):
            logger.warning("Failed to unarchive conversation %s", conversation_id, exc_info=True)
            return False

    def delete_conversation(self, conversation_id: str, actor_id: str) -> bool:
        """Hard-delete a conversation and all its messages (CASCADE). Returns True if deleted."""
        if not self._has_db():
            return False
        try:
            with get_connection() as conn:
                if conn is None:
                    return False
                with conn.cursor() as cur:
                    cur.execute(
                        "DELETE FROM conversations WHERE id = %s AND actor_id = %s",
                        (conversation_id, actor_id),
                    )
                    affected = cur.rowcount
                conn.commit()
                return affected > 0
        except (psycopg.Error, OSError):
            logger.warning("Failed to delete conversation %s", conversation_id, exc_info=True)
            return False

    def update_conversation_title(self, conversation_id: str, title: str) -> None:
        """Set or update conversation title."""
        if not self._has_db():
            return
        try:
            with get_connection() as conn:
                if conn is None:
                    return
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE conversations SET title = %s WHERE id = %s",
                        (title, conversation_id),
                    )
                conn.commit()
        except (psycopg.Error, OSError):
            logger.warning("Failed to update title for conv=%s", conversation_id, exc_info=True)

    def search_conversations(self, actor_id: str, query: str, agent_role: str | None = None) -> list[StoredConversation]:
        """Search conversations by title and last_user_message using trigram similarity."""
        if not self._has_db():
            return []
        try:
            with get_connection() as conn:
                if conn is None:
                    return []
                with conn.cursor() as cur:
                    where = "WHERE actor_id = %s AND archived_at IS NULL"
                    params: list[Any] = [actor_id]

                    if agent_role:
                        where += " AND agent_role = %s"
                        params.append(agent_role)

                    escaped = query.replace("%", r"\%").replace("_", r"\_")
                    like_query = f"%{escaped}%"
                    where += " AND (title ILIKE %s OR last_user_message ILIKE %s)"
                    params.extend([like_query, like_query])

                    cur.execute(
                        f"""
                        SELECT id, actor_id, channel, agent_role, status,
                               title, message_count, last_user_message,
                               created_at, updated_at, archived_at
                        FROM conversations
                        {where}
                        ORDER BY updated_at DESC
                        LIMIT 20
                        """,
                        params,
                    )
                    rows = cur.fetchall()

                return [
                    StoredConversation(
                        id=str(row["id"]),
                        actor_id=row["actor_id"],
                        channel=row["channel"],
                        agent_role=row.get("agent_role", "sales") or "sales",
                        status=row.get("status", "active") or "active",
                        title=row.get("title"),
                        message_count=row.get("message_count", 0) or 0,
                        last_user_message=row.get("last_user_message"),
                        created_at=row.get("created_at"),
                        updated_at=row.get("updated_at"),
                        archived_at=row.get("archived_at"),
                    )
                    for row in rows
                ]
        except (psycopg.Error, OSError):
            logger.warning("Failed to search conversations for actor=%s", actor_id, exc_info=True)
            return []

    def update_message_stats(self, conversation_id: str, user_message: str) -> None:
        """Increment message_count and set last_user_message + auto-title on first message."""
        if not self._has_db():
            return
        try:
            with get_connection() as conn:
                if conn is None:
                    return
                with conn.cursor() as cur:
                    # Increment count and update last user message
                    cur.execute(
                        """
                        UPDATE conversations
                        SET message_count = COALESCE(message_count, 0) + 1,
                            last_user_message = %s
                        WHERE id = %s
                        RETURNING message_count, title
                        """,
                        (user_message[:500], conversation_id),
                    )
                    row = cur.fetchone()  # noqa: F841 — title is now set via LLM in api/chat.py

                conn.commit()
        except (psycopg.Error, OSError):
            logger.warning("Failed to update message stats for conv=%s", conversation_id, exc_info=True)

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

    def get_conversation_status(self, conversation_id: str) -> dict | None:
        """Return status + escalation fields for a conversation."""
        if not self._has_db():
            return None
        try:
            with get_connection() as conn:
                if conn is None:
                    return None
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT status, escalated_reason, escalated_at,
                               escalated_lead_id, resolved_at, resolved_by,
                               manager_is_active, last_manager_activity_at
                        FROM conversations WHERE id = %s
                        """,
                        (conversation_id,),
                    )
                    row = cur.fetchone()
                    return dict(row) if row else None
        except (psycopg.Error, OSError):
            logger.warning("Failed to get conversation status for conv=%s", conversation_id, exc_info=True)
            return None

    def update_escalation_metadata(
        self, conversation_id: str, reason: str, lead_id: int | None = None,
    ) -> None:
        """Set escalation columns on a conversation. Idempotent (COALESCE preserves first values)."""
        if not self._has_db():
            return
        try:
            with get_connection() as conn:
                if conn is None:
                    raise OSError("No DB connection")
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE conversations
                        SET status = 'escalated',
                            escalated_at = COALESCE(escalated_at, NOW()),
                            escalated_reason = %s,
                            escalated_lead_id = COALESCE(escalated_lead_id, %s)
                        WHERE id = %s
                        """,
                        (reason, lead_id, conversation_id),
                    )
                conn.commit()
        except (psycopg.Error, OSError):
            logger.warning("Failed to update escalation metadata for conv=%s", conversation_id, exc_info=True)

    def resolve_escalation(self, conversation_id: str, resolved_by: str = "manager") -> bool:
        """De-escalate a conversation. Returns True if actually resolved."""
        if not self._has_db():
            return False
        try:
            with get_connection() as conn:
                if conn is None:
                    return False
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE conversations
                        SET status = 'active', resolved_at = NOW(), resolved_by = %s
                        WHERE id = %s AND status = 'escalated'
                        RETURNING id
                        """,
                        (resolved_by, conversation_id),
                    )
                    row = cur.fetchone()
                conn.commit()
                return row is not None
        except (psycopg.Error, OSError):
            logger.warning("Failed to resolve escalation for conv=%s", conversation_id, exc_info=True)
            return False

    def find_escalated_conversation(self, actor_id: str) -> str | None:
        """Find most recent open escalated conversation for an actor."""
        if not self._has_db():
            return None
        try:
            with get_connection() as conn:
                if conn is None:
                    return None
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id FROM conversations
                        WHERE actor_id = %s AND status = 'escalated' AND resolved_at IS NULL
                        ORDER BY updated_at DESC LIMIT 1
                        """,
                        (actor_id,),
                    )
                    row = cur.fetchone()
                    return str(row["id"]) if row else None
        except (psycopg.Error, OSError):
            return None

    def find_active_conversation(self, actor_id: str) -> str | None:
        """Find most recent active (non-ended) conversation for an actor."""
        if not self._has_db():
            return None
        try:
            with get_connection() as conn:
                if conn is None:
                    return None
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id FROM conversations
                        WHERE actor_id = %s AND status IN ('active', 'escalated')
                        ORDER BY updated_at DESC LIMIT 1
                        """,
                        (actor_id,),
                    )
                    row = cur.fetchone()
                    return str(row["id"]) if row else None
        except (psycopg.Error, OSError):
            return None

    def find_latest_conversation(self, actor_id: str) -> str | None:
        """Find most recent conversation for actor, regardless of status."""
        if not self._has_db():
            return None
        try:
            with get_connection() as conn:
                if conn is None:
                    return None
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id FROM conversations
                        WHERE actor_id = %s
                        ORDER BY updated_at DESC LIMIT 1
                        """,
                        (actor_id,),
                    )
                    row = cur.fetchone()
                    return str(row["id"]) if row else None
        except (psycopg.Error, OSError):
            return None

    def get_undelivered_manager_messages(self, agent_conversation_id: str) -> list[dict]:
        """Get undelivered manager messages for a conversation."""
        if not self._has_db():
            return []
        try:
            with get_connection() as conn:
                if conn is None:
                    return []
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, content, sender_name, created_at
                        FROM agent_manager_messages
                        WHERE agent_conversation_id = %s AND delivered = FALSE
                        ORDER BY created_at ASC
                        """,
                        (agent_conversation_id,),
                    )
                    return [dict(r) for r in cur.fetchall()]
        except (psycopg.Error, OSError):
            logger.warning("Failed to get undelivered manager messages", exc_info=True)
            return []

    def get_undelivered_manager_messages_by_actor(self, actor_id: str) -> list[dict]:
        """Get undelivered manager messages by actor_id (fallback when agent_conversation_id is NULL)."""
        if not self._has_db():
            return []
        try:
            with get_connection() as conn:
                if conn is None:
                    return []
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, content, sender_name, created_at
                        FROM agent_manager_messages
                        WHERE actor_id = %s AND delivered = FALSE
                        ORDER BY created_at ASC
                        """,
                        (actor_id,),
                    )
                    return [dict(r) for r in cur.fetchall()]
        except (psycopg.Error, OSError):
            logger.warning("Failed to get undelivered manager messages by actor", exc_info=True)
            return []

    def mark_manager_messages_delivered(self, message_ids: list[str]) -> None:
        """Mark manager messages as delivered."""
        if not self._has_db() or not message_ids:
            return
        try:
            with get_connection() as conn:
                if conn is None:
                    return
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE agent_manager_messages SET delivered = TRUE WHERE id = ANY(%s)",
                        ([str(mid) for mid in message_ids],),
                    )
                conn.commit()
        except (psycopg.Error, OSError):
            logger.warning("Failed to mark manager messages delivered", exc_info=True)

    def get_idle_support_conversations(self, hours: int = 48) -> list[dict]:
        """Find active support conversations with no activity for N hours."""
        if not self._has_db():
            return []
        try:
            with get_connection() as conn:
                if conn is None:
                    return []
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, actor_id, channel, title, updated_at
                        FROM conversations
                        WHERE agent_role = 'support'
                          AND status = 'active'
                          AND updated_at < NOW() - make_interval(hours => %s)
                          AND message_count >= 2
                        ORDER BY updated_at ASC
                        LIMIT 50
                        """,
                        (hours,),
                    )
                    return [dict(r) for r in cur.fetchall()]
        except (psycopg.Error, OSError):
            logger.warning("Failed to get idle support conversations", exc_info=True)
            return []

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
                        "SELECT actor_id, amocrm_conversation_id, amocrm_chat_id, amocrm_contact_id, amocrm_lead_id FROM agent_chat_mapping WHERE actor_id = %s",
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

    def update_chat_mapping_lead_id(self, actor_id: str, lead_id: int) -> None:
        if not self._has_db():
            return
        try:
            with get_connection() as conn:
                if conn is None:
                    return
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE agent_chat_mapping SET amocrm_lead_id = %s WHERE actor_id = %s",
                        (lead_id, actor_id),
                    )
                conn.commit()
        except (psycopg.Error, OSError):
            logger.warning("Failed to update lead_id in chat mapping for actor=%s", actor_id, exc_info=True)

    def save_manager_message(
        self, actor_id: str, content: str,
        conversation_id: str | None = None,
        amocrm_msgid: str | None = None,
        sender_name: str | None = None,
        agent_conversation_id: str | None = None,
    ) -> bool:
        """Save manager message. Returns True if new, False if duplicate."""
        if not self._has_db():
            return True
        try:
            with get_connection() as conn:
                if conn is None:
                    return True
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO agent_manager_messages
                          (actor_id, conversation_id, amocrm_msgid, sender_name, content, agent_conversation_id)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING
                        """,
                        (actor_id, conversation_id, amocrm_msgid, sender_name, content, agent_conversation_id),
                    )
                    is_new = cur.rowcount > 0
                conn.commit()
                return is_new
        except (psycopg.Error, OSError):
            logger.warning("Failed to save manager message", exc_info=True)
            return True

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
                        SELECT id, actor_id, display_name, client_type, user_role,
                               phone, fio, grade, children, dms_verified,
                               dms_contact_id, dms_data, verification_status
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

    def update_profile_display_name(self, actor_id: str, name: str) -> bool:
        """Update only the display_name field. Creates minimal profile if needed."""
        if not self._has_db():
            return False
        try:
            with get_connection() as conn:
                if conn is None:
                    return False
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO agent_user_profiles (actor_id, display_name)
                        VALUES (%s, %s)
                        ON CONFLICT (actor_id) DO UPDATE
                          SET display_name = COALESCE(EXCLUDED.display_name, agent_user_profiles.display_name)
                        """,
                        (actor_id, name),
                    )
                conn.commit()
                return True
        except (psycopg.Error, OSError):
            logger.warning("Failed to update display_name for actor=%s", actor_id, exc_info=True)
            return False

    # ---- Profile stats -------------------------------------------------------

    def get_profile_stats(self, actor_id: str) -> dict:
        """Get conversation count and last activity for profile page."""
        stats = {"conversation_count": 0, "last_active_at": None}
        if not self._has_db():
            return stats
        try:
            with get_connection() as conn:
                if conn is None:
                    return stats
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT COUNT(*) AS cnt,
                               MAX(updated_at) AS last_active
                        FROM conversations
                        WHERE actor_id = %s AND archived_at IS NULL
                        """,
                        (actor_id,),
                    )
                    row = cur.fetchone()
                    if row:
                        stats["conversation_count"] = row["cnt"]
                        stats["last_active_at"] = row["last_active"]
            return stats
        except (psycopg.Error, OSError):
            logger.warning("Failed to get profile stats for actor=%s", actor_id, exc_info=True)
            return stats

    # ---- Profile enrichment (phone-based merge) ------------------------------

    def find_profiles_by_phone(self, phone: str, exclude_actor_id: str | None = None) -> list[dict]:
        """Find all profiles with the same phone, optionally excluding one actor."""
        if not self._has_db() or not phone:
            return []
        try:
            with get_connection() as conn:
                if conn is None:
                    return []
                with conn.cursor() as cur:
                    if exclude_actor_id:
                        cur.execute(
                            """
                            SELECT id, actor_id, display_name, client_type, user_role,
                                   phone, fio, grade, children, dms_verified,
                                   dms_contact_id, dms_data, verification_status
                            FROM agent_user_profiles
                            WHERE phone = %s AND actor_id != %s
                            ORDER BY dms_verified DESC, updated_at DESC
                            """,
                            (phone, exclude_actor_id),
                        )
                    else:
                        cur.execute(
                            """
                            SELECT id, actor_id, display_name, client_type, user_role,
                                   phone, fio, grade, children, dms_verified,
                                   dms_contact_id, dms_data, verification_status
                            FROM agent_user_profiles
                            WHERE phone = %s
                            ORDER BY dms_verified DESC, updated_at DESC
                            """,
                            (phone,),
                        )
                    rows = cur.fetchall()
                    return [dict(r) for r in rows] if rows else []
        except (psycopg.Error, OSError):
            logger.warning("Failed to find profiles by phone=%s", phone, exc_info=True)
            return []

    def enrich_profile_from_existing(self, actor_id: str, donor: dict) -> bool:
        """Copy missing fields from donor profile to current actor's profile.

        Only fills in fields that are currently NULL — never overwrites existing data.
        DMS-verified donor data always wins over non-verified current data.
        """
        if not self._has_db():
            return False
        try:
            with get_connection() as conn:
                if conn is None:
                    return False
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE agent_user_profiles SET
                          display_name = COALESCE(agent_user_profiles.display_name, %s),
                          fio = COALESCE(agent_user_profiles.fio, %s),
                          grade = COALESCE(agent_user_profiles.grade, %s),
                          children = CASE
                            WHEN agent_user_profiles.children = '[]'::jsonb AND %s != '[]'::jsonb
                            THEN %s ELSE agent_user_profiles.children END,
                          dms_verified = agent_user_profiles.dms_verified OR %s,
                          dms_contact_id = COALESCE(agent_user_profiles.dms_contact_id, %s),
                          dms_data = COALESCE(agent_user_profiles.dms_data, %s),
                          client_type = COALESCE(agent_user_profiles.client_type, %s),
                          user_role = COALESCE(agent_user_profiles.user_role, %s)
                        WHERE actor_id = %s
                        """,
                        (
                            donor.get("display_name"),
                            donor.get("fio"),
                            donor.get("grade"),
                            Json(donor.get("children") or []),
                            Json(donor.get("children") or []),
                            donor.get("dms_verified", False),
                            donor.get("dms_contact_id"),
                            Json(donor.get("dms_data")) if donor.get("dms_data") else None,
                            donor.get("client_type"),
                            donor.get("user_role"),
                            actor_id,
                        ),
                    )
                conn.commit()
                logger.info(
                    "Enriched profile for actor=%s from donor=%s",
                    actor_id, donor.get("actor_id"),
                )
                return True
        except (psycopg.Error, OSError):
            logger.warning("Failed to enrich profile for actor=%s", actor_id, exc_info=True)
            return False

    # ---- Payment orders ----------------------------------------------------

    def save_payment_order(
        self,
        conversation_id: str,
        actor_id: str,
        dms_order_uuid: str,
        amount_kopecks: int,
        payment_url: str,
        product_name: str | None = None,
        product_uuid: str | None = None,
        dms_contact_id: int | None = None,
        pay_type: int = 1,
        amocrm_lead_id: int | None = None,
    ) -> str | None:
        if not self._has_db():
            return None
        try:
            with get_connection() as conn:
                if conn is None:
                    return None
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO agent_payment_orders
                          (conversation_id, actor_id, dms_order_uuid, amount_kopecks,
                           payment_url, product_name, product_uuid, dms_contact_id,
                           pay_type, amocrm_lead_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (conversation_id, actor_id, dms_order_uuid, amount_kopecks,
                         payment_url, product_name, product_uuid, dms_contact_id,
                         pay_type, amocrm_lead_id),
                    )
                    row = cur.fetchone()
                conn.commit()
                return str(row["id"]) if row else None
        except (psycopg.Error, OSError):
            logger.warning("Failed to save payment order", exc_info=True)
            return None

    def get_pending_payments(self) -> list[dict]:
        if not self._has_db():
            return []
        try:
            with get_connection() as conn:
                if conn is None:
                    return []
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, conversation_id, actor_id, dms_order_uuid,
                               product_name, amocrm_lead_id, created_at
                        FROM agent_payment_orders
                        WHERE status = 'pending'
                          AND created_at > NOW() - INTERVAL '8 days'
                        ORDER BY created_at
                        """
                    )
                    rows = cur.fetchall()
                    return [dict(r) for r in rows] if rows else []
        except (psycopg.Error, OSError):
            logger.warning("Failed to get pending payments", exc_info=True)
            return []

    def update_payment_status(self, order_id: str, status: str, paid_at: datetime | None = None) -> None:
        if not self._has_db():
            return
        try:
            with get_connection() as conn:
                if conn is None:
                    return
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE agent_payment_orders
                        SET status = %s, paid_at = %s, updated_at = NOW()
                        WHERE id = %s
                        """,
                        (status, paid_at, order_id),
                    )
                conn.commit()
        except (psycopg.Error, OSError):
            logger.warning("Failed to update payment status", exc_info=True)

    # ---- Follow-up chain ---------------------------------------------------

    def save_followup(
        self,
        conversation_id: str,
        actor_id: str,
        payment_order_id: str | None,
        step: int,
        next_fire_at: datetime,
    ) -> str | None:
        if not self._has_db():
            return None
        try:
            with get_connection() as conn:
                if conn is None:
                    return None
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO agent_followup_chain
                          (conversation_id, actor_id, payment_order_id, step, next_fire_at)
                        VALUES (%s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (conversation_id, actor_id, payment_order_id, step, next_fire_at),
                    )
                    row = cur.fetchone()
                conn.commit()
                return str(row["id"]) if row else None
        except (psycopg.Error, OSError):
            logger.warning("Failed to save followup", exc_info=True)
            return None

    def get_pending_followups(self) -> list[dict]:
        if not self._has_db():
            return []
        try:
            with get_connection() as conn:
                if conn is None:
                    return []
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT f.id, f.conversation_id, f.actor_id, f.step,
                               f.payment_order_id,
                               f.chain_type, f.onboarding_id,
                               p.product_name, p.status AS payment_status,
                               p.payment_url,
                               u.fio AS actor_name,
                               o.child_name, o.child_grade, o.product_name AS onb_product
                        FROM agent_followup_chain f
                        LEFT JOIN agent_payment_orders p ON p.id = f.payment_order_id
                        LEFT JOIN agent_user_profiles u ON u.actor_id = f.actor_id
                        LEFT JOIN agent_onboarding o ON o.id = f.onboarding_id
                        WHERE f.status = 'pending'
                          AND f.next_fire_at <= NOW()
                        ORDER BY f.next_fire_at
                        """
                    )
                    rows = cur.fetchall()
                    return [dict(r) for r in rows] if rows else []
        except (psycopg.Error, OSError):
            logger.warning("Failed to get pending followups", exc_info=True)
            return []

    def update_followup_status(self, followup_id: str, status: str, sent_at: datetime | None = None) -> None:
        if not self._has_db():
            return
        try:
            with get_connection() as conn:
                if conn is None:
                    return
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE agent_followup_chain
                        SET status = %s, sent_at = %s
                        WHERE id = %s
                        """,
                        (status, sent_at, followup_id),
                    )
                conn.commit()
        except (psycopg.Error, OSError):
            logger.warning("Failed to update followup status", exc_info=True)

    def cancel_followups_for_conversation(self, conversation_id: str) -> int:
        """Cancel all pending follow-ups for a conversation. Returns count cancelled."""
        if not self._has_db():
            return 0
        try:
            with get_connection() as conn:
                if conn is None:
                    return 0
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE agent_followup_chain
                        SET status = 'cancelled'
                        WHERE conversation_id = %s AND status = 'pending'
                        """,
                        (conversation_id,),
                    )
                    count = cur.rowcount
                conn.commit()
                if count:
                    logger.info("Cancelled %d follow-ups for conv=%s", count, conversation_id)
                return count
        except (psycopg.Error, OSError):
            logger.warning("Failed to cancel followups for conv=%s", conversation_id, exc_info=True)
            return 0

    def update_conversation_metadata(self, conversation_id: str, metadata: dict) -> None:
        """Merge metadata into the conversation's existing metadata JSON."""
        if not self._has_db():
            return
        try:
            with get_connection() as conn:
                if conn is None:
                    return
                with conn.cursor() as cur:
                    cur.execute(
                        """UPDATE conversations
                           SET metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb
                           WHERE id = %s""",
                        (Json(metadata), conversation_id),
                    )
                    conn.commit()
        except (psycopg.Error, OSError):
            logger.warning("Failed to update conversation metadata for %s", conversation_id, exc_info=True)

    def get_conversation_metadata(self, conversation_id: str) -> dict | None:
        if not self._has_db():
            return None
        try:
            with get_connection() as conn:
                if conn is None:
                    return None
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT metadata FROM conversations WHERE id = %s",
                        (conversation_id,),
                    )
                    row = cur.fetchone()
                    return row["metadata"] if row and row.get("metadata") else None
        except (psycopg.Error, OSError):
            return None

    # ---- Support onboarding -----------------------------------------------

    def save_onboarding(
        self,
        actor_id: str,
        payment_order_id: str | None = None,
        conversation_id: str | None = None,
        dms_contact_id: int | None = None,
        product_name: str | None = None,
        child_name: str | None = None,
        child_grade: int | None = None,
        status: str = "pending",
    ) -> str | None:
        if not self._has_db():
            return None
        try:
            with get_connection() as conn:
                if conn is None:
                    return None
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO agent_onboarding
                          (actor_id, payment_order_id, conversation_id,
                           dms_contact_id, product_name, child_name, child_grade, status)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (actor_id, payment_order_id, conversation_id,
                         dms_contact_id, product_name, child_name, child_grade, status),
                    )
                    row = cur.fetchone()
                conn.commit()
                return str(row["id"]) if row else None
        except (psycopg.Error, OSError):
            logger.warning("Failed to save onboarding", exc_info=True)
            return None

    def get_onboarding_by_payment(self, payment_order_id: str) -> dict | None:
        """Check if onboarding already exists for a payment order (dedup guard)."""
        if not self._has_db():
            return None
        try:
            with get_connection() as conn:
                if conn is None:
                    return None
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, status FROM agent_onboarding WHERE payment_order_id = %s LIMIT 1",
                        (payment_order_id,),
                    )
                    row = cur.fetchone()
                    return dict(row) if row else None
        except (psycopg.Error, OSError):
            return None

    def update_onboarding_status(
        self,
        onboarding_id: str,
        status: str,
        greeting_sent_at: datetime | None = None,
        followup_sent_at: datetime | None = None,
        escalated_at: datetime | None = None,
        client_responded: bool | None = None,
    ) -> None:
        if not self._has_db():
            return
        try:
            with get_connection() as conn:
                if conn is None:
                    return
                with conn.cursor() as cur:
                    sets = ["status = %s", "updated_at = NOW()"]
                    params: list = [status]
                    if greeting_sent_at is not None:
                        sets.append("greeting_sent_at = %s")
                        params.append(greeting_sent_at)
                    if followup_sent_at is not None:
                        sets.append("followup_sent_at = %s")
                        params.append(followup_sent_at)
                    if escalated_at is not None:
                        sets.append("escalated_at = %s")
                        params.append(escalated_at)
                    if client_responded is not None:
                        sets.append("client_responded = %s")
                        params.append(client_responded)
                    params.append(onboarding_id)
                    cur.execute(
                        f"UPDATE agent_onboarding SET {', '.join(sets)} WHERE id = %s",
                        params,
                    )
                conn.commit()
        except (psycopg.Error, OSError):
            logger.warning("Failed to update onboarding %s", onboarding_id, exc_info=True)

    def check_user_replied_in_conversation(self, conversation_id: str) -> bool:
        """Check if user sent any message in a conversation."""
        if not self._has_db():
            return False
        try:
            with get_connection() as conn:
                if conn is None:
                    return False
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT EXISTS(
                          SELECT 1 FROM chat_messages
                          WHERE conversation_id = %s AND role = 'user'
                        ) AS replied
                        """,
                        (conversation_id,),
                    )
                    row = cur.fetchone()
                    return bool(row["replied"]) if row else False
        except (psycopg.Error, OSError):
            return False

    def get_active_onboarding_for_conversation(self, conversation_id: str) -> dict | None:
        """Get active onboarding record for a conversation (for response detection)."""
        if not self._has_db():
            return None
        try:
            with get_connection() as conn:
                if conn is None:
                    return None
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, status, client_responded
                        FROM agent_onboarding
                        WHERE conversation_id = %s
                          AND status IN ('greeting_sent', 'followup_sent')
                        LIMIT 1
                        """,
                        (conversation_id,),
                    )
                    row = cur.fetchone()
                    return dict(row) if row else None
        except (psycopg.Error, OSError):
            return None

    def save_followup_with_type(
        self,
        conversation_id: str,
        actor_id: str,
        payment_order_id: str | None,
        step: int,
        next_fire_at: datetime,
        chain_type: str = "payment",
        onboarding_id: str | None = None,
    ) -> str | None:
        """Save followup with chain_type discriminator."""
        if not self._has_db():
            return None
        try:
            with get_connection() as conn:
                if conn is None:
                    return None
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO agent_followup_chain
                          (conversation_id, actor_id, payment_order_id, step,
                           next_fire_at, chain_type, onboarding_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (conversation_id, actor_id, payment_order_id, step,
                         next_fire_at, chain_type, onboarding_id),
                    )
                    row = cur.fetchone()
                conn.commit()
                return str(row["id"]) if row else None
        except (psycopg.Error, OSError):
            logger.warning("Failed to save followup with type", exc_info=True)
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

    # ---- Funnel / Pipeline Stage Methods ------------------------------------

    def update_funnel_stage(
        self, conversation_id: str, stage: str, pipeline: str | None = None,
    ) -> None:
        """Update funnel stage on conversation."""
        if not self._has_db():
            return
        try:
            with get_connection() as conn:
                if conn is None:
                    return
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE conversations
                        SET funnel_stage = %s,
                            funnel_pipeline = COALESCE(%s, funnel_pipeline),
                            updated_at = NOW()
                        WHERE id = %s
                        """,
                        (stage, pipeline, conversation_id),
                    )
                conn.commit()
        except (psycopg.Error, OSError):
            logger.warning("Failed to update funnel stage conv=%s", conversation_id, exc_info=True)

    def get_funnel_stage(self, conversation_id: str) -> dict | None:
        """Return {funnel_stage, funnel_pipeline} for conversation."""
        if not self._has_db():
            return None
        try:
            with get_connection() as conn:
                if conn is None:
                    return None
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT funnel_stage, funnel_pipeline FROM conversations WHERE id = %s",
                        (conversation_id,),
                    )
                    return cur.fetchone()
        except (psycopg.Error, OSError):
            return None

    def update_deal_funnel_stage(
        self, conversation_id: str, stage: str, stage_history_entry: dict | None = None,
    ) -> None:
        """Update funnel_stage and append to stage_history on agent_deal_mapping."""
        if not self._has_db():
            return
        try:
            with get_connection() as conn:
                if conn is None:
                    return
                with conn.cursor() as cur:
                    if stage_history_entry:
                        cur.execute(
                            """
                            UPDATE agent_deal_mapping
                            SET funnel_stage = %s,
                                stage_history = COALESCE(stage_history, '[]'::jsonb) || %s::jsonb,
                                updated_at = NOW()
                            WHERE conversation_id = %s
                            """,
                            (stage, json.dumps([stage_history_entry]), conversation_id),
                        )
                    else:
                        cur.execute(
                            """
                            UPDATE agent_deal_mapping
                            SET funnel_stage = %s, updated_at = NOW()
                            WHERE conversation_id = %s
                            """,
                            (stage, conversation_id),
                        )
                conn.commit()
        except (psycopg.Error, OSError):
            logger.warning("Failed to update deal funnel stage conv=%s", conversation_id, exc_info=True)

    def set_manager_approved(self, conversation_id: str) -> bool:
        """Mark deal as approved by manager. Returns True if updated."""
        if not self._has_db():
            return False
        try:
            with get_connection() as conn:
                if conn is None:
                    return False
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE agent_deal_mapping
                        SET manager_approved_at = NOW(), updated_at = NOW()
                        WHERE conversation_id = %s AND manager_approved_at IS NULL
                        """,
                        (conversation_id,),
                    )
                conn.commit()
                return cur.rowcount > 0
        except (psycopg.Error, OSError):
            logger.warning("Failed to set manager approved conv=%s", conversation_id, exc_info=True)
            return False

    def is_manager_approved(self, conversation_id: str) -> bool:
        """Check if manager has approved this deal."""
        if not self._has_db():
            return False
        try:
            with get_connection() as conn:
                if conn is None:
                    return False
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT manager_approved_at FROM agent_deal_mapping WHERE conversation_id = %s",
                        (conversation_id,),
                    )
                    row = cur.fetchone()
                    return bool(row and row["manager_approved_at"])
        except (psycopg.Error, OSError):
            return False

    def save_decline_reasons(
        self, conversation_id: str, reasons: list[str], notes: str | None = None,
    ) -> None:
        """Save structured decline reasons to deal mapping."""
        if not self._has_db():
            return
        try:
            data = {"reasons": reasons, "notes": notes}
            with get_connection() as conn:
                if conn is None:
                    return
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE agent_deal_mapping
                        SET decline_reasons = %s::jsonb, updated_at = NOW()
                        WHERE conversation_id = %s
                        """,
                        (json.dumps(data, ensure_ascii=False), conversation_id),
                    )
                conn.commit()
        except (psycopg.Error, OSError):
            logger.warning("Failed to save decline reasons conv=%s", conversation_id, exc_info=True)

    # ---- Manager Active State -----------------------------------------------

    def set_manager_active(self, conversation_id: str, active: bool) -> None:
        """Set manager_is_active flag and update last_manager_activity_at."""
        if not self._has_db():
            return
        try:
            with get_connection() as conn:
                if conn is None:
                    return
                with conn.cursor() as cur:
                    if active:
                        cur.execute(
                            """
                            UPDATE conversations
                            SET manager_is_active = TRUE,
                                last_manager_activity_at = NOW(),
                                updated_at = NOW()
                            WHERE id = %s
                            """,
                            (conversation_id,),
                        )
                    else:
                        cur.execute(
                            """
                            UPDATE conversations
                            SET manager_is_active = FALSE,
                                updated_at = NOW()
                            WHERE id = %s
                            """,
                            (conversation_id,),
                        )
                conn.commit()
        except (psycopg.Error, OSError):
            logger.warning("Failed to set manager active conv=%s", conversation_id, exc_info=True)

    def is_manager_active(self, conversation_id: str) -> bool:
        """Check if manager is currently active. Auto-expires after 15 min inactivity."""
        if not self._has_db():
            return False
        try:
            with get_connection() as conn:
                if conn is None:
                    return False
                with conn.cursor() as cur:
                    # Auto-expire: reset flag if manager inactive for 15+ minutes
                    cur.execute(
                        """
                        UPDATE conversations
                        SET manager_is_active = FALSE, updated_at = NOW()
                        WHERE id = %s
                          AND manager_is_active = TRUE
                          AND last_manager_activity_at < NOW() - INTERVAL '15 minutes'
                        RETURNING id
                        """,
                        (conversation_id,),
                    )
                    if cur.fetchone():
                        conn.commit()
                        logger.info("Manager auto-expired for conv=%s (15 min TTL)", conversation_id)
                        return False

                    cur.execute(
                        "SELECT manager_is_active FROM conversations WHERE id = %s",
                        (conversation_id,),
                    )
                    row = cur.fetchone()
                    return bool(row and row["manager_is_active"])
        except (psycopg.Error, OSError):
            return False

    # ---- SSE Live Channel: get messages since timestamp ----------------------

    def get_messages_since(
        self, conversation_id: str, since: datetime,
    ) -> list[dict]:
        """Get messages newer than `since` for SSE live push."""
        if not self._has_db():
            return []
        try:
            with get_connection() as conn:
                if conn is None:
                    return []
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, role, content, metadata, created_at
                        FROM chat_messages
                        WHERE conversation_id = %s AND created_at > %s
                        ORDER BY created_at ASC
                        LIMIT 20
                        """,
                        (conversation_id, since),
                    )
                    rows = cur.fetchall()
                    return [dict(r) for r in rows]
        except (psycopg.Error, OSError):
            return []

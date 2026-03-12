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
    status: str = "active"
    title: str | None = None
    message_count: int = 0
    last_user_message: str | None = None
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
                        select id, actor_id, channel, agent_role,
                               title, message_count, last_user_message,
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
                            title=row.get("title"),
                            message_count=row.get("message_count", 0) or 0,
                            last_user_message=row.get("last_user_message"),
                            created_at=row.get("created_at"),
                            updated_at=row.get("updated_at"),
                            archived_at=row.get("archived_at"),
                        )

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
                        SET message_count = message_count + 1,
                            last_user_message = %s
                        WHERE id = %s
                        RETURNING message_count, title
                        """,
                        (user_message[:500], conversation_id),
                    )
                    row = cur.fetchone()

                    # Auto-title from first user message if no title yet
                    if row and row["message_count"] == 1 and not row["title"]:
                        title = user_message[:60].rsplit(" ", 1)[0] if len(user_message) > 60 else user_message
                        cur.execute(
                            "UPDATE conversations SET title = %s WHERE id = %s",
                            (title.strip(), conversation_id),
                        )

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
                               p.product_name, p.status AS payment_status,
                               p.payment_url,
                               u.fio AS actor_name
                        FROM agent_followup_chain f
                        LEFT JOIN agent_payment_orders p ON p.id = f.payment_order_id
                        LEFT JOIN agent_user_profiles u ON u.actor_id = f.actor_id
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

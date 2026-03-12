from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime

import psycopg
from psycopg.types.json import Json

from app.db.pool import get_connection, has_pool

logger = logging.getLogger(__name__)


@dataclass
class ConversationSummary:
    id: str
    conversation_id: str
    actor_id: str
    agent_role: str
    summary_type: str
    summary_text: str
    topics: list[str] = field(default_factory=list)
    decisions: list = field(default_factory=list)
    preferences: list = field(default_factory=list)
    unresolved: list = field(default_factory=list)
    similarity: float = 0.0
    created_at: datetime | None = None


@dataclass
class MemoryAtom:
    id: str
    actor_id: str
    agent_role: str
    fact_type: str
    subject: str
    predicate: str
    object: str | None = None
    confidence: float = 0.8
    conversation_id: str | None = None
    similarity: float = 0.0
    created_at: datetime | None = None


class MemoryRepository:
    def _has_db(self) -> bool:
        return has_pool()

    # ---- Summaries -----------------------------------------------------------

    def save_summary(
        self,
        conversation_id: str,
        actor_id: str,
        agent_role: str,
        summary_text: str,
        topics: list[str],
        decisions: list,
        preferences: list,
        unresolved: list,
        embedding: list[float],
        summary_type: str = "conversation",
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
                        INSERT INTO agent_conversation_summaries
                          (conversation_id, actor_id, agent_role, summary_type,
                           summary_text, topics, decisions, preferences, unresolved, embedding)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (
                            conversation_id, actor_id, agent_role, summary_type,
                            summary_text, topics, Json(decisions), Json(preferences),
                            Json(unresolved), str(embedding),
                        ),
                    )
                    row = cur.fetchone()
                conn.commit()
                return str(row["id"]) if row else None
        except (psycopg.Error, OSError):
            logger.warning("Failed to save summary for conv=%s", conversation_id, exc_info=True)
            return None

    def has_summary(self, conversation_id: str) -> bool:
        if not self._has_db():
            return False
        try:
            with get_connection() as conn:
                if conn is None:
                    return False
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT 1 FROM agent_conversation_summaries WHERE conversation_id = %s LIMIT 1",
                        (conversation_id,),
                    )
                    return cur.fetchone() is not None
        except (psycopg.Error, OSError):
            return False

    def search_summaries(
        self,
        actor_id: str,
        query_embedding: list[float],
        agent_role: str | None = None,
        threshold: float = 0.4,
        top_k: int = 3,
    ) -> list[ConversationSummary]:
        if not self._has_db():
            return []
        try:
            emb_str = str(query_embedding)
            with get_connection() as conn:
                if conn is None:
                    return []
                with conn.cursor() as cur:
                    where = "WHERE actor_id = %s AND summary_type = 'conversation'"
                    params: list = [actor_id]

                    if agent_role:
                        where += " AND agent_role = %s"
                        params.append(agent_role)

                    where += " AND 1 - (embedding <=> %s::vector) > %s"
                    params.extend([emb_str, threshold])

                    cur.execute(
                        f"""
                        SELECT id, conversation_id, actor_id, agent_role, summary_type,
                               summary_text, topics, decisions, preferences, unresolved,
                               1 - (embedding <=> %s::vector) AS similarity,
                               created_at
                        FROM agent_conversation_summaries
                        {where}
                        ORDER BY embedding <=> %s::vector
                        LIMIT %s
                        """,
                        [emb_str, *params, emb_str, top_k],
                    )
                    rows = cur.fetchall()

            return [
                ConversationSummary(
                    id=str(row["id"]),
                    conversation_id=str(row["conversation_id"]),
                    actor_id=row["actor_id"],
                    agent_role=row["agent_role"],
                    summary_type=row["summary_type"],
                    summary_text=row["summary_text"],
                    topics=row.get("topics") or [],
                    decisions=row.get("decisions") or [],
                    preferences=row.get("preferences") or [],
                    unresolved=row.get("unresolved") or [],
                    similarity=round(row["similarity"], 4),
                    created_at=row.get("created_at"),
                )
                for row in rows
            ]
        except (psycopg.Error, OSError):
            logger.warning("Failed to search summaries for actor=%s", actor_id, exc_info=True)
            return []

    # ---- Memory Atoms --------------------------------------------------------

    def save_memory_atom(
        self,
        actor_id: str,
        agent_role: str,
        fact_type: str,
        subject: str,
        predicate: str,
        embedding: list[float],
        object_val: str | None = None,
        confidence: float = 0.8,
        conversation_id: str | None = None,
    ) -> str | None:
        if not self._has_db():
            return None
        try:
            with get_connection() as conn:
                if conn is None:
                    return None
                with conn.cursor() as cur:
                    # Check for existing atom with same subject+predicate+role
                    cur.execute(
                        """
                        SELECT id, object FROM agent_memory_atoms
                        WHERE actor_id = %s AND agent_role = %s
                          AND subject = %s AND predicate = %s
                          AND superseded_by IS NULL
                        LIMIT 1
                        """,
                        (actor_id, agent_role, subject, predicate),
                    )
                    existing = cur.fetchone()

                    # Skip insert if identical fact already exists
                    if existing and existing.get("object") == object_val:
                        conn.commit()
                        return str(existing["id"])

                    # Insert new atom
                    cur.execute(
                        """
                        INSERT INTO agent_memory_atoms
                          (actor_id, agent_role, conversation_id, fact_type,
                           subject, predicate, object, confidence, embedding)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        RETURNING id
                        """,
                        (
                            actor_id, agent_role, conversation_id, fact_type,
                            subject, predicate, object_val, confidence, str(embedding),
                        ),
                    )
                    new_row = cur.fetchone()
                    new_id = str(new_row["id"]) if new_row else None

                    # Supersede old fact if object changed
                    if existing and new_id:
                        cur.execute(
                            "UPDATE agent_memory_atoms SET superseded_by = %s WHERE id = %s",
                            (new_id, existing["id"]),
                        )

                conn.commit()
                return new_id
        except (psycopg.Error, OSError):
            logger.warning("Failed to save memory atom for actor=%s", actor_id, exc_info=True)
            return None

    def search_atoms(
        self,
        actor_id: str,
        query_embedding: list[float],
        agent_role: str | None = None,
        cross_role_types: list[str] | None = None,
        threshold: float = 0.35,
        top_k: int = 5,
    ) -> list[MemoryAtom]:
        """Search active memory atoms by vector similarity.

        cross_role_types: fact types that ignore agent_role filter (e.g. ['entity', 'preference']).
        """
        if not self._has_db():
            return []
        cross_role_types = cross_role_types or []
        try:
            emb_str = str(query_embedding)
            with get_connection() as conn:
                if conn is None:
                    return []
                with conn.cursor() as cur:
                    # Build role filter: cross-role types bypass role filter
                    where = """
                        WHERE actor_id = %s
                          AND superseded_by IS NULL
                          AND (expires_at IS NULL OR expires_at > NOW())
                          AND 1 - (embedding <=> %s::vector) > %s
                    """
                    params: list = [actor_id, emb_str, threshold]

                    if agent_role and cross_role_types:
                        where += " AND (agent_role = %s OR fact_type = ANY(%s))"
                        params.extend([agent_role, cross_role_types])
                    elif agent_role:
                        where += " AND agent_role = %s"
                        params.append(agent_role)

                    cur.execute(
                        f"""
                        SELECT id, actor_id, agent_role, conversation_id, fact_type,
                               subject, predicate, object, confidence,
                               1 - (embedding <=> %s::vector) AS similarity,
                               created_at
                        FROM agent_memory_atoms
                        {where}
                        ORDER BY embedding <=> %s::vector
                        LIMIT %s
                        """,
                        [emb_str, *params, emb_str, top_k],
                    )
                    rows = cur.fetchall()

            return [
                MemoryAtom(
                    id=str(row["id"]),
                    actor_id=row["actor_id"],
                    agent_role=row["agent_role"],
                    fact_type=row["fact_type"],
                    subject=row["subject"],
                    predicate=row["predicate"],
                    object=row.get("object"),
                    confidence=row.get("confidence", 0.8),
                    conversation_id=str(row["conversation_id"]) if row.get("conversation_id") else None,
                    similarity=round(row["similarity"], 4),
                    created_at=row.get("created_at"),
                )
                for row in rows
            ]
        except (psycopg.Error, OSError):
            logger.warning("Failed to search memory atoms for actor=%s", actor_id, exc_info=True)
            return []

    # ---- Idle conversations for summarization --------------------------------

    def get_idle_unsummarized(self, idle_minutes: int = 30, min_messages: int = 4) -> list[dict]:
        """Get conversations that are idle and have no summary yet."""
        if not self._has_db():
            return []
        try:
            with get_connection() as conn:
                if conn is None:
                    return []
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT c.id, c.actor_id, c.agent_role, c.message_count
                        FROM conversations c
                        WHERE c.updated_at < NOW() - (%s * INTERVAL '1 minute')
                          AND c.status IN ('active', 'escalated')
                          AND c.message_count >= %s
                          AND c.archived_at IS NULL
                          AND NOT EXISTS (
                            SELECT 1 FROM agent_conversation_summaries s
                            WHERE s.conversation_id = c.id
                          )
                        ORDER BY c.updated_at ASC
                        LIMIT 20
                        """,
                        (idle_minutes, min_messages),
                    )
                    rows = cur.fetchall()
                    return [dict(r) for r in rows] if rows else []
        except (psycopg.Error, OSError):
            logger.warning("Failed to get idle unsummarized conversations", exc_info=True)
            return []

"""Memory service: retrieval, scoring, and context assembly.

Called on every user message to inject relevant memories from past conversations
into the LLM context window.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from cachetools import TTLCache
from openai import OpenAI

from app.config import get_settings
from app.db.memory_repository import ConversationSummary, MemoryAtom, MemoryRepository

logger = logging.getLogger("memory")

# Cache: actor_id → formatted memory context string (5 min TTL)
_memory_cache: TTLCache[str, str] = TTLCache(maxsize=200, ttl=300)

# Fact type boost for scoring
_TYPE_BOOST = {
    "action_item": 1.3,
    "preference": 1.2,
    "decision": 1.1,
    "question": 1.1,
    "entity": 1.0,
    "feedback": 0.9,
}

MEMORY_CONTEXT_TEMPLATE = """\
# Память из прошлых диалогов

Ниже — информация из предыдущих разговоров с этим клиентом.
Используй её для персонализации, но НЕ ссылайся на неё явно ("Вы ранее говорили...").
Если клиент упоминает тему, которая обсуждалась ранее — покажи, что помнишь контекст.

{facts_section}{summaries_section}"""


_openai_client: OpenAI | None = None


def _get_openai_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        from app.services.openai_client import get_openai_client
        _openai_client = get_openai_client()
    return _openai_client


def _embed_query(text: str) -> list[float]:
    from openai import RateLimitError
    from app.services.openai_client import is_quota_error, switch_to_fallback, get_openai_client
    global _openai_client

    settings = get_settings()
    client = _get_openai_client()
    try:
        response = client.embeddings.create(
            model=settings.openai_embedding_model,
            input=[text],
        )
        return response.data[0].embedding
    except RateLimitError as e:
        if is_quota_error(e) and switch_to_fallback():
            _openai_client = get_openai_client()
            response = _openai_client.embeddings.create(
                model=settings.openai_embedding_model,
                input=[text],
            )
            return response.data[0].embedding
        raise


def _score_memory(similarity: float, created_at: datetime | None, fact_type: str, halflife_days: int = 30) -> float:
    """Composite score: similarity * 0.6 + recency * 0.25 + type_boost * 0.15"""
    # Recency decay
    if created_at:
        now = datetime.now(tz=timezone.utc)
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        age_days = (now - created_at).total_seconds() / 86400
        recency = 0.5 ** (age_days / max(halflife_days, 1))
    else:
        recency = 0.5

    type_boost = _TYPE_BOOST.get(fact_type, 1.0)
    # Normalize type_boost to 0-1 range (max is 1.3)
    normalized_boost = type_boost / 1.3

    return similarity * 0.6 + recency * 0.25 + normalized_boost * 0.15


def _format_facts(atoms: list[tuple[MemoryAtom, float]]) -> str:
    if not atoms:
        return ""
    lines = ["## Факты о клиенте:"]
    for atom, score in atoms:
        obj_str = f" {atom.object}" if atom.object else ""
        lines.append(f"- {atom.subject} {atom.predicate}{obj_str} (уверенность: {atom.confidence})")
    return "\n".join(lines)


def _format_summaries(summaries: list[tuple[ConversationSummary, float]]) -> str:
    if not summaries:
        return ""
    lines = ["\n## Из прошлых диалогов:"]
    for summary, score in summaries:
        age = ""
        if summary.created_at:
            now = datetime.now(tz=timezone.utc)
            ca = summary.created_at
            if ca.tzinfo is None:
                ca = ca.replace(tzinfo=timezone.utc)
            days = int((now - ca).total_seconds() / 86400)
            if days == 0:
                age = "сегодня"
            elif days == 1:
                age = "вчера"
            elif days < 7:
                age = f"{days} дн. назад"
            else:
                age = f"{days // 7} нед. назад"

        prefix = f"[{age}] " if age else ""
        lines.append(f"- {prefix}{summary.summary_text}")
    return "\n".join(lines)


class MemoryService:
    def __init__(self) -> None:
        self.repo = MemoryRepository()
        self.settings = get_settings()

    @property
    def enabled(self) -> bool:
        return getattr(self.settings, "memory_enabled", True)

    def get_memory_context(self, actor_id: str, user_text: str, agent_role: str) -> str | None:
        """Retrieve and format memory context for LLM injection.

        Returns formatted string or None if no relevant memories found.
        """
        if not self.enabled:
            return None

        # Check cache (key includes query hash so different questions get different results)
        query_hash = hashlib.md5(user_text.encode()).hexdigest()[:8]
        cache_key = f"{actor_id}:{agent_role}:{query_hash}"
        cached = _memory_cache.get(cache_key)
        if cached is not None:
            return cached if cached else None

        try:
            query_embedding = _embed_query(user_text)
        except Exception:
            logger.warning("Failed to embed query for memory retrieval", exc_info=True)
            return None

        halflife = getattr(self.settings, "memory_recency_halflife_days", 30)
        cross_types = getattr(self.settings, "memory_cross_role_types", "preference,entity")
        cross_role_list = [t.strip() for t in cross_types.split(",") if t.strip()]

        # Semantic search (similarity-based)
        summaries = self.repo.search_summaries(
            actor_id=actor_id,
            query_embedding=query_embedding,
            agent_role=agent_role,
            threshold=getattr(self.settings, "memory_summary_threshold", 0.4),
            top_k=getattr(self.settings, "memory_summary_top_k", 3),
        )

        atoms = self.repo.search_atoms(
            actor_id=actor_id,
            query_embedding=query_embedding,
            agent_role=agent_role,
            cross_role_types=cross_role_list,
            threshold=getattr(self.settings, "memory_atom_threshold", 0.35),
            top_k=getattr(self.settings, "memory_atoms_top_k", 5),
        )

        # Always include recent facts and summaries (identity, context)
        # regardless of semantic similarity — name, phone, grade are always relevant
        recent_atoms = self.repo.get_recent_atoms(actor_id, top_k=5)
        recent_summaries = self.repo.get_recent_summaries(actor_id, top_k=2)

        # Merge: deduplicate by id
        seen_atom_ids = {a.id for a in atoms}
        for ra in recent_atoms:
            if ra.id not in seen_atom_ids:
                atoms.append(ra)
                seen_atom_ids.add(ra.id)

        seen_summary_ids = {s.id for s in summaries}
        for rs in recent_summaries:
            if rs.id not in seen_summary_ids:
                summaries.append(rs)
                seen_summary_ids.add(rs.id)

        if not summaries and not atoms:
            _memory_cache[cache_key] = ""
            return None

        logger.info("Memory for %s: %d atoms, %d summaries", actor_id, len(atoms), len(summaries))

        # Score and sort
        scored_summaries = [
            (s, _score_memory(s.similarity, s.created_at, "decision", halflife))
            for s in summaries
        ]
        scored_atoms = [
            (a, _score_memory(a.similarity, a.created_at, a.fact_type, halflife))
            for a in atoms
        ]
        scored_summaries.sort(key=lambda x: x[1], reverse=True)
        scored_atoms.sort(key=lambda x: x[1], reverse=True)

        # Format
        facts_section = _format_facts(scored_atoms)
        summaries_section = _format_summaries(scored_summaries)

        if not facts_section and not summaries_section:
            _memory_cache[cache_key] = ""
            return None

        context = MEMORY_CONTEXT_TEMPLATE.format(
            facts_section=facts_section,
            summaries_section=summaries_section,
        ).strip()

        # Token budget: rough estimate (1 token ≈ 4 chars for Russian)
        max_tokens = getattr(self.settings, "memory_max_context_tokens", 800)
        max_chars = max_tokens * 4
        if len(context) > max_chars:
            context = context[:max_chars].rsplit("\n", 1)[0]

        _memory_cache[cache_key] = context
        return context

    def invalidate_cache(self, actor_id: str, agent_role: str | None = None) -> None:
        """Clear cached memory for an actor (e.g., after new summary is created)."""
        prefix = f"{actor_id}:{agent_role}:" if agent_role else f"{actor_id}:"
        for key in list(_memory_cache.keys()):
            if key.startswith(prefix):
                _memory_cache.pop(key, None)

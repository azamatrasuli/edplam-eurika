"""Conversation summarization and fact extraction pipeline.

Runs as a background job: finds idle conversations, extracts summaries and
atomic facts via GPT-4o, embeds them, and stores in pgvector tables.
"""
from __future__ import annotations

import json
import logging

from openai import RateLimitError

from app.config import get_settings
from app.db.memory_repository import MemoryRepository
from app.db.repository import ConversationRepository
from app.models.chat import ChatMessage
from app.services.memory import MemoryService
from app.services.openai_client import get_openai_client, is_quota_error, switch_to_fallback

logger = logging.getLogger("summarizer")


def _get_client():
    return get_openai_client()


SUMMARIZE_PROMPT = """\
Проанализируй этот диалог между AI-агентом и клиентом и извлеки структурированную информацию.

ДИАЛОГ:
{messages}

Ответь СТРОГО в JSON формате (без markdown):
{{
  "summary": "краткое содержание диалога (2-3 предложения на русском)",
  "title": "краткий заголовок беседы (до 50 символов на русском)",
  "topics": ["тема1", "тема2"],
  "decisions": [{{"what": "что решено", "context": "контекст"}}],
  "preferences": [{{"subject": "о чём", "preference": "что предпочитает", "sentiment": "positive"}}],
  "unresolved": [{{"question": "что не решено", "context": "контекст"}}],
  "facts": [{{"subject": "субъект", "predicate": "предикат", "object": "объект", "type": "entity"}}]
}}

Типы фактов:
- entity: имя клиента, имя ребёнка, телефон, класс, возраст, email — любые идентификационные данные (ВАЖНО: всё что идентифицирует клиента — это entity)
- preference: предпочтения клиента (формат обучения, бюджет, время связи)
- decision: решения, принятые в диалоге (выбранный тариф, согласие на оплату)
- action_item: что нужно сделать (перезвонить, отправить документы)
- question: нерешённые вопросы клиента
- feedback: отзывы, жалобы, благодарности
Если какой-то раздел пуст — оставь пустой массив.
"""


def _format_messages(messages: list[ChatMessage]) -> str:
    lines = []
    for m in messages:
        role_label = "Клиент" if m.role == "user" else "Агент"
        lines.append(f"{role_label}: {m.content}")
    return "\n".join(lines)


def _embed_batch(texts: list[str], settings=None) -> list[list[float]]:
    settings = settings or get_settings()
    client = _get_client()
    try:
        response = client.embeddings.create(
            model=settings.openai_embedding_model, input=texts,
        )
    except RateLimitError as e:
        if is_quota_error(e):
            switch_to_fallback()
            client = _get_client()
            response = client.embeddings.create(
                model=settings.openai_embedding_model, input=texts,
            )
        else:
            raise
    return [item.embedding for item in response.data]


def _call_summarize_llm(messages: list[ChatMessage], settings=None) -> dict | None:
    settings = settings or get_settings()
    client = _get_client()

    formatted = _format_messages(messages)
    prompt = SUMMARIZE_PROMPT.format(messages=formatted)

    try:
        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=1500,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        return json.loads(content)
    except RateLimitError as e:
        if is_quota_error(e):
            switch_to_fallback()
            client = _get_client()
            response = client.chat.completions.create(
                model=settings.openai_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0, max_tokens=1500,
                response_format={"type": "json_object"},
            )
            return json.loads(response.choices[0].message.content)
        logger.exception("Failed to call summarize LLM")
        return None
    except Exception:
        logger.exception("Failed to call summarize LLM")
        return None


def summarize_conversation(
    conversation_id: str,
    actor_id: str,
    agent_role: str,
    conv_repo: ConversationRepository,
    mem_repo: MemoryRepository,
) -> bool:
    """Summarize a single conversation. Returns True on success."""
    messages = conv_repo.get_messages(conversation_id, limit=50)
    if len(messages) < 4:
        return False

    # Filter to user + assistant messages only
    messages = [m for m in messages if m.role in ("user", "assistant")]
    if len(messages) < 4:
        return False

    summary_data = _call_summarize_llm(messages)
    if not summary_data:
        return False

    # Batch embed: summary + all facts
    texts_to_embed = [summary_data.get("summary", "")]
    facts = summary_data.get("facts", [])
    for fact in facts:
        fact_text = f"{fact.get('subject', '')} {fact.get('predicate', '')} {fact.get('object', '')}".strip()
        texts_to_embed.append(fact_text)

    try:
        embeddings = _embed_batch(texts_to_embed)
    except Exception:
        logger.exception("Failed to embed summary for conv=%s", conversation_id)
        return False

    summary_embedding = embeddings[0]
    fact_embeddings = embeddings[1:]

    # Save summary
    mem_repo.save_summary(
        conversation_id=conversation_id,
        actor_id=actor_id,
        agent_role=agent_role,
        summary_text=summary_data.get("summary", ""),
        topics=summary_data.get("topics", []),
        decisions=summary_data.get("decisions", []),
        preferences=summary_data.get("preferences", []),
        unresolved=summary_data.get("unresolved", []),
        embedding=summary_embedding,
    )

    # Save memory atoms
    for i, fact in enumerate(facts):
        if i < len(fact_embeddings):
            mem_repo.save_memory_atom(
                actor_id=actor_id,
                agent_role=agent_role,
                conversation_id=conversation_id,
                fact_type=fact.get("type", "entity"),
                subject=fact.get("subject", ""),
                predicate=fact.get("predicate", ""),
                object_val=fact.get("object"),
                embedding=fact_embeddings[i],
            )

    # Update conversation title with LLM-generated title
    llm_title = summary_data.get("title")
    if llm_title:
        conv_repo.update_conversation_title(conversation_id, llm_title[:100])

    # Mark conversation as summarized only if archived (not actively used)
    try:
        from app.db.pool import get_connection
        with get_connection() as conn:
            if conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT archived_at FROM conversations WHERE id = %s",
                        (conversation_id,),
                    )
                    row = cur.fetchone()
                    if row and row["archived_at"] is not None:
                        conv_repo.update_conversation_status(conversation_id, "summarized")
    except Exception:
        pass  # Non-critical — summary is saved regardless

    # Invalidate cached memory so next message picks up new facts
    try:
        memory_svc = MemoryService()
        memory_svc.invalidate_cache(actor_id)
    except Exception:
        logger.debug("Memory cache invalidation failed for actor=%s", actor_id)

    logger.info(
        "Summarized conv=%s: %d facts, topics=%s",
        conversation_id, len(facts), summary_data.get("topics", []),
    )
    return True


def summarize_idle_conversations() -> int:
    """Background job: find and summarize idle conversations. Returns count processed."""
    settings = get_settings()
    conv_repo = ConversationRepository()
    mem_repo = MemoryRepository()

    idle_minutes = getattr(settings, "memory_idle_minutes", 30)
    min_messages = getattr(settings, "memory_min_messages", 4)

    idle_convs = mem_repo.get_idle_unsummarized(idle_minutes=idle_minutes, min_messages=min_messages)
    if not idle_convs:
        return 0

    logger.info("Found %d idle conversations to summarize", len(idle_convs))
    count = 0
    for conv in idle_convs:
        try:
            ok = summarize_conversation(
                conversation_id=str(conv["id"]),
                actor_id=conv["actor_id"],
                agent_role=conv.get("agent_role", "sales"),
                conv_repo=conv_repo,
                mem_repo=mem_repo,
            )
            if ok:
                count += 1
        except Exception:
            logger.warning("Failed to summarize conv=%s", conv["id"], exc_info=True)

    logger.info("Summarized %d/%d conversations", count, len(idle_convs))
    return count

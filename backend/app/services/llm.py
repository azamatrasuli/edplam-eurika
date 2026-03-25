from __future__ import annotations

import json
import logging
import time
from collections.abc import Generator
from dataclasses import dataclass, field
from typing import Any

import tiktoken
from openai import OpenAI, RateLimitError

from app.agent.prompt import get_system_prompt
from app.config import get_settings
from app.models.chat import ActorContext, ChatMessage

logger = logging.getLogger("llm")

_tiktoken_encoding: tiktoken.Encoding | None = None


def _get_encoding() -> tiktoken.Encoding:
    global _tiktoken_encoding
    if _tiktoken_encoding is None:
        _tiktoken_encoding = tiktoken.encoding_for_model("gpt-4o")
    return _tiktoken_encoding


def _count_tokens(text: str) -> int:
    return len(_get_encoding().encode(text))


@dataclass
class LLMChunk:
    token: str


@dataclass
class ToolCallEvent:
    """Yielded when a tool is executed (informational for the SSE consumer)."""
    name: str
    result: str
    payment_data: dict | None = None


@dataclass
class StatusEvent:
    """Yielded to inform SSE consumer about current processing phase."""
    label: str


@dataclass
class LLMResult:
    text: str
    usage_tokens: int | None
    rag_metadata: dict | None = None


class LLMService:
    MAX_TOOL_ITERATIONS = 5

    def __init__(self) -> None:
        self.settings = get_settings()
        from app.services.openai_client import get_openai_client
        self.client = get_openai_client()

    # ---- history builder --------------------------------------------------

    def _build_history_messages(
        self,
        history: list[ChatMessage],
        system_tokens: int,
    ) -> list[dict[str, str]]:
        """Build history messages within a token budget.

        Walks backward through history, accumulating messages until the token
        budget is exhausted. Returns messages in chronological order.
        """
        budget = getattr(self.settings, "history_max_context_tokens", 100_000)
        available = budget - system_tokens
        if available < 500:
            available = 4000  # safety floor

        result: list[dict[str, str]] = []
        used = 0
        min_messages = 6  # always include at least this many

        for i, msg in enumerate(reversed(history)):
            content = msg.content or ""
            # Enrich assistant messages with tool call summaries from metadata
            if msg.role == "assistant" and getattr(msg, "metadata", None):
                tool_calls = (msg.metadata or {}).get("tool_calls")
                if tool_calls and isinstance(tool_calls, list):
                    tool_lines = []
                    for tc in tool_calls:
                        name = tc.get("name", "")
                        res = tc.get("result", "")
                        if name and res:
                            tool_lines.append(f"{name}: {res[:200]}")
                    if tool_lines:
                        content = content + "\n[Инструменты: " + "; ".join(tool_lines) + "]"

            tokens = _count_tokens(content) + 4  # 4 tokens overhead per message
            if i >= min_messages and used + tokens > available:
                break
            result.append({"role": msg.role, "content": content})
            used += tokens

        result.reverse()
        logger.info("History: %d/%d messages, ~%d tokens", len(result), len(history), used)
        return result

    # ---- context builders -------------------------------------------------

    def _identity_context(self, actor: ActorContext) -> str:
        # Name resolution: auth → profile (display_name/fio) → memory atoms
        name = actor.display_name
        if not name:
            try:
                from app.services.onboarding import OnboardingService
                profile = OnboardingService().check_profile(actor.actor_id)
                if profile:
                    name = getattr(profile, "display_name", None) or getattr(profile, "fio", None)
                    if not name and isinstance(profile, dict):
                        name = profile.get("display_name") or profile.get("fio")
            except Exception:
                pass
        if not name:
            try:
                from app.db.memory_repository import MemoryRepository
                name = MemoryRepository().get_user_name_from_atoms(actor.actor_id)
            except Exception:
                pass
        name = name or "не указано"
        phone = actor.phone or "не указано"
        channel = actor.channel.value
        return (
            "Контекст клиента:\n"
            f"- Канал входа: {channel}\n"
            f"- Имя: {name}\n"
            f"- Телефон: {phone}\n"
            "- Используй этот контекст в ответе, когда это уместно.\n"
            "- Если имя известно — обращайся по имени и НЕ спрашивай его заново."
        )

    def _crm_context(self, crm_data: dict | None) -> str:
        if not crm_data:
            return ""
        parts = ["Данные клиента из CRM:"]
        if crm_data.get("contact_name"):
            parts.append(f"- Имя в CRM: {crm_data['contact_name']}")
        if crm_data.get("contact_id"):
            parts.append(f"- ID контакта: {crm_data['contact_id']}")
        deal = crm_data.get("active_deal")
        if deal:
            parts.append(f"- Активная сделка: {deal.get('name', 'без названия')}")
            if deal.get("product"):
                parts.append(f"- Продукт: {deal['product']}")
            if deal.get("amount"):
                parts.append(f"- Сумма: {deal['amount']} руб.")
        return "\n".join(parts)

    def _kb_fallback(self, tool_calls: list[dict]) -> str | None:
        """If KB search results exist from tool calls, return them as a direct answer."""
        for tc in tool_calls:
            if tc.get("name") == "search_knowledge_base" and tc.get("result"):
                result = tc["result"]
                if "Источник:" in result and "не найдено" not in result.lower():
                    return (
                        "Вот что я нашла в базе знаний:\n\n"
                        + result[:3000]
                        + "\n\nЕсли нужна дополнительная информация — спрашивайте!"
                    )
        return None

    def _fallback_text(self, role: str = "sales") -> str:
        if role == "support":
            return (
                "Секунду, есть техническая пауза с генерацией ответа. "
                "Я уже продолжаю работу. Можете повторить вопрос или уточнить, чем могу помочь."
            )
        return (
            "Секунду, есть техническая пауза с генерацией ответа. "
            "Я уже продолжаю работу. Можете повторить вопрос или уточнить, какой класс вас интересует."
        )

    # ---- main entry point -------------------------------------------------

    def stream_answer(
        self,
        user_text: str,
        actor: ActorContext,
        history: list[ChatMessage],
        crm_context: dict | None = None,
        tool_executor: Any | None = None,
        profile_context: str | None = None,
        memory_context: str | None = None,
        running_summary: str | None = None,
    ) -> Generator[LLMChunk | ToolCallEvent, None, LLMResult]:
        """
        Stream LLM answer with function calling support.

        Yields LLMChunk for text tokens and ToolCallEvent for tool executions.
        Returns LLMResult when complete.
        """
        agent_role = actor.agent_role.value if hasattr(actor.agent_role, "value") else str(actor.agent_role)

        if self.client is None:
            fallback = (
                "Я Эврика. Сейчас OpenAI не подключен в окружении, "
                "поэтому отвечаю в демо-режиме. Напишите OPENAI_API_KEY в backend/.env."
            )
            for ch in fallback:
                yield LLMChunk(token=ch)
            return LLMResult(text=fallback, usage_tokens=None)

        from app.agent.tools import get_tool_definitions

        tool_defs = get_tool_definitions(agent_role)

        # Build system messages
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": get_system_prompt(agent_role)},
            {"role": "system", "content": self._identity_context(actor)},
        ]
        if profile_context:
            messages.append({"role": "system", "content": profile_context})
        if memory_context:
            messages.append({"role": "system", "content": memory_context})
        if running_summary:
            messages.append({"role": "system", "content": f"# Краткое содержание начала этого диалога\n\n{running_summary}"})
        crm_ctx_str = self._crm_context(crm_context)
        if crm_ctx_str:
            messages.append({"role": "system", "content": crm_ctx_str})

        # Count system tokens, then fill history within budget
        system_tokens = sum(_count_tokens(m["content"]) + 4 for m in messages)
        system_tokens += _count_tokens(user_text) + 4  # reserve for current message
        history_msgs = self._build_history_messages(history, system_tokens)
        messages.extend(history_msgs)
        messages.append({"role": "user", "content": user_text})

        all_tool_calls_made: list[dict] = []
        escalation_triggered = False
        rate_limit_retries = 0
        max_rate_limit_retries = 3
        iteration = 0

        while iteration < self.MAX_TOOL_ITERATIONS:
            try:
                logger.info("LLM iteration %d starting (messages=%d, tools=%s)", iteration, len(messages), bool(tool_executor))
                create_kwargs: dict[str, Any] = {
                    "model": self.settings.openai_model,
                    "messages": messages,
                    "stream": True,
                    "temperature": 0.3,
                    "timeout": self.settings.openai_request_timeout_seconds,
                }
                if tool_executor:
                    create_kwargs["tools"] = tool_defs

                from app.logging_config import log_external_call

                with log_external_call("openai", f"chat_completion_iter{iteration}"):
                    stream = self.client.chat.completions.create(**create_kwargs)

                full_text: list[str] = []
                tool_calls_acc: dict[int, dict] = {}
                total_tokens = None

                for chunk in stream:
                    choice = chunk.choices[0] if chunk.choices else None
                    if not choice:
                        usage = getattr(chunk, "usage", None)
                        if usage and getattr(usage, "total_tokens", None) is not None:
                            total_tokens = usage.total_tokens
                        continue

                    delta = choice.delta

                    # Text content
                    if delta and delta.content:
                        full_text.append(delta.content)
                        yield LLMChunk(token=delta.content)

                    # Tool calls (accumulated across stream chunks)
                    if delta and delta.tool_calls:
                        for tc_delta in delta.tool_calls:
                            idx = tc_delta.index
                            if idx not in tool_calls_acc:
                                tool_calls_acc[idx] = {"id": "", "name": "", "arguments": ""}
                            tc = tool_calls_acc[idx]
                            if tc_delta.id:
                                tc["id"] = tc_delta.id
                            if tc_delta.function:
                                if tc_delta.function.name:
                                    tc["name"] = tc_delta.function.name
                                if tc_delta.function.arguments:
                                    tc["arguments"] += tc_delta.function.arguments

                    # Usage info
                    usage = getattr(chunk, "usage", None)
                    if usage and getattr(usage, "total_tokens", None) is not None:
                        total_tokens = usage.total_tokens

                # If we got text and no tool calls — done
                if full_text and not tool_calls_acc:
                    return LLMResult(
                        text="".join(full_text),
                        usage_tokens=total_tokens,
                        rag_metadata={
                            "tool_calls": all_tool_calls_made,
                            "escalation": escalation_triggered,
                        },
                    )

                # If we got tool calls — execute and loop
                if tool_calls_acc and tool_executor:
                    assistant_msg: dict[str, Any] = {
                        "role": "assistant",
                        "content": "".join(full_text) if full_text else None,
                        "tool_calls": [],
                    }
                    for idx in sorted(tool_calls_acc.keys()):
                        tc = tool_calls_acc[idx]
                        assistant_msg["tool_calls"].append({
                            "id": tc["id"],
                            "type": "function",
                            "function": {"name": tc["name"], "arguments": tc["arguments"]},
                        })
                    messages.append(assistant_msg)

                    for idx in sorted(tool_calls_acc.keys()):
                        tc = tool_calls_acc[idx]
                        try:
                            args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                        except json.JSONDecodeError:
                            args = {}

                        result = tool_executor.execute(tc["name"], args)
                        all_tool_calls_made.append({
                            "name": tc["name"],
                            "args": args,
                            "result": result.result[:2000],
                        })

                        yield ToolCallEvent(
                            name=tc["name"],
                            result=result.result,
                            payment_data=result.payment_data,
                        )

                        if result.is_escalation:
                            escalation_triggered = True

                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": result.result,
                        })

                    iteration += 1
                    logger.info("Tool iteration done, moving to iteration %d (messages=%d)", iteration, len(messages))
                    continue  # next iteration — OpenAI will respond with text

                # Edge case: no text and no tool calls
                if not full_text:
                    fallback = self._kb_fallback(all_tool_calls_made) or self._fallback_text(agent_role)
                    for ch in fallback:
                        yield LLMChunk(token=ch)
                    return LLMResult(text=fallback, usage_tokens=total_tokens,
                                     rag_metadata={"tool_calls": all_tool_calls_made, "escalation": escalation_triggered})

                # Text without tool calls (shouldn't reach here, but safety)
                return LLMResult(
                    text="".join(full_text),
                    usage_tokens=total_tokens,
                    rag_metadata={
                        "tool_calls": all_tool_calls_made,
                        "escalation": escalation_triggered,
                    },
                )

            except RateLimitError as e:
                # On quota exhaustion, switch to fallback key and retry
                from app.services.openai_client import is_quota_error, switch_to_fallback, get_openai_client
                if is_quota_error(e):
                    switch_to_fallback()  # switch if not already
                    refreshed = get_openai_client()
                    if refreshed is not self.client:
                        self.client = refreshed
                        continue  # retry same iteration with new key

                rate_limit_retries += 1
                if rate_limit_retries > max_rate_limit_retries:
                    logger.error("Rate limit: max retries (%d) exceeded", max_rate_limit_retries)
                    fallback = self._kb_fallback(all_tool_calls_made) or self._fallback_text(agent_role)
                    for ch in fallback:
                        yield LLMChunk(token=ch)
                    return LLMResult(text=fallback, usage_tokens=None,
                                     rag_metadata={"tool_calls": all_tool_calls_made, "escalation": escalation_triggered})
                retry_after = getattr(e, "retry_after", None)
                if retry_after is None:
                    # Exponential backoff: 5s, 10s, 20s
                    retry_after = min(5 * (2 ** (rate_limit_retries - 1)), 30)
                logger.warning(
                    "Rate limit on iteration %d (retry %d/%d), waiting %.1fs",
                    iteration, rate_limit_retries, max_rate_limit_retries, retry_after,
                )
                time.sleep(min(retry_after, 30))
                continue  # retry same iteration (iteration NOT incremented)

            except Exception:
                logger.exception("LLM streaming error on iteration %d", iteration)
                fallback = self._kb_fallback(all_tool_calls_made) or self._fallback_text(agent_role)
                for ch in fallback:
                    yield LLMChunk(token=ch)
                return LLMResult(text=fallback, usage_tokens=None,
                                 rag_metadata={"tool_calls": all_tool_calls_made, "escalation": escalation_triggered})

        # Max iterations exceeded
        fallback = "Извините, возникла сложность с обработкой запроса. Попробуйте переформулировать вопрос."
        for ch in fallback:
            yield LLMChunk(token=ch)
        return LLMResult(text=fallback, usage_tokens=None,
                         rag_metadata={"tool_calls": all_tool_calls_made, "escalation": escalation_triggered})

    # ---- suggestion chips generation ----------------------------------------

    def generate_suggestions(
        self,
        assistant_text: str,
        user_text: str,
        agent_role: str = "sales",
    ) -> list[dict] | None:
        """Generate 2-3 contextual suggestion chips based on the last exchange."""
        if not self.client:
            return None

        role_hint = "менеджер по продажам" if agent_role == "sales" else "менеджер поддержки"

        try:
            from app.services.openai_client import get_openai_client, is_quota_error, switch_to_fallback
            _sug_kwargs = dict(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            f"Ты помощник {role_hint} в онлайн-школе EdPalm. "
                            "Проанализируй последний обмен репликами и предложи 2-3 кнопки быстрых ответов "
                            "для клиента. Формулируй от первого лица (как если бы клиент нажимал). "
                            "Кнопки должны быть короткими (2-5 слов). "
                            "Верни JSON массив: [{\"label\": \"текст кнопки\", \"value\": \"полное сообщение\"}]. "
                            "label — текст на кнопке, value — полное сообщение которое отправится. "
                            "Если дальнейшие вопросы неуместны (прощание, оплата завершена) — верни пустой массив []."
                        ),
                    },
                    {"role": "user", "content": user_text},
                    {"role": "assistant", "content": assistant_text[:1000]},
                    {"role": "user", "content": "Предложи кнопки быстрых ответов."},
                ],
                temperature=0.3, max_tokens=200, timeout=15,
            )
            try:
                response = self.client.chat.completions.create(**_sug_kwargs)
            except RateLimitError as e:
                if is_quota_error(e):
                    switch_to_fallback()
                    self.client = get_openai_client()
                    response = self.client.chat.completions.create(**_sug_kwargs)
                else:
                    raise

            raw = response.choices[0].message.content.strip()
            # Handle markdown code blocks
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
                raw = raw.strip()

            chips = json.loads(raw)
            if isinstance(chips, list) and len(chips) <= 4:
                return [c for c in chips if isinstance(c, dict) and "label" in c and "value" in c][:3]
            return None
        except Exception:
            logger.info("Suggestion generation failed", exc_info=True)
            return None

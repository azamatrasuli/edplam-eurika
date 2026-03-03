from __future__ import annotations

import json
import logging
from collections.abc import Generator
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI

from app.agent.prompt import SYSTEM_PROMPT
from app.config import get_settings
from app.models.chat import ActorContext, ChatMessage

logger = logging.getLogger("llm")


@dataclass
class LLMChunk:
    token: str


@dataclass
class ToolCallEvent:
    """Yielded when a tool is executed (informational for the SSE consumer)."""
    name: str
    result: str


@dataclass
class LLMResult:
    text: str
    usage_tokens: int | None
    rag_metadata: dict | None = None


class LLMService:
    MAX_TOOL_ITERATIONS = 5

    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = OpenAI(api_key=self.settings.openai_api_key) if self.settings.openai_api_key else None

    # ---- context builders -------------------------------------------------

    def _identity_context(self, actor: ActorContext) -> str:
        name = actor.display_name or "не указано"
        phone = actor.phone or "не указано"
        channel = actor.channel.value
        return (
            "Контекст клиента:\n"
            f"- Канал входа: {channel}\n"
            f"- Имя: {name}\n"
            f"- Телефон: {phone}\n"
            "- Используй этот контекст в ответе, когда это уместно."
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

    def _fallback_text(self) -> str:
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
    ) -> Generator[LLMChunk | ToolCallEvent, None, LLMResult]:
        """
        Stream LLM answer with function calling support.

        Yields LLMChunk for text tokens and ToolCallEvent for tool executions.
        Returns LLMResult when complete.
        """
        if self.client is None:
            fallback = (
                "Я Эврика. Сейчас OpenAI не подключен в окружении, "
                "поэтому отвечаю в демо-режиме. Напишите OPENAI_API_KEY в backend/.env."
            )
            for ch in fallback:
                yield LLMChunk(token=ch)
            return LLMResult(text=fallback, usage_tokens=None)

        from app.agent.tools import TOOL_DEFINITIONS

        # Build initial messages
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": self._identity_context(actor)},
        ]
        crm_ctx_str = self._crm_context(crm_context)
        if crm_ctx_str:
            messages.append({"role": "system", "content": crm_ctx_str})

        for item in history[-12:]:
            messages.append({"role": item.role, "content": item.content})
        messages.append({"role": "user", "content": user_text})

        all_tool_calls_made: list[dict] = []
        escalation_triggered = False

        for iteration in range(self.MAX_TOOL_ITERATIONS):
            try:
                create_kwargs: dict[str, Any] = {
                    "model": self.settings.openai_model,
                    "messages": messages,
                    "stream": True,
                    "temperature": 0.3,
                    "timeout": self.settings.openai_request_timeout_seconds,
                }
                if tool_executor:
                    create_kwargs["tools"] = TOOL_DEFINITIONS

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
                            "result": result.result[:500],
                        })

                        yield ToolCallEvent(name=tc["name"], result=result.result)

                        if result.is_escalation:
                            escalation_triggered = True

                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc["id"],
                            "content": result.result,
                        })

                    continue  # next iteration — OpenAI will respond with text

                # Edge case: no text and no tool calls
                if not full_text:
                    fallback = self._fallback_text()
                    for ch in fallback:
                        yield LLMChunk(token=ch)
                    return LLMResult(text=fallback, usage_tokens=total_tokens)

                # Text without tool calls (shouldn't reach here, but safety)
                return LLMResult(
                    text="".join(full_text),
                    usage_tokens=total_tokens,
                    rag_metadata={
                        "tool_calls": all_tool_calls_made,
                        "escalation": escalation_triggered,
                    },
                )

            except Exception:
                logger.exception("LLM streaming error on iteration %d", iteration)
                fallback = self._fallback_text()
                for ch in fallback:
                    yield LLMChunk(token=ch)
                return LLMResult(text=fallback, usage_tokens=None)

        # Max iterations exceeded
        fallback = "Извините, возникла сложность с обработкой запроса. Попробуйте переформулировать вопрос."
        for ch in fallback:
            yield LLMChunk(token=ch)
        return LLMResult(text=fallback, usage_tokens=None)

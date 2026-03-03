"""OpenAI function calling tool definitions and execution engine."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from app.config import get_settings
from app.integrations.amocrm import AmoCRMClient
from app.rag.search import search_knowledge_base

logger = logging.getLogger("agent.tools")


# ---------------------------------------------------------------------------
# Tool definitions (OpenAI JSON Schema format)
# ---------------------------------------------------------------------------

TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": (
                "Поиск информации о продуктах, ценах, программах EdPalm в базе знаний. "
                "Используй КАЖДЫЙ РАЗ, когда клиент задаёт вопрос о продуктах, ценах, "
                "программах, расписании или условиях обучения."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Поисковый запрос на русском языке. Формулируй максимально конкретно.",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_amocrm_contact",
            "description": (
                "Найти клиента в CRM по номеру телефона или Telegram ID. "
                "Используй для проверки, является ли клиент новым или существующим."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "phone": {"type": "string", "description": "Номер телефона клиента (например, +79991234567)"},
                    "telegram_id": {"type": "string", "description": "Telegram ID клиента"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_amocrm_deal",
            "description": (
                "Получить активную сделку клиента из CRM. "
                "Используй, когда нужно узнать текущий статус сделки или продукт клиента."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "contact_id": {"type": "integer", "description": "ID контакта в amoCRM"},
                },
                "required": ["contact_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_amocrm_lead",
            "description": (
                "Создать новую сделку в CRM для клиента. "
                "Вызывай ТОЛЬКО после квалификации клиента и подбора продукта. "
                "Не вызывай при первом сообщении."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Имя клиента"},
                    "phone": {"type": "string", "description": "Номер телефона"},
                    "telegram_id": {"type": "string", "description": "Telegram ID (если есть)"},
                    "product": {"type": "string", "description": "Название продукта (например, 'Экстернат Классный 5 класс')"},
                    "amount": {"type": "integer", "description": "Сумма в рублях"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_deal_stage",
            "description": "Обновить этап сделки в CRM. Используй для фиксации прогресса в воронке продаж.",
            "parameters": {
                "type": "object",
                "properties": {
                    "lead_id": {"type": "integer", "description": "ID сделки в amoCRM"},
                    "status_id": {"type": "integer", "description": "ID нового этапа воронки"},
                    "product": {"type": "string", "description": "Название продукта (если нужно обновить)"},
                    "amount": {"type": "integer", "description": "Сумма (если нужно обновить)"},
                },
                "required": ["lead_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_to_manager",
            "description": (
                "Передать диалог живому менеджеру. Вызывай ОБЯЗАТЕЛЬНО если: "
                "клиент выражает недовольство, просит человека, вопрос вне базы знаний, "
                "или запрашивает скидку которой нет."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "Причина эскалации (кратко, на русском)"},
                },
                "required": ["reason"],
            },
        },
    },
]


# ---------------------------------------------------------------------------
# Tool result
# ---------------------------------------------------------------------------

@dataclass
class ToolResult:
    name: str
    result: str
    is_escalation: bool = False
    escalation_reason: str | None = None


# ---------------------------------------------------------------------------
# Tool executor
# ---------------------------------------------------------------------------

class ToolExecutor:
    """Executes tools called by OpenAI function calling. Always returns string results."""

    def __init__(
        self,
        amocrm_client: AmoCRMClient | None = None,
        actor_id: str | None = None,
        conversation_id: str | None = None,
    ) -> None:
        self.crm = amocrm_client or AmoCRMClient()
        self.actor_id = actor_id
        self.conversation_id = conversation_id

    def execute(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        logger.info("Executing tool: %s args=%s", tool_name, arguments)
        try:
            handler = getattr(self, f"_tool_{tool_name}", None)
            if handler is None:
                return ToolResult(name=tool_name, result=f"Unknown tool: {tool_name}")
            return handler(**arguments)
        except Exception as e:
            logger.exception("Tool execution error: %s", tool_name)
            return ToolResult(name=tool_name, result=f"Ошибка при выполнении: {e}")

    # ---- tool implementations ---------------------------------------------

    def _tool_search_knowledge_base(self, query: str) -> ToolResult:
        chunks = search_knowledge_base(query)
        if not chunks:
            return ToolResult(
                name="search_knowledge_base",
                result="В базе знаний не найдено релевантной информации по запросу: " + query,
            )
        parts = []
        for i, chunk in enumerate(chunks, 1):
            source_label = chunk.source.replace(".md", "") if chunk.source else "unknown"
            parts.append(
                f"[{i}] Источник: {source_label} | Раздел: {chunk.section} | "
                f"Релевантность: {chunk.similarity}\n{chunk.content}"
            )
        result = "\n---\n".join(parts)
        # Warn LLM if all chunks have low relevance
        if all(c.similarity < 0.5 for c in chunks):
            result = (
                "⚠ Все найденные фрагменты имеют низкую релевантность (< 0.5). "
                "Информация может быть неточной. Если не уверена в ответе — "
                "предложи подключить менеджера.\n\n" + result
            )
        return ToolResult(name="search_knowledge_base", result=result)

    def _tool_get_amocrm_contact(
        self, phone: str | None = None, telegram_id: str | None = None,
    ) -> ToolResult:
        contact = None
        if telegram_id:
            contact = self.crm.find_contact_by_telegram_id(telegram_id)
        if not contact and phone:
            contact = self.crm.find_contact_by_phone(phone)
        if contact:
            return ToolResult(
                name="get_amocrm_contact",
                result=json.dumps({
                    "found": True,
                    "contact_id": contact.id,
                    "name": contact.name,
                    "phone": contact.phone,
                    "telegram_id": contact.telegram_id,
                }, ensure_ascii=False),
            )
        return ToolResult(name="get_amocrm_contact", result='{"found": false}')

    def _tool_get_amocrm_deal(self, contact_id: int) -> ToolResult:
        lead = self.crm.find_active_lead(contact_id)
        if lead:
            return ToolResult(
                name="get_amocrm_deal",
                result=json.dumps({
                    "found": True,
                    "lead_id": lead.id,
                    "name": lead.name,
                    "pipeline_id": lead.pipeline_id,
                    "status_id": lead.status_id,
                    "product": lead.product_name,
                    "amount": lead.amount,
                    "price": lead.price,
                }, ensure_ascii=False),
            )
        return ToolResult(name="get_amocrm_deal", result='{"found": false}')

    def _tool_create_amocrm_lead(
        self,
        name: str,
        phone: str | None = None,
        telegram_id: str | None = None,
        product: str | None = None,
        amount: int | None = None,
    ) -> ToolResult:
        contact, is_new = self.crm.find_or_create_contact(
            phone=phone, name=name, telegram_id=telegram_id,
        )
        if not contact:
            return ToolResult(
                name="create_amocrm_lead",
                result='{"success": false, "error": "CRM unavailable"}',
            )

        lead_name = f"AI-Агент: {product or 'Консультация'} — {name}"
        lead = self.crm.create_lead(
            name=lead_name, contact_id=contact.id, product=product, amount=amount,
        )
        if not lead:
            return ToolResult(
                name="create_amocrm_lead",
                result='{"success": false, "error": "Lead creation failed"}',
            )

        return ToolResult(
            name="create_amocrm_lead",
            result=json.dumps({
                "success": True,
                "lead_id": lead.id,
                "contact_id": contact.id,
                "is_new_contact": is_new,
            }, ensure_ascii=False),
        )

    def _tool_update_deal_stage(
        self,
        lead_id: int,
        status_id: int | None = None,
        product: str | None = None,
        amount: int | None = None,
    ) -> ToolResult:
        lead = self.crm.update_lead(
            lead_id=lead_id, status_id=status_id, product=product, amount=amount,
        )
        if lead:
            return ToolResult(
                name="update_deal_stage",
                result=json.dumps({"success": True, "lead_id": lead.id}),
            )
        return ToolResult(
            name="update_deal_stage",
            result='{"success": false, "error": "Update failed"}',
        )

    def _tool_escalate_to_manager(self, reason: str) -> ToolResult:
        return ToolResult(
            name="escalate_to_manager",
            result=json.dumps({
                "escalated": True,
                "reason": reason,
                "message": "Диалог передан менеджеру. Он свяжется с клиентом в ближайшее время.",
            }, ensure_ascii=False),
            is_escalation=True,
            escalation_reason=reason,
        )

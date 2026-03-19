"""OpenAI function calling tool definitions and execution engine."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from app.config import get_settings
from app.db.events import EventTracker
from app.db.repository import ConversationRepository
from app.integrations.amocrm import AmoCRMClient
from app.integrations.dms import get_dms_service, _normalize_phone, _format_phone_dms
from app.rag.search import search_knowledge_base

logger = logging.getLogger("agent.tools")


# ---------------------------------------------------------------------------
# Tool definitions (OpenAI JSON Schema format)
# ---------------------------------------------------------------------------

SALES_TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": (
                "Поиск информации о продуктах, ценах, программах, компании EdPalm в базе знаний. "
                "Используй КАЖДЫЙ РАЗ, когда клиент задаёт вопрос о продуктах, ценах, "
                "программах, расписании, условиях обучения, аттестации, документах, "
                "компании (основатель, рейтинги, награды, регионы, количество учеников), "
                "возврате, пробном периоде, рассрочке, мероприятиях или любых фактах об EdPalm."
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
            "name": "get_client_profile",
            "description": (
                "Получить профиль клиента из системы: ФИО, тариф, класс ученика, статус зачисления, "
                "школа прикрепления. Используй когда клиент называет телефон или нужно проверить его данные."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "phone": {"type": "string", "description": "Номер телефона клиента"},
                },
                "required": ["phone"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_payment_link",
            "description": (
                "Сгенерировать ссылку на оплату обучения. "
                "Вызывай ТОЛЬКО когда клиент подтвердил выбор продукта и готов оплатить. "
                "НЕ вызывай для тарифа Персональный — веди к консультации с менеджером."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "product_name": {
                        "type": "string",
                        "description": "Название продукта (например, 'Экстернат Классный 5 класс')",
                    },
                    "grade": {
                        "type": "integer",
                        "description": "Класс ученика (1-11)",
                    },
                    "student_name": {
                        "type": "string",
                        "description": "ФИО ученика (если известно)",
                    },
                    "payer_phone": {
                        "type": "string",
                        "description": "Телефон плательщика",
                    },
                },
                "required": ["product_name", "grade", "payer_phone"],
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

# Backward-compatible alias
TOOL_DEFINITIONS = SALES_TOOL_DEFINITIONS

SUPPORT_TOOL_DEFINITIONS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": (
                "Поиск информации в базе знаний службы поддержки EdPalm. "
                "Используй КАЖДЫЙ РАЗ, когда клиент задаёт вопрос о платформе, "
                "документах, оплате, расписании, аттестации или учебном процессе."
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
            "name": "get_client_profile",
            "description": (
                "Получить профиль клиента из системы: ФИО, тариф, класс ученика, статус зачисления, "
                "школа прикрепления. Используй когда клиент называет телефон или спрашивает про свой тариф/статус."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "phone": {"type": "string", "description": "Номер телефона клиента"},
                },
                "required": ["phone"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_amocrm_ticket",
            "description": (
                "Создать обращение (тикет) клиента в CRM. Используй для заявок, "
                "которые требуют действий от команды EdPalm: запрос справки, "
                "проблема с доступом, вопрос по оплате и т.д."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "issue": {
                        "type": "string",
                        "description": "Краткое описание обращения клиента",
                    },
                    "name": {"type": "string", "description": "Имя клиента (если известно)"},
                    "phone": {"type": "string", "description": "Номер телефона (если известен)"},
                    "telegram_id": {"type": "string", "description": "Telegram ID (если известен)"},
                },
                "required": ["issue"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_to_manager",
            "description": (
                "Передать диалог специалисту поддержки. Вызывай ОБЯЗАТЕЛЬНО если: "
                "клиент выражает недовольство, просит человека, вопрос вне базы знаний, "
                "или касается возвратов и юридических вопросов."
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


def get_tool_definitions(role: str) -> list[dict]:
    """Return tool definitions for the given agent role."""
    if role == "support":
        return SUPPORT_TOOL_DEFINITIONS
    return SALES_TOOL_DEFINITIONS


# ---------------------------------------------------------------------------
# Tool result
# ---------------------------------------------------------------------------

@dataclass
class ToolResult:
    name: str
    result: str
    is_escalation: bool = False
    escalation_reason: str | None = None
    payment_data: dict | None = None


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
        agent_role: str = "sales",
        repo: ConversationRepository | None = None,
    ) -> None:
        self.crm = amocrm_client or AmoCRMClient()
        self.dms = get_dms_service()
        self.actor_id = actor_id
        self.conversation_id = conversation_id
        self.agent_role = agent_role
        self.repo = repo or ConversationRepository()
        self.events = EventTracker()

    def execute(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        logger.info("Executing tool: %s args=%s", tool_name, arguments)
        try:
            handler = getattr(self, f"_tool_{tool_name}", None)
            if handler is None:
                return ToolResult(name=tool_name, result=f"Unknown tool: {tool_name}")
            result = handler(**arguments)
            # Track tool call event
            self.events.track_tool_call(
                self.conversation_id,
                self.actor_id or "",
                tool_name,
                arguments,
                result.result[:200],
                not result.result.startswith("Ошибка"),
                agent_role=self.agent_role,
            )
            return result
        except Exception as e:
            logger.exception("Tool execution error: %s", tool_name)
            self.events.track_tool_call(
                self.conversation_id, self.actor_id or "", tool_name,
                arguments, str(e)[:200], False, agent_role=self.agent_role,
            )
            return ToolResult(name=tool_name, result=f"Ошибка при выполнении: {e}")

    # ---- tool implementations ---------------------------------------------

    def _tool_search_knowledge_base(self, query: str) -> ToolResult:
        chunks = search_knowledge_base(query, namespace=self.agent_role)
        if not chunks:
            self.events.track_rag_miss(
                self.conversation_id, self.actor_id or "", query, self.agent_role,
            )
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
        # Warn LLM if all chunks have very low relevance
        if all(c.similarity < 0.35 for c in chunks):
            result = (
                "⚠ Релевантность найденных фрагментов низкая. "
                "Используй информацию с осторожностью, но всё равно ответь клиенту "
                "на основе найденного. НЕ эскалируй только из-за низкой релевантности.\n\n" + result
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

        # Save CRM mappings for traceability
        if self.actor_id:
            self.repo.save_contact_mapping(self.actor_id, contact.id, contact.name)
        if self.conversation_id:
            self.repo.save_deal_mapping(
                self.conversation_id, lead.id, contact.id,
                pipeline_id=lead.pipeline_id, status_id=lead.status_id,
            )
        logger.info(
            "Created lead %d for contact %d (actor=%s, conv=%s)",
            lead.id, contact.id, self.actor_id, self.conversation_id,
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

    def _tool_get_client_profile(self, phone: str) -> ToolResult:
        """Look up client profile in DMS by phone number and auto-save to profile store."""
        result = self.dms.search_contact_by_phone(phone)
        if not result:
            return ToolResult(
                name="get_client_profile",
                result='{"found": false, "message": "Клиент не найден по указанному телефону"}',
            )
        contact = result.contact
        students_data = [
            {
                "fio": s.fio,
                "grade": s.grade,
                "product": s.product_name,
                "state": s.state,
                "school": s.enrollment_school,
                "is_active": s.is_active,
            }
            for s in result.students
        ]
        profile = {
            "found": True,
            "contact": {
                "name": f"{contact.surname} {contact.name} {contact.patronymic or ''}".strip(),
                "phone": contact.phone,
                "email": contact.email,
            },
            "students": students_data,
        }

        # Write-back: persist discovered profile for future sessions
        if self.actor_id:
            try:
                children = [{"fio": s.fio, "grade": s.grade} for s in result.students]
                full_name = f"{contact.surname} {contact.name} {contact.patronymic or ''}".strip()
                first_grade = result.students[0].grade if result.students else None
                dms_data = {
                    "contact_id": contact.contact_id,
                    "students": [
                        {
                            "student_id": s.student_id,
                            "fio": s.fio,
                            "grade": s.grade,
                            "product_name": s.product_name,
                            "moodle_id": s.moodle_id,
                        }
                        for s in result.students
                    ],
                }
                self.repo.save_user_profile(
                    actor_id=self.actor_id,
                    client_type="existing",
                    user_role="parent",
                    phone=_normalize_phone(phone),
                    phone_raw=phone,
                    fio=full_name,
                    grade=first_grade,
                    children=children,
                    dms_verified=True,
                    dms_contact_id=contact.contact_id,
                    dms_data=dms_data,
                    verification_status="found",
                )
                logger.info(
                    "Write-back: saved DMS profile for actor=%s phone=%s",
                    self.actor_id, phone,
                )
            except Exception:
                logger.warning("Write-back failed for actor=%s", self.actor_id, exc_info=True)

        return ToolResult(
            name="get_client_profile",
            result=json.dumps(profile, ensure_ascii=False),
        )

    def _tool_generate_payment_link(
        self,
        product_name: str,
        grade: int,
        payer_phone: str,
        student_name: str | None = None,
    ) -> ToolResult:
        """Generate a payment link via DMS: product lookup → order → link."""
        from app.services.payment import PaymentService

        payment_svc = PaymentService(dms=self.dms, repo=self.repo, crm=self.crm)
        result = payment_svc.create_payment(
            actor_id=self.actor_id or "",
            conversation_id=self.conversation_id or "",
            product_name=product_name,
            grade=grade,
            payer_phone=payer_phone,
            student_name=student_name,
        )

        if result.get("success"):
            payment_data = {
                "product_name": result["product_name"],
                "amount_rub": result["amount_rub"],
                "payment_url": result["payment_url"],
                "order_uuid": result["order_uuid"],
                "grade": result.get("grade"),
            }
            return ToolResult(
                name="generate_payment_link",
                result=json.dumps({
                    "success": True,
                    "product_name": result["product_name"],
                    "amount_rub": result["amount_rub"],
                    "message": "Ссылка на оплату сгенерирована. Клиент видит карточку оплаты.",
                }, ensure_ascii=False),
                payment_data=payment_data,
            )
        else:
            return ToolResult(
                name="generate_payment_link",
                result=json.dumps({
                    "success": False,
                    "error": result.get("error", "Неизвестная ошибка"),
                }, ensure_ascii=False),
            )

    def _tool_create_amocrm_ticket(
        self,
        issue: str,
        name: str | None = None,
        phone: str | None = None,
        telegram_id: str | None = None,
    ) -> ToolResult:
        settings = get_settings()
        contact, is_new = self.crm.find_or_create_contact(
            phone=phone, name=name or "Клиент поддержки", telegram_id=telegram_id,
        )
        if not contact:
            return ToolResult(
                name="create_amocrm_ticket",
                result='{"success": false, "error": "CRM unavailable"}',
            )

        lead_name = f"Поддержка: {issue[:80]}"
        lead = self.crm.create_lead(
            name=lead_name,
            contact_id=contact.id,
            pipeline_id=settings.amocrm_service_pipeline_id,
        )
        if not lead:
            return ToolResult(
                name="create_amocrm_ticket",
                result='{"success": false, "error": "Ticket creation failed"}',
            )

        # Save CRM mappings for traceability
        if self.actor_id:
            self.repo.save_contact_mapping(self.actor_id, contact.id, contact.name)
        if self.conversation_id:
            self.repo.save_deal_mapping(
                self.conversation_id, lead.id, contact.id,
                pipeline_id=settings.amocrm_service_pipeline_id,
            )
        logger.info(
            "Created support ticket %d for contact %d (actor=%s, conv=%s)",
            lead.id, contact.id, self.actor_id, self.conversation_id,
        )

        return ToolResult(
            name="create_amocrm_ticket",
            result=json.dumps({
                "success": True,
                "ticket_id": lead.id,
                "contact_id": contact.id,
                "issue": issue,
            }, ensure_ascii=False),
        )

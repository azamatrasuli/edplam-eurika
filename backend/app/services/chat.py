from __future__ import annotations

import logging
from dataclasses import dataclass

from app.agent.prompt import PROMPT_VERSION
from app.db.repository import ConversationRepository, StoredConversation
from app.integrations.amocrm import AmoCRMClient
from app.models.chat import ActorContext, Channel, ChatMessage
from app.services.llm import LLMService

logger = logging.getLogger("chat")


@dataclass
class StreamContext:
    conversation: StoredConversation
    actor: ActorContext
    history: list[ChatMessage]


class ChatService:
    def __init__(self) -> None:
        self.repo = ConversationRepository()
        self.llm = LLMService()
        self.crm = AmoCRMClient()

    def ensure_conversation(self, actor: ActorContext, conversation_id: str | None) -> StreamContext:
        conv = self.repo.start_or_resume_conversation(actor, conversation_id)
        history = self.repo.get_messages(conv.id, limit=50)
        return StreamContext(conversation=conv, actor=actor, history=history)

    def generate_greeting(self, actor: ActorContext, conversation_id: str) -> str:
        """Generate a personalized greeting and save it as the first assistant message."""
        name = actor.display_name.strip() if actor.display_name else None
        if name:
            greeting = (
                f"Здравствуйте, {name}! Я Эврика, виртуальный менеджер EdPalm. "
                "Помогу подобрать программу обучения и отвечу на ваши вопросы. "
                "Расскажите, что вас интересует?"
            )
        else:
            greeting = (
                "Здравствуйте! Я Эврика, виртуальный менеджер EdPalm. "
                "Помогу подобрать программу обучения и отвечу на ваши вопросы. "
                "Расскажите, что вас интересует?"
            )
        self.save_assistant_message(conversation_id, greeting, usage_tokens=None)
        return greeting

    def resolve_crm_context(self, actor: ActorContext) -> dict | None:
        """Look up actor in amoCRM. Returns CRM context dict or None."""
        # Check local mapping first
        contact_id = self.repo.get_contact_mapping(actor.actor_id)
        contact_name = None

        if not contact_id:
            # Try amoCRM lookup by channel-specific identifier
            contact = None
            if actor.channel == Channel.telegram:
                tg_id = actor.actor_id.replace("telegram:", "")
                contact = self.crm.find_contact_by_telegram_id(tg_id)
            if not contact and actor.phone:
                contact = self.crm.find_contact_by_phone(actor.phone)

            if contact:
                contact_id = contact.id
                contact_name = contact.name
                self.repo.save_contact_mapping(actor.actor_id, contact.id, contact.name)
            else:
                return None

        # Found contact — check for active deal
        lead = self.crm.find_active_lead(contact_id)
        return {
            "contact_id": contact_id,
            "contact_name": contact_name,
            "active_deal": {
                "lead_id": lead.id,
                "name": lead.name,
                "product": lead.product_name,
                "amount": lead.amount,
                "status_id": lead.status_id,
            } if lead else None,
        }

    def save_user_message(self, conversation_id: str, text: str) -> None:
        self.repo.save_message(
            conversation_id=conversation_id,
            role="user",
            content=text,
            metadata={"prompt_version": PROMPT_VERSION},
        )

    def save_assistant_message(
        self,
        conversation_id: str,
        text: str,
        usage_tokens: int | None,
        rag_metadata: dict | None = None,
    ) -> None:
        meta: dict = {"prompt_version": PROMPT_VERSION}
        if rag_metadata:
            meta.update(rag_metadata)
        self.repo.save_message(
            conversation_id=conversation_id,
            role="assistant",
            content=text,
            model=self.llm.settings.openai_model,
            token_usage=usage_tokens,
            metadata=meta,
        )

    def stream_answer(
        self,
        user_text: str,
        actor: ActorContext,
        history: list[ChatMessage],
        conversation_id: str | None = None,
        crm_context: dict | None = None,
    ):
        from app.agent.tools import ToolExecutor

        tool_executor = ToolExecutor(
            amocrm_client=self.crm,
            actor_id=actor.actor_id,
            conversation_id=conversation_id,
        )
        return self.llm.stream_answer(
            user_text=user_text,
            actor=actor,
            history=history,
            crm_context=crm_context,
            tool_executor=tool_executor,
        )

    def get_messages(self, conversation_id: str) -> list[ChatMessage]:
        return self.repo.get_messages(conversation_id)

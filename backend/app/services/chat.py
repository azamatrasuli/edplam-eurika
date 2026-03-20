from __future__ import annotations

import logging
from dataclasses import dataclass

from app.agent.prompt import PROMPT_VERSION
from app.config import get_settings
from app.db.repository import ConversationRepository, StoredConversation
from app.integrations.amocrm import AmoCRMClient
from app.models.chat import ActorContext, AgentRole, Channel, ChatMessage
from app.services.llm import LLMService
from app.services.memory import MemoryService
from app.services.onboarding import OnboardingService

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
        self.onboarding = OnboardingService()
        self.memory = MemoryService()

    def ensure_conversation(
        self, actor: ActorContext, conversation_id: str | None, *, force_new: bool = False,
    ) -> StreamContext:
        conv = self.repo.start_or_resume_conversation(actor, conversation_id, force_new=force_new)
        history = self.repo.get_messages(conv.id, limit=50)

        # On new conversation start, trigger background summarization of past idle conversations
        if force_new or not history:
            self._trigger_user_summarization(actor.actor_id)

        return StreamContext(conversation=conv, actor=actor, history=history)

    def _trigger_user_summarization(self, actor_id: str) -> None:
        """Summarize past idle conversations for this user in background thread."""
        import threading

        def _run():
            try:
                from app.db.memory_repository import MemoryRepository
                from app.services.summarizer import summarize_conversation

                mem_repo = MemoryRepository()
                user_convs = mem_repo.get_user_unsummarized(actor_id, idle_minutes=2, min_messages=3)
                if not user_convs:
                    return
                logger.info("Triggered memory backfill for %s: %d conversations", actor_id, len(user_convs))
                for conv in user_convs:
                    summarize_conversation(
                        conversation_id=str(conv["id"]),
                        actor_id=conv["actor_id"],
                        agent_role=conv.get("agent_role", "sales"),
                        conv_repo=self.repo,
                        mem_repo=mem_repo,
                    )
            except Exception:
                logger.warning("Background summarization failed for %s", actor_id, exc_info=True)

        threading.Thread(target=_run, daemon=True).start()

    def generate_greeting(self, actor: ActorContext, conversation_id: str) -> str:
        """Generate a personalized greeting based on channel, time, and profile."""
        import datetime as _dt

        name = actor.display_name.strip() if actor.display_name else None
        is_support = actor.agent_role == AgentRole.support

        # Time of day (Moscow UTC+3)
        moscow_hour = (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=3)).hour
        if 6 <= moscow_hour < 12:
            hi = "Доброе утро"
        elif 12 <= moscow_hour < 18:
            hi = "Добрый день"
        else:
            hi = "Добрый вечер"

        # Check saved profile for richer context
        profile = self.onboarding.check_profile(actor.actor_id)
        child_snippet = ""
        if profile and profile.dms_verified and profile.children:
            first_child = profile.children[0]
            fio_parts = (first_child.get("fio") or "").split()
            child_name = fio_parts[0] if fio_parts else None
            child_grade = first_child.get("grade")
            if child_name and child_grade:
                child_snippet = f" Вижу, {child_name} в {child_grade} классе."

        # --- Build greeting by channel × role ---
        if is_support:
            if name and child_snippet:
                greeting = f"{hi}, {name}!{child_snippet} Чем могу помочь?"
            elif name:
                greeting = (
                    f"{hi}, {name}! Я Эврика — помогу с вопросами "
                    "по платформе, документам и оплате. Что случилось?"
                )
            else:
                greeting = (
                    f"{hi}! Я Эврика — помогу с вопросами "
                    "по платформе, документам и оплате. Чем могу помочь?"
                )
        elif actor.channel == Channel.telegram:
            if name:
                greeting = (
                    f"Привет, {name}! Я Эврика из EdPalm — "
                    "помогу разобраться в программах обучения. "
                    "О чём хотите узнать?"
                )
            else:
                greeting = (
                    "Привет! Я Эврика из EdPalm — "
                    "помогу разобраться в программах обучения. "
                    "О чём хотите узнать?"
                )
        elif actor.channel == Channel.external:
            greeting = (
                f"{hi}! Я Эврика из EdPalm. "
                "Помогу подобрать программу и отвечу на вопросы. "
                "Что вас интересует?"
            )
        else:
            # Portal
            if name and child_snippet:
                greeting = f"{hi}, {name}!{child_snippet} Чем могу помочь?"
            elif name:
                greeting = (
                    f"{hi}, {name}! Я Эврика — помогу подобрать "
                    "программу обучения. Что вас интересует?"
                )
            else:
                greeting = (
                    f"{hi}! Я Эврика — помогу подобрать "
                    "программу обучения. Что вас интересует?"
                )

        self.save_assistant_message(conversation_id, greeting, usage_tokens=None)
        return greeting

    def resolve_crm_context(self, actor: ActorContext) -> dict | None:
        """Look up actor in amoCRM. Returns CRM context dict or None.

        Side-effect: if a CRM contact has a phone and no DMS profile exists
        for this actor, auto-resolve via DMS and persist for future sessions.
        """
        # Check local mapping first
        contact_id = self.repo.get_contact_mapping(actor.actor_id)
        contact_name = None
        contact_phone = None

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
                contact_phone = contact.phone
                self.repo.save_contact_mapping(actor.actor_id, contact.id, contact.name)
            else:
                return None
        else:
            # We have a saved mapping but may not have the phone — try CRM for it
            contact_phone = actor.phone

        # Auto-resolve DMS profile if CRM contact has phone and no profile yet
        resolved_phone = contact_phone or actor.phone
        if resolved_phone and actor.actor_id:
            try:
                existing_profile = self.onboarding.check_profile(actor.actor_id)
                if not existing_profile:
                    self.onboarding.save_profile_from_phone(actor.actor_id, resolved_phone)
            except Exception:
                logger.info("Auto DMS resolve failed for %s", actor.actor_id, exc_info=True)

        # Found contact — check for active deal
        pipeline_id = None
        if actor.agent_role == AgentRole.support:
            pipeline_id = get_settings().amocrm_service_pipeline_id
        lead = self.crm.find_active_lead(contact_id, pipeline_id=pipeline_id)
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
        # Update message_count, last_user_message, and auto-title
        self.repo.update_message_stats(conversation_id, text)

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

        agent_role = actor.agent_role.value if hasattr(actor.agent_role, "value") else str(actor.agent_role)
        tool_executor = ToolExecutor(
            amocrm_client=self.crm,
            actor_id=actor.actor_id,
            conversation_id=conversation_id,
            agent_role=agent_role,
            repo=self.repo,
        )

        # Load onboarding profile context for LLM
        profile_context = self.onboarding.get_profile_context_for_llm(actor.actor_id)

        # Check for renewal scenario context
        if conversation_id:
            conv_meta = self.repo.get_conversation_metadata(conversation_id)
            if conv_meta and conv_meta.get("scenario_type") == "renewal":
                renewal_ctx = (
                    f"Сценарий: пролонгация\n"
                    f"Ученик: {conv_meta.get('student_name', '—')}\n"
                    f"Текущий продукт: {conv_meta.get('current_product', '—')}\n"
                    f"Класс: {conv_meta.get('grade', '—')}"
                )
                profile_context = (profile_context + "\n\n" + renewal_ctx) if profile_context else renewal_ctx

        # Load memory context from past conversations
        memory_context = None
        try:
            memory_context = self.memory.get_memory_context(
                actor_id=actor.actor_id,
                user_text=user_text,
                agent_role=agent_role,
            )
        except Exception:
            logger.warning("Memory retrieval failed for %s", actor.actor_id, exc_info=True)

        return self.llm.stream_answer(
            user_text=user_text,
            actor=actor,
            history=history,
            crm_context=crm_context,
            tool_executor=tool_executor,
            profile_context=profile_context or None,
            memory_context=memory_context,
        )

    def get_messages(self, conversation_id: str) -> list[ChatMessage]:
        return self.repo.get_messages(conversation_id)

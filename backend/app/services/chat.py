from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from openai import OpenAI

from app.agent.prompt import PROMPT_VERSION
from app.config import get_settings
from app.db.repository import ConversationRepository, StoredConversation
from app.integrations.amocrm import AmoCRMClient
from app.models.chat import ActorContext, AgentRole, Channel, ChatMessage, ClientType
from app.services.llm import LLMService, StatusEvent
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

        # On new conversation start, trigger background summarization of past conversations
        if force_new or not history:
            self._trigger_user_summarization(actor.actor_id, exclude_conversation_id=conv.id)

        return StreamContext(conversation=conv, actor=actor, history=history)

    def _trigger_user_summarization(self, actor_id: str, exclude_conversation_id: str | None = None) -> None:
        """Summarize past conversations for this user in background thread."""
        import threading

        def _run():
            try:
                from app.db.memory_repository import MemoryRepository
                from app.services.summarizer import summarize_conversation

                mem_repo = MemoryRepository()
                user_convs = mem_repo.get_user_unsummarized(
                    actor_id, idle_minutes=0, min_messages=3,
                    exclude_conversation_id=exclude_conversation_id,
                )
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
        """Generate a personalized greeting based on channel, time, client type, and profile."""
        import datetime as _dt

        is_support = actor.agent_role == AgentRole.support
        is_teacher = actor.agent_role == AgentRole.teacher

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

        # --- Name resolution chain (priority: auth → profile → memory) ---
        name = actor.display_name.strip() if actor.display_name else None
        if not name and profile:
            name = getattr(profile, "display_name", None) or getattr(profile, "fio", None)
            # profile may be a dict (from get_user_profile)
            if not name and isinstance(profile, dict):
                name = profile.get("display_name") or profile.get("fio")
        if not name:
            try:
                from app.db.memory_repository import MemoryRepository
                name = MemoryRepository().get_user_name_from_atoms(actor.actor_id)
            except Exception:
                logger.debug("Memory name lookup failed for %s", actor.actor_id, exc_info=True)
        if name:
            name = name.strip()
        child_snippet = ""
        product_snippet = ""
        if profile and profile.dms_verified and profile.children:
            first_child = profile.children[0]
            fio_parts = (first_child.get("fio") or "").split()
            child_name = fio_parts[0] if fio_parts else None
            child_grade = first_child.get("grade")
            if child_name and child_grade:
                child_snippet = f" Вижу, {child_name} в {child_grade} классе."
            # Extract product for renewal context
            dms_data = profile.dms_data or {}
            students = dms_data.get("students", [])
            if students and students[0].get("product_name"):
                product_snippet = f" Текущая программа: {students[0]['product_name']}."

        # Determine client type from conversation metadata or CRM
        client_type = ClientType.unknown
        try:
            crm_ctx = self.resolve_crm_context(actor)
            client_type = self.classify_client_type(actor, crm_ctx, conversation_id)
        except Exception:
            logger.info("Could not classify client for greeting", exc_info=True)

        # Set initial funnel stage for sales conversations
        if actor.agent_role == AgentRole.sales and conversation_id:
            try:
                from app.services.funnel import FunnelService
                funnel = FunnelService(repo=self.repo, crm=self.crm)
                funnel.advance_stage(conversation_id, None, "new", force=True)
            except Exception:
                logger.info("Could not set initial funnel stage", exc_info=True)

        # --- Build greeting by client_type × role ---

        if is_teacher:
            if name and child_snippet:
                greeting = f"{hi}, {name}!{child_snippet} Готова помочь с учёбой — спрашивай!"
            elif name:
                greeting = (
                    f"{hi}, {name}! Я Эврика — твой виртуальный учитель. "
                    "Помогу разобраться в любой теме. О чём хочешь спросить?"
                )
            else:
                greeting = (
                    f"{hi}! Я Эврика — твой виртуальный учитель в EdPalm. "
                    "Помогу с любым предметом. Что будем разбирать?"
                )

        elif is_support:
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

        elif client_type == ClientType.renewal:
            # Продлённый клиент — тёплое возвращение
            if name:
                greeting = (
                    f"{hi}, {name}! Рада видеть вас снова."
                    f"{child_snippet}{product_snippet} "
                    "Чем могу помочь?"
                )
            else:
                greeting = (
                    f"{hi}! Рада видеть вас снова."
                    f"{child_snippet} "
                    "Как к вам обращаться?"
                )

        elif client_type == ClientType.reanimation:
            # Реанимация — возврат после отказа
            if name:
                greeting = (
                    f"{hi}, {name}! Рада, что вернулись. "
                    "Давайте посмотрим, что можем предложить. "
                    "Что вас интересует?"
                )
            else:
                greeting = (
                    f"{hi}! Рада, что вы к нам вернулись. "
                    "Я Эврика из EdPalm. Как к вам обращаться?"
                )

        else:
            # Новый клиент — знакомство в первую очередь
            if name:
                greeting = (
                    f"Привет, {name}! Я Эврика из EdPalm 😊 "
                    "Помогу подобрать программу обучения. "
                    "Что вас интересует?"
                )
            else:
                greeting = (
                    f"Привет! Я Эврика из EdPalm 😊 "
                    "Как к вам обращаться?"
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

    def classify_client_type(
        self,
        actor: ActorContext,
        crm_context: dict | None,
        conversation_id: str | None = None,
    ) -> ClientType:
        """Classify client as new/renewal/reanimation based on CRM + DMS data.

        Called during resolve_crm_context to determine the client journey path.
        """
        if not crm_context or not crm_context.get("contact_id"):
            return ClientType.new

        contact_id = crm_context["contact_id"]

        # Check DMS profile for active students
        profile = self.onboarding.check_profile(actor.actor_id)
        has_active_students = False
        if profile and profile.get("dms_verified"):
            dms_data = profile.get("dms_data") or {}
            students = dms_data.get("students", [])
            has_active_students = any(
                s.get("state") in ("active", None) for s in students
            )

        # If active students in DMS → renewal (client already studying)
        if has_active_students:
            client_type = ClientType.renewal
        else:
            # Check deal history in amoCRM
            try:
                all_leads = self.crm.find_leads_by_contact(contact_id)
            except Exception:
                all_leads = []

            has_won = any(l.status_id == 142 for l in all_leads)
            has_lost = any(l.status_id == 143 for l in all_leads)
            has_active = crm_context.get("active_deal") is not None

            if has_active:
                # Active deal exists but no DMS students → could be mid-process
                client_type = ClientType.new
            elif has_won:
                # Was a client before (won deal) but no active students → reanimation
                client_type = ClientType.reanimation
            elif has_lost:
                # Had a deal that was lost → reanimation
                client_type = ClientType.reanimation
            else:
                client_type = ClientType.new

        # Persist classification
        if conversation_id:
            try:
                meta = self.repo.get_conversation_metadata(conversation_id) or {}
                meta["client_type"] = client_type.value
                self.repo.update_conversation_metadata(conversation_id, meta)
            except Exception:
                logger.info("Failed to persist client_type to conversation metadata", exc_info=True)

        logger.info(
            "Client classified: actor=%s type=%s contact_id=%s",
            actor.actor_id, client_type.value, contact_id,
        )
        return client_type

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

    # ---- running summary for long conversations ----------------------------

    _RUNNING_SUMMARY_PROMPT = (
        "Ты — суммаризатор диалога. Кратко (3-5 предложений) опиши содержание "
        "этой части диалога между AI-агентом и клиентом. Сохрани ключевые факты: "
        "имя клиента, класс ребёнка, выбранный продукт, договорённости, "
        "нерешённые вопросы. Пиши на русском."
    )

    def _get_running_summary(
        self,
        conversation_id: str,
        history: list[ChatMessage],
    ) -> str | None:
        """Generate or retrieve a running summary for long conversations."""
        settings = get_settings()
        threshold = settings.conversation_summary_threshold
        keep_recent = settings.conversation_summary_keep_recent

        if len(history) <= threshold:
            return None

        # Check cached summary in conversation metadata
        conv_meta = self.repo.get_conversation_metadata(conversation_id) or {}
        cached_summary = conv_meta.get("running_summary")
        cached_up_to = conv_meta.get("running_summary_up_to", 0)

        # Regenerate if no cache or if 10+ new messages since last summary
        messages_to_summarize = len(history) - keep_recent
        if cached_summary and messages_to_summarize - cached_up_to < 10:
            return cached_summary

        # Build text from older messages
        older = history[:messages_to_summarize]
        lines = []
        for m in older:
            role_label = "Клиент" if m.role == "user" else "Агент"
            lines.append(f"{role_label}: {m.content[:300]}")
        dialog_text = "\n".join(lines)

        # If there's already a cached summary, include it for continuity
        if cached_summary:
            dialog_text = f"Предыдущее краткое содержание:\n{cached_summary}\n\nНовые сообщения:\n{dialog_text}"

        try:
            client = OpenAI(api_key=settings.openai_api_key)
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": self._RUNNING_SUMMARY_PROMPT},
                    {"role": "user", "content": dialog_text[:8000]},
                ],
                temperature=0,
                max_tokens=500,
                timeout=15,
            )
            summary = response.choices[0].message.content.strip()
        except Exception:
            logger.warning("Running summary generation failed for conv=%s", conversation_id, exc_info=True)
            return cached_summary  # return stale cache if available

        # Save to conversation metadata
        try:
            new_meta = dict(conv_meta)
            new_meta["running_summary"] = summary
            new_meta["running_summary_up_to"] = messages_to_summarize
            self.repo.update_conversation_metadata(conversation_id, new_meta)
        except Exception:
            logger.warning("Failed to save running summary metadata", exc_info=True)

        logger.info("Generated running summary for conv=%s (%d→%d msgs)", conversation_id, cached_up_to, messages_to_summarize)
        return summary

    # ---- stream answer orchestration ----------------------------------------

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

        # Inject client_type and scenario context from conversation metadata
        if conversation_id:
            conv_meta = self.repo.get_conversation_metadata(conversation_id) or {}

            # Client type classification (computed at greeting or by check_client_history)
            client_type = conv_meta.get("client_type")
            if client_type:
                type_labels = {
                    "new": "Новый клиент — первое обращение. Полная квалификация.",
                    "renewal": "Продлённый клиент — уже учится. Пропусти квалификацию, предложи продление.",
                    "reanimation": "Реанимация — ранее отказался, вернулся. Выясни что изменилось.",
                }
                type_ctx = (
                    f"# ТИП КЛИЕНТА: {client_type.upper()}\n"
                    f"{type_labels.get(client_type, '')}"
                )
                profile_context = (profile_context + "\n\n" + type_ctx) if profile_context else type_ctx

            # Renewal scenario context
            if conv_meta.get("scenario_type") == "renewal":
                renewal_ctx = (
                    f"Сценарий: пролонгация\n"
                    f"Ученик: {conv_meta.get('student_name', '—')}\n"
                    f"Текущий продукт: {conv_meta.get('current_product', '—')}\n"
                    f"Класс: {conv_meta.get('grade', '—')}"
                )
                profile_context = (profile_context + "\n\n" + renewal_ctx) if profile_context else renewal_ctx

        # Load memory context from past conversations
        from app.api.chat import _status_label  # noqa: local to avoid circular at module level
        yield StatusEvent(label=_status_label("memory"))
        memory_context = None
        try:
            memory_context = self.memory.get_memory_context(
                actor_id=actor.actor_id,
                user_text=user_text,
                agent_role=agent_role,
            )
        except Exception:
            logger.warning("Memory retrieval failed for %s", actor.actor_id, exc_info=True)

        # Generate running summary for long conversations
        running_summary = None
        if conversation_id:
            try:
                running_summary = self._get_running_summary(conversation_id, history)
            except Exception:
                logger.warning("Running summary failed for %s", conversation_id, exc_info=True)

        # Right before LLM call
        yield StatusEvent(label=_status_label("thinking"))

        return (yield from self.llm.stream_answer(
            user_text=user_text,
            actor=actor,
            history=history,
            crm_context=crm_context,
            tool_executor=tool_executor,
            profile_context=profile_context or None,
            memory_context=memory_context,
            running_summary=running_summary,
        ))

    def get_messages(self, conversation_id: str) -> list[ChatMessage]:
        return self.repo.get_messages(conversation_id)

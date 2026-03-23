"""Service layer for amoCRM imBox integration (Chat API).

Full automatic flow:
1. First message from a new user → create amoCRM contact + lead + chat
2. All subsequent messages → just forward to existing chat
3. Agent responses → forward as bot messages
"""

from __future__ import annotations

import logging

from app.db.repository import ConversationRepository
from app.integrations.amocrm import AmoCRMClient
from app.integrations.amocrm_chat import AmoCRMChatClient
from app.models.chat import ActorContext

logger = logging.getLogger("imbox")


class ImBoxService:
    """Forwards messages to/from amoCRM imBox. Fire-and-forget, never blocks chat."""

    def __init__(
        self,
        repo: ConversationRepository | None = None,
        chat_client: AmoCRMChatClient | None = None,
        crm_client: AmoCRMClient | None = None,
    ) -> None:
        self.repo = repo or ConversationRepository()
        self.client = chat_client or AmoCRMChatClient()
        self._crm = crm_client  # lazy-init to avoid import cycle
        logger.info("[init] ImBoxService created, is_enabled=%s", self.is_enabled())

    @property
    def crm(self) -> AmoCRMClient:
        if self._crm is None:
            self._crm = AmoCRMClient()
        return self._crm

    def is_enabled(self) -> bool:
        return self.client.is_configured()

    # ---- automatic CRM setup ------------------------------------------------

    def _ensure_chat_setup(self, actor: ActorContext, conv_id: str) -> None:
        """
        Ensure amoCRM contact + lead + chat exist for this actor.
        Called once per actor, on first message.
        Idempotent: checks mapping before creating anything.
        """
        # Check if already set up
        existing = self.repo.get_chat_mapping_details(actor.actor_id)
        if existing and existing.get("amocrm_chat_id"):
            logger.info("[setup] already set up for %s, skipping", actor.actor_id)
            return

        logger.info("[setup] first message from %s, creating CRM entities...", actor.actor_id)

        # Step 1: Find or create amoCRM contact
        phone = actor.phone
        name = actor.display_name or "Клиент EdPalm"
        telegram_id = None
        if actor.channel.value == "telegram" and actor.actor_id.startswith("telegram:"):
            telegram_id = actor.actor_id.split(":", 1)[1]

        contact, is_new = self.crm.find_or_create_contact(
            phone=phone, name=name, telegram_id=telegram_id,
        )

        if not contact:
            logger.error("[setup] failed to find/create contact for %s", actor.actor_id)
            return

        logger.info(
            "[setup] contact: id=%d name=%s is_new=%s",
            contact.id, contact.name, is_new,
        )

        # Save contact mapping
        self.repo.save_contact_mapping(actor.actor_id, contact.id, contact.name)

        # Step 2: Find or create a lead
        lead = None
        leads = self.crm.find_leads_by_contact(contact.id)
        active_leads = [l for l in leads if l.status_id != 143]  # exclude closed
        if active_leads:
            lead = active_leads[0]
            logger.info("[setup] using existing lead: id=%d", lead.id)
        else:
            lead = self.crm.create_lead(
                name=f"Обращение через AI-агент ({name})",
                contact_id=contact.id,
            )
            if lead:
                logger.info("[setup] created lead: id=%d", lead.id)
            else:
                logger.warning("[setup] failed to create lead, continuing without it")

        # Step 3: Create chat in amojo (required for imBox visibility)
        chat_result = self.client.create_chat(
            conversation_id=conv_id,
            user_id=actor.actor_id,
            user_name=name,
            phone=phone,
        )
        if chat_result:
            amojo_chat_id = chat_result.get("id")
            if amojo_chat_id:
                self.repo.update_chat_mapping_amocrm_id(actor.actor_id, amojo_chat_id)
                logger.info("[setup] chat created: amojo_id=%s", amojo_chat_id)

        logger.info("[setup] DONE for %s", actor.actor_id)

    # ---- message forwarding ------------------------------------------------

    def forward_user_message(self, actor: ActorContext, text: str) -> None:
        logger.info(
            "[forward_user] actor=%s channel=%s is_enabled=%s text=%s",
            actor.actor_id, actor.channel.value, self.is_enabled(), text[:60],
        )
        if not self.is_enabled():
            logger.info("[forward_user] SKIP — imBox not configured")
            return
        try:
            conv_id = self.repo.get_or_create_chat_mapping(actor.actor_id)
            logger.info("[forward_user] conv_id=%s", conv_id)

            # Auto-setup CRM entities on first message
            self._ensure_chat_setup(actor, conv_id)

            # Send user message to imBox
            logger.info("[forward_user] sending to imBox...")
            result = self.client.send_message(
                conversation_id=conv_id,
                sender_id=actor.actor_id,
                sender_name=actor.display_name or "Клиент EdPalm",
                text=text,
                is_bot=False,
                sender_phone=actor.phone,
            )
            logger.info(
                "[forward_user] result: success=%s msgid=%s error=%s",
                result.success, result.msgid, result.error,
            )
            if result.success and result.raw:
                real_id = (result.raw.get("new_conversation") or {}).get("id")
                if real_id:
                    logger.info("[forward_user] updating mapping with amocrm_chat_id=%s", real_id)
                    self.repo.update_chat_mapping_amocrm_id(actor.actor_id, real_id)
        except Exception:
            logger.exception("[forward_user] EXCEPTION while forwarding to imBox")

    def forward_agent_response(self, actor: ActorContext, text: str) -> None:
        """Forward AI agent response to amoCRM imBox as bot (outgoing) message."""
        if not self.is_enabled():
            return
        try:
            conv_id = self.repo.get_or_create_chat_mapping(actor.actor_id)
            result = self.client.send_message(
                conversation_id=conv_id,
                sender_id="eureka-bot",
                sender_name="Эврика",
                text=text,
                is_bot=True,
                receiver_id=actor.actor_id,
                receiver_phone=actor.phone,
            )
            logger.info(
                "[forward_agent] result: success=%s msgid=%s error=%s",
                result.success, result.msgid, result.error,
            )
        except Exception:
            logger.exception("[forward_agent] EXCEPTION while forwarding to imBox")

"""Service layer for amoCRM imBox integration (Chat API).

Full automatic flow:
1. First message from a new user → create amoCRM contact + lead + chat
2. All subsequent messages → just forward to existing chat
3. Agent responses → add as note to the lead (Chat API doesn't support outgoing)
"""

from __future__ import annotations

import logging
import time

from app.db.repository import ConversationRepository
from app.integrations.amocrm import AmoCRMClient
from app.integrations.amocrm_chat import AmoCRMChatClient
from app.models.chat import ActorContext

logger = logging.getLogger("imbox")

MAX_SEND_RETRIES = 1
RETRY_DELAY_S = 1.0


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
        # Check if already fully set up (chat_id + lead_id present)
        existing = self.repo.get_chat_mapping_details(actor.actor_id)
        if existing and existing.get("amocrm_chat_id") and existing.get("amocrm_lead_id"):
            logger.info("[setup] already set up for %s (lead=%s), skipping",
                        actor.actor_id, existing.get("amocrm_lead_id"))
            return

        logger.info("[setup] first message from %s, creating CRM entities...", actor.actor_id)

        # Step 1: Find or create amoCRM contact
        # Re-use existing contact_id from mapping if available (prevents duplicates)
        phone = actor.phone
        name = actor.display_name or "Клиент EdPalm"
        telegram_id = None
        if actor.channel.value == "telegram" and actor.actor_id.startswith("telegram:"):
            telegram_id = actor.actor_id.split(":", 1)[1]

        contact = None
        existing_contact_id = existing.get("amocrm_contact_id") if existing else None
        if existing_contact_id:
            # Re-fetch contact from amoCRM to verify it still exists
            contact_data = self.crm._request("GET", f"/contacts/{existing_contact_id}")
            if contact_data and "id" in contact_data:
                contact = self.crm._parse_contact(contact_data)
                logger.info("[setup] reusing existing contact: id=%d", contact.id)

        if not contact:
            contact, is_new = self.crm.find_or_create_contact(
                phone=phone, name=name, telegram_id=telegram_id,
            )
            if not contact:
                logger.error("[setup] failed to find/create contact for %s", actor.actor_id)
                return
            logger.info("[setup] contact: id=%d name=%s is_new=%s", contact.id, contact.name, is_new)

        # Save contact mapping
        self.repo.save_contact_mapping(actor.actor_id, contact.id, contact.name)

        # Step 2: Find or create a lead
        lead = None
        existing_lead_id = existing.get("amocrm_lead_id") if existing else None
        if existing_lead_id:
            lead = self.crm.get_lead(existing_lead_id)
            if lead and lead.status_id != 143:  # not closed-lost
                logger.info("[setup] reusing existing lead: id=%d", lead.id)
            else:
                lead = None  # stale or closed, create new

        if not lead:
            leads = self.crm.find_leads_by_contact(contact.id)
            active_leads = [l for l in leads if l.status_id not in (142, 143)]
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

        # Save lead_id to chat mapping (critical for forward_agent_response)
        if lead:
            self.repo.update_chat_mapping_lead_id(actor.actor_id, lead.id)

        # Step 3: Create chat in amojo (required for imBox visibility)
        if not (existing and existing.get("amocrm_chat_id")):
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

    def _send_with_retry(self, **kwargs) -> None:
        """Send message to imBox with 1 retry on transient failure."""
        result = self.client.send_message(**kwargs)
        if result.success:
            logger.info("[send_retry] OK: msgid=%s", result.msgid)
            if result.raw:
                real_id = (result.raw.get("new_conversation") or {}).get("id")
                if real_id:
                    actor_id = kwargs.get("sender_id", "")
                    self.repo.update_chat_mapping_amocrm_id(actor_id, real_id)
            return

        # Retry once for transient errors
        logger.warning("[send_retry] first attempt failed: %s, retrying in %ss...",
                       result.error, RETRY_DELAY_S)
        time.sleep(RETRY_DELAY_S)
        result2 = self.client.send_message(**kwargs)
        if result2.success:
            logger.info("[send_retry] retry OK: msgid=%s", result2.msgid)
        else:
            logger.error("[send_retry] retry also failed: %s (message lost)", result2.error)

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

            # Send user message to imBox (with retry)
            logger.info("[forward_user] sending to imBox...")
            self._send_with_retry(
                conversation_id=conv_id,
                sender_id=actor.actor_id,
                sender_name=actor.display_name or "Клиент EdPalm",
                text=text,
                is_bot=False,
                sender_phone=actor.phone,
            )
        except Exception:
            logger.exception("[forward_user] EXCEPTION while forwarding to imBox")

    def forward_agent_response(self, actor: ActorContext, text: str, conversation_id: str | None = None) -> None:
        """Forward AI agent response to amoCRM as a note on the lead.

        amoCRM Chat API for custom channels does not support outgoing messages.
        Instead, we add the AI response as a note to the lead so the manager
        sees the full conversation context in the deal card.
        """
        if not self.is_enabled():
            return
        try:
            lead_id = self._resolve_lead_id(actor, conversation_id)

            if lead_id:
                truncated = text[:2000] if len(text) > 2000 else text
                self.crm.add_note(lead_id, f"[Эврика]: {truncated}")
                logger.info("[forward_agent] note added to lead=%d, text=%s", lead_id, text[:60])
            else:
                logger.warning("[forward_agent] no lead_id found for actor=%s conv=%s, note skipped",
                               actor.actor_id, conversation_id)
        except Exception:
            logger.exception("[forward_agent] EXCEPTION while adding note to lead")

    def _resolve_lead_id(self, actor: ActorContext, conversation_id: str | None) -> int | None:
        """Find lead_id through all available sources. Priority:
        1. deal_mapping (funnel-created leads)
        2. chat_mapping.amocrm_lead_id (setup-created leads)
        3. contact_mapping → find_active_lead (dynamic lookup)
        """
        # Source 1: deal_mapping (created by FunnelService)
        if conversation_id and len(conversation_id) > 10:  # valid UUID
            try:
                deal = self.repo.get_deal_mapping(conversation_id)
                if deal and deal.get("amocrm_lead_id"):
                    return deal["amocrm_lead_id"]
            except Exception:
                logger.debug("deal_mapping lookup failed for conv=%s", conversation_id)

        # Source 2: chat_mapping.amocrm_lead_id (saved during _ensure_chat_setup)
        mapping = self.repo.get_chat_mapping_details(actor.actor_id)
        if mapping and mapping.get("amocrm_lead_id"):
            return mapping["amocrm_lead_id"]

        # Source 3: contact_mapping → search for any active lead
        contact_id = mapping.get("amocrm_contact_id") if mapping else None
        if not contact_id:
            contact_id = self.repo.get_contact_mapping(actor.actor_id)

        if contact_id:
            # Search all pipelines, not just sales
            leads = self.crm.find_leads_by_contact(contact_id)
            active = [l for l in leads if l.status_id not in (142, 143)]
            if active:
                lead_id = active[0].id
                # Cache for next time
                self.repo.update_chat_mapping_lead_id(actor.actor_id, lead_id)
                return lead_id

        return None

from __future__ import annotations

import json
import logging
from collections.abc import Generator

import httpx
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.auth.service import AuthService
from app.errors import error_response
from app.logging_config import enrich_ctx

_TOOL_LABELS = {
    "search_knowledge_base": "Ищу в базе знаний...",
    "get_amocrm_contact": "Проверяю данные клиента...",
    "get_amocrm_deal": "Проверяю активные сделки...",
    "create_amocrm_lead": "Создаю заявку...",
    "update_deal_stage": "Обновляю статус заявки...",
    "get_client_profile": "Загружаю профиль клиента...",
    "generate_payment_link": "Готовлю ссылку на оплату...",
    "escalate_to_manager": "Подключаю менеджера...",
    "create_manager_task": "Создаю задачу менеджеру...",
    "register_decline": "Фиксирую обратную связь...",
    "create_amocrm_ticket": "Создаю обращение...",
}


def _tool_label(name: str) -> str:
    return _TOOL_LABELS.get(name, "Обрабатываю...")
from app.config import get_settings
from app.models.chat import (
    AgentRole,
    AuthPayload,
    Channel,
    ChatStreamRequest,
    ConversationMessagesResponse,
    StartConversationRequest,
    StartConversationResponse,
)
from app.db.events import EventTracker
from app.services.chat import ChatService
from app.services.imbox import ImBoxService
from app.services.llm import LLMChunk, ToolCallEvent
from app.services.speech import ALLOWED_FORMATS, SpeechService

logger = logging.getLogger("api.chat")

router = APIRouter(prefix="/api/v1", tags=["chat"])
auth_service = AuthService()
chat_service = ChatService()
speech_service = SpeechService()
imbox_service = ImBoxService()
event_tracker = EventTracker()


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _escape_html(text: str) -> str:
    """Escape HTML special characters for Telegram parse_mode=HTML."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _notify_manager(
    reason: str, actor, conversation_id: str, summary: str,
    crm_lead_id: int | None = None,
) -> None:
    """Send rich Telegram notification to manager about escalation."""
    settings = get_settings()
    chat_id = settings.manager_telegram_chat_id
    bot_token = settings.telegram_bot_token

    if not chat_id or not bot_token:
        logger.warning("Manager Telegram notification not configured")
        return

    esc = _escape_html
    display = esc(actor.display_name or actor.actor_id)
    agent_role = getattr(actor, "agent_role", "sales")
    role_val = agent_role.value if hasattr(agent_role, "value") else str(agent_role)
    role_label = "Поддержка" if role_val == "support" else "Продажи"

    # Conversation summary — last 5 messages
    conversation_summary = esc(summary[:800])
    try:
        from app.db.repository import ConversationRepository
        repo = ConversationRepository()
        messages = repo.get_messages(conversation_id, limit=10)
        if messages:
            lines = []
            for m in messages[-5:]:
                role_name = "Клиент" if m.role == "user" else "Агент"
                lines.append(f"{role_name}: {esc(m.content[:150])}")
            conversation_summary = "\n".join(lines)
    except Exception:
        pass  # fallback to summary[:800]

    # Client profile
    profile_snippet = ""
    try:
        from app.db.repository import ConversationRepository
        repo = ConversationRepository()
        profile = repo.get_user_profile(actor.actor_id)
        if profile:
            fio = profile.get("fio", "—")
            phone = profile.get("phone", "—")
            profile_snippet = f"\n<b>Профиль:</b> {esc(fio)}, тел: {esc(phone)}"
            children = profile.get("children") or []
            for child in children[:3]:
                child_fio = child.get("fio", "—") if isinstance(child, dict) else "—"
                child_grade = child.get("grade", "—") if isinstance(child, dict) else "—"
                profile_snippet += f"\n  · {esc(str(child_fio))}, {child_grade} класс"
    except Exception:
        pass

    # CRM link
    crm_link = ""
    if crm_lead_id:
        crm_link = f"\n<b>CRM:</b> https://{settings.amocrm_subdomain}.amocrm.ru/leads/detail/{crm_lead_id}"

    text = (
        f"<b>⚠ Эскалация от AI-агента Эврика</b>\n\n"
        f"<b>Роль:</b> {role_label}\n"
        f"<b>Клиент:</b> {display}\n"
        f"<b>Канал:</b> {actor.channel.value}\n"
        f"<b>Причина:</b> {esc(reason)}"
        f"{profile_snippet}"
        f"{crm_link}\n\n"
        f"<b>Последние сообщения:</b>\n{conversation_summary}"
    )

    # Build inline keyboard with links
    buttons = []
    if crm_lead_id:
        buttons.append({
            "text": "📋 Открыть в CRM",
            "url": f"https://{settings.amocrm_subdomain}.amocrm.ru/leads/detail/{crm_lead_id}",
        })
    buttons.append({
        "text": "💬 Открыть диалог",
        "url": f"{settings.frontend_url}/#/?conv={conversation_id}&manager_key={settings.dashboard_api_key}&role={role_val}",
    })
    buttons.append({
        "text": "✅ Согласовать",
        "url": f"{settings.backend_url}/api/v1/manager/approve/{conversation_id}?key={settings.dashboard_api_key}",
    })

    payload: dict = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }
    if buttons:
        payload["reply_markup"] = json.dumps({"inline_keyboard": [buttons]})

    try:
        httpx.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json=payload,
            timeout=10,
        )
    except Exception:
        logger.exception("Failed to send escalation notification")


def _make_stream(
    user_text: str, actor, ctx, *, transcript: str | None = None,
) -> Generator[str, None, None]:
    """Shared SSE stream generator for text and voice endpoints."""
    chat_service.save_user_message(ctx.conversation.id, user_text)
    imbox_service.forward_user_message(actor, user_text)

    # Cancel pending follow-ups when user replies
    try:
        chat_service.repo.cancel_followups_for_conversation(ctx.conversation.id)
    except Exception:
        logger.debug("No follow-ups to cancel for conv=%s", ctx.conversation.id)

    meta_payload = {
        "conversation_id": ctx.conversation.id,
        "actor_id": actor.actor_id,
        "channel": actor.channel.value,
    }
    if transcript is not None:
        meta_payload["transcript"] = transcript
    yield _sse("meta", meta_payload)

    # Deliver pending manager messages (arrived via imBox while user was away)
    try:
        pending_mgr = chat_service.repo.get_undelivered_manager_messages(ctx.conversation.id)
        # Fallback: check by actor_id for messages with NULL agent_conversation_id
        if not pending_mgr:
            pending_mgr = chat_service.repo.get_undelivered_manager_messages_by_actor(actor.actor_id)
        if pending_mgr:
            for msg in pending_mgr:
                sender = msg.get("sender_name", "Менеджер")
                yield _sse("manager_message", {
                    "text": f"[{sender}]: {msg['content']}",
                    "sender": sender,
                    "created_at": msg["created_at"].isoformat() if msg.get("created_at") else None,
                })
            chat_service.repo.mark_manager_messages_delivered(
                [str(m["id"]) for m in pending_mgr]
            )
    except Exception:
        logger.debug("Failed to deliver pending manager messages", exc_info=True)

    # Resolve CRM context and classify client if not done yet
    crm_context = chat_service.resolve_crm_context(actor)
    if crm_context and ctx.conversation.id:
        try:
            conv_meta = chat_service.repo.get_conversation_metadata(ctx.conversation.id) or {}
            if not conv_meta.get("client_type"):
                chat_service.classify_client_type(actor, crm_context, ctx.conversation.id)
        except Exception:
            pass  # non-blocking

    generator = chat_service.stream_answer(
        user_text, ctx.actor, ctx.history,
        conversation_id=ctx.conversation.id,
        crm_context=crm_context,
    )

    full_text: list[str] = []
    usage_tokens = None
    rag_metadata = None

    error_occurred = False
    try:
        while True:
            event = next(generator)
            if isinstance(event, LLMChunk):
                full_text.append(event.token)
                yield _sse("token", {"text": event.token})
            elif isinstance(event, ToolCallEvent):
                logger.info("SSE: tool_call event: %s", event.name)
                label = _tool_label(event.name)
                yield _sse("tool_call", {"name": event.name, "label": label})
                if event.payment_data:
                    yield _sse("payment_card", event.payment_data)
    except StopIteration as stop:
        logger.info("SSE: generator finished (StopIteration)")
        result = stop.value
        if result:
            usage_tokens = result.usage_tokens
            rag_metadata = result.rag_metadata
    except Exception as exc:
        logger.exception("SSE: generator error: %s", exc)
        error_occurred = True
        yield _sse("error", {"message": "Произошла ошибка при генерации ответа"})

    answer = "".join(full_text).strip()
    if not answer:
        answer = "Извините, не смогла сформировать ответ. Попробуйте еще раз."

    try:
        chat_service.save_assistant_message(
            conversation_id=ctx.conversation.id,
            text=answer,
            usage_tokens=usage_tokens,
            rag_metadata=rag_metadata,
        )
        imbox_service.forward_agent_response(actor, answer)
    except Exception:
        logger.warning("Failed to save assistant message", exc_info=True)

    # Handle escalation
    if rag_metadata and rag_metadata.get("escalation"):
        try:
            reason = "Агент инициировал эскалацию"
            crm_lead_id = None
            for tc in rag_metadata.get("tool_calls", []):
                if tc.get("name") == "escalate_to_manager":
                    reason = tc.get("args", {}).get("reason", reason)
                    try:
                        tc_result = json.loads(tc.get("result", "{}"))
                        crm_lead_id = tc_result.get("lead_id")
                    except (json.JSONDecodeError, TypeError):
                        pass
                    break

            chat_service.repo.update_escalation_metadata(ctx.conversation.id, reason, crm_lead_id)
            _notify_manager(reason, actor, ctx.conversation.id, answer, crm_lead_id=crm_lead_id)
            event_tracker.track_escalation(
                ctx.conversation.id, actor.actor_id, reason,
                channel=actor.channel.value,
                agent_role=getattr(actor, "agent_role", "sales"),
            )
            yield _sse("escalation", {"reason": reason, "manager_notified": True})
        except Exception:
            logger.warning("Escalation handling failed", exc_info=True)

    # Auto-title: set title from first user message if conversation has none
    try:
        from app.db.pool import get_connection
        with get_connection() as conn:
            if conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT title FROM conversations WHERE id = %s", (ctx.conversation.id,))
                    row = cur.fetchone()
                    if row and not row.get("title"):
                        auto_title = user_text.strip()[:60]
                        if len(user_text.strip()) > 60:
                            auto_title = auto_title.rsplit(" ", 1)[0] + "..."
                        chat_service.repo.update_conversation_title(ctx.conversation.id, auto_title)
                        yield _sse("title", {"conversation_id": ctx.conversation.id, "title": auto_title})
    except Exception:
        logger.warning("Auto-title generation failed", exc_info=True)

    yield _sse("done", {"text": answer, "usage_tokens": usage_tokens})

    # Suggestion chips — contextual quick-reply buttons
    try:
        agent_role_str = getattr(actor, "agent_role", "sales")
        if hasattr(agent_role_str, "value"):
            agent_role_str = agent_role_str.value
        suggestions = chat_service.llm.generate_suggestions(
            assistant_text=answer,
            user_text=user_text,
            agent_role=str(agent_role_str),
        )
        if suggestions:
            yield _sse("suggestions", {"chips": suggestions})
    except Exception:
        logger.debug("Suggestion generation failed", exc_info=True)


# ---- endpoints -----------------------------------------------------------

@router.post("/conversations/start", response_model=StartConversationResponse)
def start_conversation(req: StartConversationRequest) -> StartConversationResponse:
    actor = auth_service.resolve(req.auth)
    actor = actor.model_copy(update={"agent_role": req.agent_role})
    enrich_ctx(user_id=actor.actor_id, agent_role=req.agent_role.value)

    # Manager mode: load existing conversation without owner check
    is_manager = actor.channel == Channel.manager
    if is_manager and req.conversation_id:
        messages = chat_service.repo.get_messages(req.conversation_id, limit=50)
        conv_status = chat_service.repo.get_conversation_status(req.conversation_id)
        greeting = "Вы подключены как менеджер. Видите историю переписки клиента."
        return StartConversationResponse(
            conversation_id=req.conversation_id,
            actor=actor,
            greeting=greeting,
            status=conv_status.get("status", "active") if conv_status else "active",
            escalated_reason=conv_status.get("escalated_reason") if conv_status else None,
        )

    try:
        ctx = chat_service.ensure_conversation(actor, conversation_id=req.conversation_id, force_new=req.force_new)
    except Exception:
        logger.exception("ensure_conversation failed for %s force_new=%s", actor.actor_id, req.force_new)
        raise
    # Generate greeting only for new conversations (no history)
    if not ctx.history:
        agent_role_val = actor.agent_role.value if hasattr(actor.agent_role, "value") else str(actor.agent_role)
        event_tracker.track(
            "conversation_started",
            conversation_id=ctx.conversation.id,
            actor_id=actor.actor_id,
            channel=actor.channel.value,
            agent_role=agent_role_val,
            data={"channel": actor.channel.value, "agent_role": agent_role_val},
        )
        greeting = chat_service.generate_greeting(actor, ctx.conversation.id)
    else:
        # For resumed conversations, use the first assistant message as greeting
        greeting = next(
            (m.content for m in ctx.history if m.role == "assistant"),
            "Здравствуйте! Я Эврика, виртуальный менеджер EdPalm."
        )
    return StartConversationResponse(
        conversation_id=ctx.conversation.id,
        actor=actor,
        greeting=greeting,
        status=ctx.conversation.status,
        escalated_reason=ctx.conversation.escalated_reason,
    )



@router.post("/conversations/{conversation_id}/messages", response_model=ConversationMessagesResponse)
def conversation_messages(conversation_id: str, auth: AuthPayload) -> ConversationMessagesResponse:
    actor = auth_service.resolve(auth)
    enrich_ctx(user_id=actor.actor_id, conversation_id=conversation_id)
    # Manager can view any conversation; regular users only their own
    is_manager = actor.channel == Channel.manager
    if not is_manager:
        conv = chat_service.repo.get_conversation_owner(conversation_id)
        if not conv or conv != actor.actor_id:
            raise HTTPException(403, "Access denied")
    messages = chat_service.get_messages(conversation_id)
    conv_status = chat_service.repo.get_conversation_status(conversation_id)
    return ConversationMessagesResponse(
        conversation_id=conversation_id,
        messages=messages,
        status=conv_status.get("status", "active") if conv_status else "active",
        escalated_reason=conv_status.get("escalated_reason") if conv_status else None,
    )


@router.post("/chat/stream")
def chat_stream(req: ChatStreamRequest) -> StreamingResponse:
    actor = auth_service.resolve(req.auth)
    actor = actor.model_copy(update={"agent_role": req.agent_role})
    enrich_ctx(user_id=actor.actor_id, agent_role=req.agent_role.value)

    # Manager mode: save message as manager_message, don't invoke LLM
    is_manager = actor.channel == Channel.manager
    if is_manager and req.conversation_id:
        chat_service.repo.save_message(
            conversation_id=req.conversation_id,
            role="assistant",
            content=req.message,
            metadata={"source": "manager", "sender_name": "Менеджер"},
        )
        # Activate manager mode — client messages will go to manager, not AI
        chat_service.repo.set_manager_active(req.conversation_id, True)
        # Also save to manager_messages table for SSE live delivery
        owner = chat_service.repo.get_conversation_owner(req.conversation_id)
        if owner:
            chat_service.repo.save_manager_message(
                actor_id=owner,
                content=req.message,
                sender_name="Менеджер",
                conversation_id=req.conversation_id,
            )
        def _manager_stream():
            yield _sse("meta", {"conversation_id": req.conversation_id, "actor_id": actor.actor_id, "channel": "manager"})
            yield _sse("done", {"text": "", "usage_tokens": 0})
        return StreamingResponse(_manager_stream(), media_type="text/event-stream")

    # Client mode: check if manager is active → route to manager, skip AI
    conv_id = req.conversation_id
    if conv_id and chat_service.repo.is_manager_active(conv_id):
        # Manager is active — save client message but DON'T invoke LLM
        chat_service.repo.save_message(
            conversation_id=conv_id,
            role="user",
            content=req.message,
        )
        chat_service.repo.update_message_stats(conv_id, req.message)
        # Acknowledge to client (no AI response)
        def _client_to_manager_stream():
            yield _sse("meta", {"conversation_id": conv_id, "actor_id": actor.actor_id, "channel": actor.channel.value})
            yield _sse("status", {"manager_active": True, "message": "Ваше сообщение передано менеджеру."})
            yield _sse("done", {"text": "", "usage_tokens": 0})
        return StreamingResponse(_client_to_manager_stream(), media_type="text/event-stream")

    ctx = chat_service.ensure_conversation(actor, conversation_id=req.conversation_id)
    enrich_ctx(conversation_id=ctx.conversation.id)
    return StreamingResponse(
        _make_stream(req.message, actor, ctx),
        media_type="text/event-stream",
    )


@router.post("/chat/transcribe")
async def chat_transcribe(
    audio: UploadFile = File(...),
    auth_json: str = Form(...),
) -> dict:
    """Accept audio, transcribe via Whisper, return text (no LLM call)."""
    # Validate auth before consuming Whisper credits
    auth = AuthPayload.model_validate_json(auth_json)
    actor = auth_service.resolve(auth)
    enrich_ctx(user_id=actor.actor_id)
    ext = (audio.filename or "audio.webm").rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_FORMATS:
        return error_response("audio_format")
    audio_bytes = await audio.read()
    if len(audio_bytes) > 25 * 1024 * 1024:
        return error_response("audio_too_large")
    transcript = speech_service.transcribe(audio_bytes, filename=audio.filename or f"voice.{ext}")
    if not transcript:
        return error_response("stt_unavailable")
    return {"transcript": transcript}


@router.post("/chat/tts")
async def chat_tts(request: Request) -> StreamingResponse:
    """Synthesize assistant text to speech using OpenAI TTS API."""
    body = await request.json()

    auth = AuthPayload.model_validate(body.get("auth", {}))
    actor = auth_service.resolve(auth)
    enrich_ctx(user_id=actor.actor_id)

    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "Text is required")

    settings = get_settings()

    def audio_stream():
        yield from speech_service.synthesize_stream(text, voice=settings.openai_tts_voice)

    return StreamingResponse(
        audio_stream(),
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": "inline",
            "Cache-Control": "public, max-age=3600",
        },
    )


@router.post("/chat/voice")
async def chat_voice(
    audio: UploadFile = File(...),
    auth_json: str = Form(...),
    conversation_id: str | None = Form(default=None),
    agent_role: str = Form(default="sales"),
) -> StreamingResponse:
    """Accept voice message, transcribe via Whisper, then stream LLM response."""
    ext = (audio.filename or "audio.webm").rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_FORMATS:
        return error_response("audio_format")

    audio_bytes = await audio.read()
    if len(audio_bytes) > 25 * 1024 * 1024:
        return error_response("audio_too_large")

    transcript = speech_service.transcribe(audio_bytes, filename=audio.filename or f"voice.{ext}")
    if not transcript:
        return error_response("stt_unavailable")

    role_enum = AgentRole(agent_role) if agent_role in ("sales", "support", "teacher") else AgentRole.sales
    auth = AuthPayload.model_validate_json(auth_json)
    actor = auth_service.resolve(auth)
    actor = actor.model_copy(update={"agent_role": role_enum})
    enrich_ctx(user_id=actor.actor_id, agent_role=role_enum.value)
    ctx = chat_service.ensure_conversation(actor, conversation_id=conversation_id)
    enrich_ctx(conversation_id=ctx.conversation.id)

    return StreamingResponse(
        _make_stream(transcript, actor, ctx, transcript=transcript),
        media_type="text/event-stream",
    )


@router.get("/amocrm/oauth/callback")
def amocrm_oauth_callback(code: str):
    """Callback for amoCRM OAuth2 authorization flow."""
    from app.integrations.amocrm import AmoCRMClient

    client = AmoCRMClient()
    success = client.exchange_code(code)
    if success:
        return {"status": "ok", "message": "amoCRM tokens saved"}
    raise HTTPException(500, "Failed to exchange amoCRM authorization code")


async def _process_chat_webhook(request: Request, scope_id: str | None = None):
    """Core logic for amoCRM imBox webhooks. Supports v1 and v2 formats."""
    body = await request.body()
    body_str = body.decode("utf-8", errors="replace")

    logger.info(
        "amoCRM chat webhook: scope_id=%s body_len=%d headers=%s",
        scope_id, len(body_str),
        {k: v for k, v in request.headers.items() if k.lower() in ("x-signature", "content-type")},
    )
    logger.debug("amoCRM chat webhook body: %s", body_str[:2000])

    signature = request.headers.get("X-Signature", "")
    if not signature:
        logger.warning("amoCRM chat webhook missing X-Signature header")
        return {"status": "signature_missing"}
    if not imbox_service.client.verify_webhook_signature(body, signature):
        logger.warning("Invalid amoCRM chat webhook signature")
        return {"status": "signature_invalid"}

    try:
        payload = json.loads(body_str)
    except Exception:
        return {"status": "invalid_json"}

    # --- Parse webhook: support BOTH v1 and v2 formats ---
    conversation_id = ""
    sender_name = ""
    sender_id = ""
    text = ""
    msgid = ""

    event_type = payload.get("event_type")

    if event_type == "new_message":
        # V1 format: {"event_type": "new_message", "payload": {...}}
        inner = payload.get("payload", {})
        conversation_id = inner.get("conversation_id", "")
        sender = inner.get("sender", {})
        sender_name = sender.get("name", "")
        sender_id = sender.get("id", "")
        message = inner.get("message", {})
        text = message.get("text", "")
        msgid = inner.get("msgid", "")
        logger.info("Webhook v1: conv=%s sender=%s text=%s", conversation_id, sender_name, text[:80])

    elif "message" in payload and not event_type:
        # V2 format: {"account_id": "...", "time": ..., "message": {...}}
        msg_wrapper = payload["message"]
        conv_data = msg_wrapper.get("conversation", {})
        # client_id = our conversation_id (agent_chat_...), id = amoCRM internal UUID
        conversation_id = conv_data.get("client_id") or conv_data.get("id", "")
        sender_data = msg_wrapper.get("sender", {})
        sender_name = sender_data.get("name", "")
        sender_id = sender_data.get("id", "")
        inner_message = msg_wrapper.get("message", {})
        text = inner_message.get("text", "")
        msgid = inner_message.get("id", "")
        # V2 may have receiver.client_id as fallback for finding actor
        receiver_client_id = msg_wrapper.get("receiver", {}).get("client_id", "")
        logger.info(
            "Webhook v2: conv=%s sender_id=%s receiver_client=%s text=%s",
            conversation_id, sender_id, receiver_client_id, text[:80],
        )
    else:
        logger.info("amoCRM webhook: unrecognized format, keys=%s", list(payload.keys()))
        return {"status": "ok"}

    if not text:
        logger.info("amoCRM webhook: empty text, skipping")
        return {"status": "ok"}

    # Find actor by conversation_id
    actor_id = imbox_service.repo.find_actor_by_chat_conversation_id(conversation_id)
    if not actor_id:
        logger.warning("amoCRM webhook: no actor found for conv=%s", conversation_id)
        return {"status": "actor_not_found"}

    display_name = sender_name or "Менеджер"

    # Check for resolution commands
    cmd = text.strip().lower()
    if cmd in ("/resolve", "/close", "/готово"):
        agent_conv_id = chat_service.repo.find_escalated_conversation(actor_id)
        if agent_conv_id:
            resolved = chat_service.repo.resolve_escalation(
                agent_conv_id, resolved_by=display_name,
            )
            if resolved:
                event_tracker.track(
                    "escalation_resolved",
                    conversation_id=agent_conv_id,
                    actor_id=actor_id,
                    data={"resolved_by": display_name, "source": "imbox"},
                )
                logger.info("Escalation resolved via imBox command for conv=%s", agent_conv_id)
        return {"status": "resolved"}

    # Find agent conversation for this actor (escalated > active > any latest)
    agent_conv_id = (
        chat_service.repo.find_escalated_conversation(actor_id)
        or chat_service.repo.find_active_conversation(actor_id)
        or chat_service.repo.find_latest_conversation(actor_id)
    )

    # Save raw manager message (with agent_conversation_id for deferred delivery)
    imbox_service.repo.save_manager_message(
        actor_id=actor_id,
        content=text,
        conversation_id=conversation_id,
        amocrm_msgid=msgid,
        sender_name=display_name,
        agent_conversation_id=agent_conv_id,
    )

    # Inject into agent conversation so client sees it in real-time
    try:
        if agent_conv_id:
            chat_service.repo.save_message(
                conversation_id=agent_conv_id,
                role="assistant",
                content=f"[{display_name}]: {text}",
                metadata={"source": "manager", "sender_name": display_name, "amocrm_msgid": msgid},
            )
            logger.info("Manager message injected into conv=%s for actor=%s", agent_conv_id, actor_id)
        else:
            logger.warning("No active/escalated conversation for actor=%s, message saved but not injected", actor_id)
    except Exception:
        logger.warning("Failed to inject manager message into conversation", exc_info=True)

    return {"status": "ok"}


@router.post("/amocrm/chat/webhook/{scope_id}")
async def amocrm_chat_webhook(scope_id: str, request: Request):
    """Receive manager replies from amoCRM imBox (with scope_id)."""
    return await _process_chat_webhook(request, scope_id)


@router.post("/amocrm/chat/webhook")
async def amocrm_chat_webhook_no_scope(request: Request):
    """Receive manager replies from amoCRM imBox (without scope_id)."""
    return await _process_chat_webhook(request)


@router.post("/amocrm/chat/connect")
def amocrm_chat_connect():
    """One-time: connect chat channel to amoCRM account. Returns scope_id."""
    ok = imbox_service.client.connect_channel()
    if ok:
        scope_id = imbox_service.client.get_scope_id()
        return {"status": "ok", "scope_id": scope_id}
    raise HTTPException(500, "Failed to connect amoCRM chat channel")


@router.get("/amocrm/chat/status")
def amocrm_chat_status():
    """Diagnostic: check amoCRM Chat API configuration."""
    configured = imbox_service.client.is_configured()
    scope_id = imbox_service.client.get_scope_id() if configured else None
    return {
        "configured": configured,
        "scope_id": scope_id,
        "channel_id": imbox_service.client._channel_id if configured else None,
    }


# ---------------------------------------------------------------------------
# SSE Live Channel — real-time message push
# ---------------------------------------------------------------------------

@router.get("/chat/listen/{conversation_id}")
async def listen_events(conversation_id: str, request: Request):
    """SSE keep-alive: pushes new messages and status changes in real-time.

    Client opens this connection and receives events as they happen.
    Auth via ?key= (manager) or ?guest_id= / ?token= (client).
    """
    import asyncio
    from datetime import datetime, timezone

    # Validate access: either manager key or conversation owner
    key_param = request.query_params.get("key", "")
    guest_id = request.query_params.get("guest_id", "")
    settings = get_settings()

    is_authorized = False
    if key_param and settings.dashboard_api_key and key_param == settings.dashboard_api_key:
        is_authorized = True  # manager
    elif guest_id:
        owner = chat_service.repo.get_conversation_owner(conversation_id)
        if owner and owner == f"guest:{guest_id}":
            is_authorized = True  # conversation owner
    # Also allow if actor_id matches (portal/telegram)
    token = request.query_params.get("token", "")
    if token:
        try:
            from app.auth.portal import PortalAuth
            actor = PortalAuth().resolve(token)
            owner = chat_service.repo.get_conversation_owner(conversation_id)
            if owner and owner == actor.actor_id:
                is_authorized = True
        except Exception:
            pass

    if not is_authorized:
        raise HTTPException(403, "Access denied")

    async def event_stream():
        last_check = datetime.now(timezone.utc)
        loop = asyncio.get_event_loop()
        while True:
            try:
                # Check for new messages since last check (run sync DB in thread pool)
                new_msgs = await loop.run_in_executor(
                    None, chat_service.repo.get_messages_since, conversation_id, last_check,
                )
                for msg in new_msgs:
                    msg_data = {
                        "id": str(msg["id"]),
                        "role": msg["role"],
                        "content": msg["content"],
                        "metadata": msg.get("metadata") or {},
                        "created_at": msg["created_at"].isoformat() if msg.get("created_at") else None,
                    }
                    yield _sse("new_message", msg_data)
                    # Update last_check to latest message time
                    if msg.get("created_at"):
                        last_check = msg["created_at"]

                # If no new messages, just update timestamp
                if not new_msgs:
                    last_check = datetime.now(timezone.utc)

                # SSE keepalive heartbeat
                yield ": heartbeat\n\n"
            except Exception:
                logger.debug("SSE listen error", exc_info=True)
                yield ": error\n\n"

            await asyncio.sleep(0.5)  # Fast polling for real-time feel

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Manager: hand back to AI
# ---------------------------------------------------------------------------

@router.post("/manager/handback/{conversation_id}")
@router.get("/manager/handback/{conversation_id}")
def manager_handback_to_ai(conversation_id: str, request: Request):
    """Manager returns conversation to AI. Client messages will go to AI again."""
    settings = get_settings()
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip()
    key_param = request.query_params.get("key", "")
    if not settings.dashboard_api_key or (token != settings.dashboard_api_key and key_param != settings.dashboard_api_key):
        raise HTTPException(401, "Invalid API key")

    chat_service.repo.set_manager_active(conversation_id, False)

    # Notify client
    owner = chat_service.repo.get_conversation_owner(conversation_id)
    if owner:
        chat_service.repo.save_message(
            conversation_id=conversation_id,
            role="assistant",
            content="Менеджер вернул диалог Эврике. Можете продолжить общение с ИИ-ассистентом.",
            metadata={"source": "system", "event": "handback"},
        )

    from fastapi.responses import HTMLResponse
    html = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Возврат ИИ</title>
<style>body{font-family:system-ui;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0;background:#1a1a2e;color:#fff}
.card{background:#16213e;padding:40px;border-radius:16px;text-align:center;max-width:400px}
.icon{font-size:64px;margin-bottom:16px}</style></head>
<body><div class="card"><div class="icon">🤖</div><h2>Диалог возвращён Эврике</h2>
<p>Клиент теперь общается с ИИ-ассистентом.</p></div></body></html>"""
    return HTMLResponse(html)


# ---------------------------------------------------------------------------
# Manager: connect (re-activate manager mode)
# ---------------------------------------------------------------------------

@router.post("/manager/connect/{conversation_id}")
@router.get("/manager/connect/{conversation_id}")
def manager_connect(conversation_id: str, request: Request):
    """Manager re-connects to conversation. Client messages go to manager again."""
    settings = get_settings()
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip()
    key_param = request.query_params.get("key", "")
    if not settings.dashboard_api_key or (token != settings.dashboard_api_key and key_param != settings.dashboard_api_key):
        raise HTTPException(401, "Invalid API key")

    chat_service.repo.set_manager_active(conversation_id, True)

    owner = chat_service.repo.get_conversation_owner(conversation_id)
    if owner:
        chat_service.repo.save_message(
            conversation_id=conversation_id,
            role="assistant",
            content="Менеджер подключился к диалогу.",
            metadata={"source": "system", "event": "manager_connected"},
        )

    return {"status": "connected", "conversation_id": conversation_id}


# ---------------------------------------------------------------------------
# Manager approval endpoint (Funnel gate)
# ---------------------------------------------------------------------------

@router.post("/manager/approve/{conversation_id}")
@router.get("/manager/approve/{conversation_id}")
def manager_approve_deal(conversation_id: str, request: Request):
    """Manager approves a deal — unlocks payment for the client.

    Accepts auth via: Authorization header OR ?key= query param.
    Advances the deal from 'manager_review' to 'awaiting_payment'.
    Saves a notification message for the client.
    Returns HTML page for browser (when opened via TG button).
    """
    settings = get_settings()
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip()
    key_param = request.query_params.get("key", "")
    if not settings.dashboard_api_key or (token != settings.dashboard_api_key and key_param != settings.dashboard_api_key):
        from fastapi.responses import HTMLResponse
        return HTMLResponse("<h2>Неверный ключ авторизации</h2>", status_code=401)

    from app.services.funnel import FunnelService

    funnel = FunnelService(repo=chat_service.repo, crm=chat_service.crm)
    already = funnel.is_manager_approved(conversation_id)

    if not already:
        approved = funnel.approve_by_manager(conversation_id)
        if not approved:
            from fastapi.responses import HTMLResponse
            return HTMLResponse("<h2>Сделка не найдена</h2><p>Нет deal mapping для этого разговора.</p>", status_code=404)

        # Save notification message for client
        owner = chat_service.repo.get_conversation_owner(conversation_id)
        if owner:
            chat_service.repo.save_manager_message(
                actor_id=owner,
                content="✅ Менеджер согласовал предложение. Можно оформить оплату!",
                sender_name="Менеджер",
                conversation_id=conversation_id,
            )
            # Also save to conversation messages for history
            chat_service.repo.save_message(
                conversation_id=conversation_id,
                role="assistant",
                content="✅ Менеджер согласовал предложение. Можно оформить оплату!",
                metadata={"source": "manager", "sender_name": "Менеджер", "event": "approved"},
            )

    # Return HTML for browser display
    from fastapi.responses import HTMLResponse
    status_text = "уже было согласовано" if already else "успешно согласовано"
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Согласование</title>
<style>body{{font-family:system-ui;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0;background:#1a1a2e;color:#fff}}
.card{{background:#16213e;padding:40px;border-radius:16px;text-align:center;max-width:400px}}
.icon{{font-size:64px;margin-bottom:16px}}
h2{{margin:0 0 8px}}</style></head>
<body><div class="card"><div class="icon">✅</div><h2>Предложение {status_text}</h2>
<p>Разговор: <code>{conversation_id[:8]}...</code></p>
<p>Клиент получит уведомление.</p></div></body></html>"""
    return HTMLResponse(html)


# ---------------------------------------------------------------------------
# Admin: trigger renewal deals generation
# ---------------------------------------------------------------------------

@router.post("/admin/trigger-renewals")
def trigger_renewals(request: Request):
    """Trigger auto-renewal deal generation for all active students.

    Requires dashboard_api_key in Authorization header.
    """
    settings = get_settings()
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip()
    if not settings.dashboard_api_key or token != settings.dashboard_api_key:
        raise HTTPException(401, "Invalid API key")

    from app.services.renewal import RenewalService

    renewal_svc = RenewalService()
    result = renewal_svc.generate_renewal_deals()
    return result


# ---------------------------------------------------------------------------
# Admin: check stale deals
# ---------------------------------------------------------------------------

@router.post("/admin/check-stale-deals")
def check_stale_deals(request: Request):
    """Check for stale deals past TTL and take action.

    Requires dashboard_api_key in Authorization header.
    """
    settings = get_settings()
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip()
    if not settings.dashboard_api_key or token != settings.dashboard_api_key:
        raise HTTPException(401, "Invalid API key")

    from app.services.funnel import FunnelService

    funnel = FunnelService(repo=chat_service.repo, crm=chat_service.crm)
    result = funnel.check_stale_deals()
    return result


@router.post("/conversations/{conversation_id}/poll")
def poll_new_messages(conversation_id: str, auth: AuthPayload):
    """Poll for new manager messages. Returns undelivered messages and marks them delivered."""
    actor = auth_service.resolve(auth)
    # Allow both owner and manager to poll
    is_manager = actor.channel == Channel.manager
    if not is_manager:
        owner = chat_service.repo.get_conversation_owner(conversation_id)
        if not owner or owner != actor.actor_id:
            return {"messages": []}

    pending = chat_service.repo.get_undelivered_manager_messages(conversation_id)
    if not pending:
        return {"messages": []}

    result = []
    for msg in pending:
        sender = msg.get("sender_name", "Менеджер")
        result.append({
            "id": str(msg["id"]),
            "content": msg["content"],
            "sender": sender,
            "created_at": msg["created_at"].isoformat() if msg.get("created_at") else None,
            "type": "manager",
        })
    chat_service.repo.mark_manager_messages_delivered([str(m["id"]) for m in pending])
    return {"messages": result}


@router.get("/admin/reload-settings")
def reload_settings(request: Request):
    """Bust lru_cache on get_settings() to pick up .env changes without restart."""
    settings = get_settings()
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip()
    key_param = request.query_params.get("key", "")
    if not settings.dashboard_api_key or (token != settings.dashboard_api_key and key_param != settings.dashboard_api_key):
        raise HTTPException(401, "Invalid API key")

    get_settings.cache_clear()
    new_settings = get_settings()
    return {
        "status": "reloaded",
        "manager_chat_id": new_settings.manager_telegram_chat_id or "(empty)",
        "reanimation_pipeline": new_settings.amocrm_reanimation_pipeline_id,
    }

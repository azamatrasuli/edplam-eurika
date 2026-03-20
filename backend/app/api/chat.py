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
    "create_amocrm_ticket": "Создаю обращение...",
}


def _tool_label(name: str) -> str:
    return _TOOL_LABELS.get(name, "Обрабатываю...")
from app.config import get_settings
from app.models.chat import (
    AgentRole,
    AuthPayload,
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


def _notify_manager(reason: str, actor, conversation_id: str, summary: str) -> None:
    """Send Telegram notification to manager about escalation."""
    settings = get_settings()
    chat_id = settings.manager_telegram_chat_id
    bot_token = settings.telegram_bot_token

    if not chat_id or not bot_token:
        logger.warning("Manager Telegram notification not configured")
        return

    display = _escape_html(actor.display_name or actor.actor_id)
    text = (
        f"<b>Эскалация от AI-агента Эврика</b>\n\n"
        f"<b>Клиент:</b> {display}\n"
        f"<b>Канал:</b> {actor.channel.value}\n"
        f"<b>Причина:</b> {_escape_html(reason)}\n"
        f"<b>ID диалога:</b> <code>{_escape_html(conversation_id)}</code>\n\n"
        f"<b>Последнее сообщение агента:</b>\n{_escape_html(summary[:800])}"
    )

    try:
        httpx.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
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

    # Resolve CRM context
    crm_context = chat_service.resolve_crm_context(actor)

    generator = chat_service.stream_answer(
        user_text, ctx.actor, ctx.history,
        conversation_id=ctx.conversation.id,
        crm_context=crm_context,
    )

    full_text: list[str] = []
    usage_tokens = None
    rag_metadata = None

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

    answer = "".join(full_text).strip()
    if not answer:
        answer = "Извините, не смогла сформировать ответ. Попробуйте еще раз."

    chat_service.save_assistant_message(
        conversation_id=ctx.conversation.id,
        text=answer,
        usage_tokens=usage_tokens,
        rag_metadata=rag_metadata,
    )
    imbox_service.forward_agent_response(actor, answer)

    # Handle escalation
    if rag_metadata and rag_metadata.get("escalation"):
        reason = "Агент инициировал эскалацию"
        for tc in rag_metadata.get("tool_calls", []):
            if tc.get("name") == "escalate_to_manager":
                reason = tc.get("args", {}).get("reason", reason)
                break

        chat_service.repo.update_conversation_status(ctx.conversation.id, "escalated")
        _notify_manager(reason, actor, ctx.conversation.id, answer)
        event_tracker.track_escalation(
            ctx.conversation.id, actor.actor_id, reason,
            channel=actor.channel.value,
            agent_role=getattr(actor, "agent_role", "sales"),
        )
        yield _sse("escalation", {"reason": reason, "manager_notified": True})

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
    ctx = chat_service.ensure_conversation(actor, conversation_id=req.conversation_id, force_new=req.force_new)
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
        conversation_id=ctx.conversation.id, actor=actor, greeting=greeting
    )


@router.post("/conversations/{conversation_id}/messages", response_model=ConversationMessagesResponse)
def conversation_messages(conversation_id: str, auth: AuthPayload) -> ConversationMessagesResponse:
    actor = auth_service.resolve(auth)
    enrich_ctx(user_id=actor.actor_id, conversation_id=conversation_id)
    # Verify the conversation belongs to this actor
    conv = chat_service.repo.get_conversation_owner(conversation_id)
    if not conv or conv != actor.actor_id:
        raise HTTPException(403, "Access denied")
    messages = chat_service.get_messages(conversation_id)
    return ConversationMessagesResponse(conversation_id=conversation_id, messages=messages)


@router.post("/chat/stream")
def chat_stream(req: ChatStreamRequest) -> StreamingResponse:
    actor = auth_service.resolve(req.auth)
    actor = actor.model_copy(update={"agent_role": req.agent_role})
    enrich_ctx(user_id=actor.actor_id, agent_role=req.agent_role.value)
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

    role_enum = AgentRole(agent_role) if agent_role in ("sales", "support") else AgentRole.sales
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


@router.post("/amocrm/chat/webhook/{scope_id}")
async def amocrm_chat_webhook(scope_id: str, request: Request):
    """Receive manager replies from amoCRM imBox. Always returns 200."""
    body = await request.body()
    body_str = body.decode("utf-8", errors="replace")

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

    event_type = payload.get("event_type")
    inner = payload.get("payload", payload)

    if event_type == "new_message":
        conversation_id = inner.get("conversation_id", "")
        sender = inner.get("sender", {})
        message = inner.get("message", {})
        text = message.get("text", "")
        msgid = inner.get("msgid", "")

        logger.info("Manager reply via imBox: conv=%s sender=%s", conversation_id, sender.get("name"))

        actor_id = imbox_service.repo.find_actor_by_chat_conversation_id(conversation_id)
        if actor_id and text:
            imbox_service.repo.save_manager_message(
                actor_id=actor_id,
                content=text,
                conversation_id=conversation_id,
                amocrm_msgid=msgid,
                sender_name=sender.get("name"),
            )

    return {"status": "ok"}

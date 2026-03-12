from __future__ import annotations

import json
import logging
from collections.abc import Generator

import httpx
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.auth.service import AuthService
from app.config import get_settings
from app.models.chat import (
    AgentRole,
    AuthPayload,
    ChatStreamRequest,
    ConversationMessagesResponse,
    StartConversationRequest,
    StartConversationResponse,
)
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


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _notify_manager(reason: str, actor, conversation_id: str, summary: str) -> None:
    """Send Telegram notification to manager about escalation."""
    settings = get_settings()
    chat_id = settings.manager_telegram_chat_id
    bot_token = settings.telegram_bot_token

    if not chat_id or not bot_token:
        logger.warning("Manager Telegram notification not configured")
        return

    display = actor.display_name or actor.actor_id
    text = (
        f"<b>Эскалация от AI-агента Эврика</b>\n\n"
        f"<b>Клиент:</b> {display}\n"
        f"<b>Канал:</b> {actor.channel.value}\n"
        f"<b>Причина:</b> {reason}\n"
        f"<b>ID диалога:</b> <code>{conversation_id}</code>\n\n"
        f"<b>Последнее сообщение агента:</b>\n{summary[:800]}"
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
                yield _sse("tool_call", {"name": event.name})
    except StopIteration as stop:
        result = stop.value
        if result:
            usage_tokens = result.usage_tokens
            rag_metadata = result.rag_metadata

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
        yield _sse("escalation", {"reason": reason, "manager_notified": True})

    yield _sse("done", {"text": answer, "usage_tokens": usage_tokens})


# ---- endpoints -----------------------------------------------------------

@router.post("/conversations/start", response_model=StartConversationResponse)
def start_conversation(req: StartConversationRequest) -> StartConversationResponse:
    actor = auth_service.resolve(req.auth)
    actor = actor.model_copy(update={"agent_role": req.agent_role})
    ctx = chat_service.ensure_conversation(actor, conversation_id=req.conversation_id)
    # Generate greeting only for new conversations (no history)
    if not ctx.history:
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
    ctx = chat_service.ensure_conversation(actor, conversation_id=req.conversation_id)
    return StreamingResponse(
        _make_stream(req.message, actor, ctx),
        media_type="text/event-stream",
    )


@router.post("/chat/transcribe")
async def chat_transcribe(audio: UploadFile = File(...)) -> dict:
    """Accept audio, transcribe via Whisper, return text (no LLM call)."""
    ext = (audio.filename or "audio.webm").rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_FORMATS:
        raise HTTPException(400, f"Unsupported format: {ext}")
    audio_bytes = await audio.read()
    if len(audio_bytes) > 25 * 1024 * 1024:
        raise HTTPException(413, "Audio file too large")
    transcript = speech_service.transcribe(audio_bytes, filename=audio.filename or f"voice.{ext}")
    if not transcript:
        raise HTTPException(502, "Speech-to-text unavailable")
    return {"transcript": transcript}


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
        raise HTTPException(400, f"Unsupported audio format: {ext}. Allowed: {', '.join(sorted(ALLOWED_FORMATS))}")

    audio_bytes = await audio.read()
    if len(audio_bytes) > 25 * 1024 * 1024:
        raise HTTPException(413, "Audio file too large (max 25MB)")

    transcript = speech_service.transcribe(audio_bytes, filename=audio.filename or f"voice.{ext}")
    if not transcript:
        raise HTTPException(502, "Speech-to-text service unavailable")

    role_enum = AgentRole(agent_role) if agent_role in ("sales", "support") else AgentRole.sales
    auth = AuthPayload.model_validate_json(auth_json)
    actor = auth_service.resolve(auth)
    actor = actor.model_copy(update={"agent_role": role_enum})
    ctx = chat_service.ensure_conversation(actor, conversation_id=conversation_id)

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
    if signature and not imbox_service.client.verify_webhook_signature(body, signature):
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

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Channel(str, Enum):
    portal = "portal"
    telegram = "telegram"
    external = "external"


class AuthPayload(BaseModel):
    portal_token: str | None = None
    telegram_init_data: str | None = None
    external_token: str | None = None


class ActorContext(BaseModel):
    channel: Channel
    actor_id: str
    display_name: str | None = None
    phone: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class StartConversationRequest(BaseModel):
    auth: AuthPayload
    conversation_id: str | None = None


class StartConversationResponse(BaseModel):
    conversation_id: str
    actor: ActorContext
    greeting: str


class ChatStreamRequest(BaseModel):
    auth: AuthPayload
    conversation_id: str | None = None
    message: str = Field(min_length=1, max_length=4000)


class ChatMessage(BaseModel):
    role: str
    content: str
    created_at: datetime


class ConversationMessagesResponse(BaseModel):
    conversation_id: str
    messages: list[ChatMessage]

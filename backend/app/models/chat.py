from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


class Channel(str, Enum):
    portal = "portal"
    telegram = "telegram"
    external = "external"
    guest = "guest"


class AgentRole(str, Enum):
    sales = "sales"
    support = "support"


class AuthPayload(BaseModel):
    portal_token: str | None = None
    telegram_init_data: str | None = None
    external_token: str | None = None
    guest_id: str | None = None


class ActorContext(BaseModel):
    channel: Channel
    actor_id: str
    display_name: str | None = None
    phone: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    agent_role: AgentRole = AgentRole.sales

    @model_validator(mode="after")
    def _sanitize_display_name(self):
        """Strip HTML tags from display_name to prevent XSS."""
        if self.display_name:
            import re
            self.display_name = re.sub(r"<[^>]*>", "", self.display_name).strip() or None
        return self


class StartConversationRequest(BaseModel):
    auth: AuthPayload
    conversation_id: str | None = None
    agent_role: AgentRole = AgentRole.sales
    force_new: bool = False


class StartConversationResponse(BaseModel):
    conversation_id: str
    actor: ActorContext
    greeting: str


class ChatStreamRequest(BaseModel):
    auth: AuthPayload
    conversation_id: str | None = None
    message: str = Field(min_length=1, max_length=4000)
    agent_role: AgentRole = AgentRole.sales


class ChatMessage(BaseModel):
    role: str
    content: str
    created_at: datetime


class ConversationMessagesResponse(BaseModel):
    conversation_id: str
    messages: list[ChatMessage]


# ---- Chat History models -------------------------------------------------

class ConversationListRequest(BaseModel):
    auth: AuthPayload
    agent_role: AgentRole | None = None
    offset: int = 0
    limit: int = Field(default=20, le=50)
    include_archived: bool = False


class ConversationListItem(BaseModel):
    id: str
    title: str | None = None
    agent_role: str
    status: str = "active"
    message_count: int = 0
    last_user_message: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    archived_at: datetime | None = None


class ConversationListResponse(BaseModel):
    conversations: list[ConversationListItem]
    total: int
    has_more: bool


class ConversationSearchRequest(BaseModel):
    auth: AuthPayload
    query: str = Field(min_length=2, max_length=200)
    agent_role: AgentRole | None = None


class ConversationRenameRequest(BaseModel):
    auth: AuthPayload
    title: str = Field(min_length=1, max_length=100)

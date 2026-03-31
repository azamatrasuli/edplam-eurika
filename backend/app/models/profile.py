"""Models for the user profile API."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.chat import AuthPayload


# ---- Request models --------------------------------------------------------

class ProfileRequest(BaseModel):
    auth: AuthPayload


class ProfileUpdateRequest(BaseModel):
    auth: AuthPayload
    display_name: str | None = Field(default=None, max_length=100)
    email: str | None = Field(default=None, max_length=200)


class MemoryDeleteRequest(BaseModel):
    auth: AuthPayload


class MemoryClearRequest(BaseModel):
    auth: AuthPayload


# ---- Response models -------------------------------------------------------

class ChildInfo(BaseModel):
    fio: str | None = None
    grade: int | None = None
    product_name: str | None = None


class MemoryItem(BaseModel):
    """A single memory fact, formatted for user display."""
    id: str
    text: str  # Human-readable: "Живёт в Калининграде"
    fact_type: str  # entity, preference, decision, etc.
    created_at: datetime | None = None


class ProfileStats(BaseModel):
    conversation_count: int = 0
    memory_count: int = 0
    last_active_at: datetime | None = None


class ProfileResponse(BaseModel):
    actor_id: str
    display_name: str | None = None
    fio: str | None = None
    phone: str | None = None
    client_type: str | None = None
    user_role: str | None = None
    grade: int | None = None
    children: list[ChildInfo] = Field(default_factory=list)
    dms_verified: bool = False
    avatar: str | None = None
    portal_role: int | None = None       # 3=parent, 4=student, 5=guest
    is_minor: bool | None = None
    memories: list[MemoryItem] = Field(default_factory=list)
    stats: ProfileStats = Field(default_factory=ProfileStats)
    completeness: float = 0.0  # 0.0 to 1.0


class MemoryListResponse(BaseModel):
    memories: list[MemoryItem] = Field(default_factory=list)
    total: int = 0


# ---- Consent models -------------------------------------------------------

class ConsentGrantRequest(BaseModel):
    auth: AuthPayload
    purpose_id: str
    method: str = "settings"


class ConsentRevokeRequest(BaseModel):
    auth: AuthPayload
    purpose_id: str
    method: str = "settings"


class ConsentItem(BaseModel):
    purpose_id: str
    title_ru: str
    description: str
    required: bool
    granted: bool
    version: str
    granted_at: datetime | None = None
    revoked_at: datetime | None = None
    is_minor: bool | None = None


class ConsentStatusResponse(BaseModel):
    consents: list[ConsentItem] = Field(default_factory=list)
    all_required_granted: bool = False
    is_minor_actor: bool | None = None
    minor_age: int | None = None


# ---- Data export & deletion models -----------------------------------------

class ExportRequest(BaseModel):
    auth: AuthPayload


class ExportResponse(BaseModel):
    request_id: str
    status: str


class DeletionRequest(BaseModel):
    auth: AuthPayload
    reason: str | None = None


class DeletionStatusResponse(BaseModel):
    has_pending: bool = False
    request_id: str | None = None
    execute_after: datetime | None = None
    created_at: datetime | None = None

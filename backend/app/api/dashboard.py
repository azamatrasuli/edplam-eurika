"""Dashboard API — metrics, conversations, escalations, unanswered questions."""

from __future__ import annotations

import logging
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings
from app.db.dashboard import DashboardRepository
from app.models.dashboard import (
    DashboardMetrics,
    PaginatedConversations,
    PaginatedEscalations,
    UnansweredQuestion,
)

logger = logging.getLogger("api.dashboard")
router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])
security = HTTPBearer()


def _verify_dashboard_key(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    settings = get_settings()
    if not settings.dashboard_api_key:
        raise HTTPException(503, "Dashboard not configured — DASHBOARD_API_KEY is empty")
    if credentials.credentials != settings.dashboard_api_key:
        raise HTTPException(401, "Invalid dashboard API key")
    return credentials.credentials


def _default_dates(
    date_from: date | None, date_to: date | None,
) -> tuple[date, date]:
    today = date.today()
    return date_from or (today - timedelta(days=7)), date_to or today


@router.get("/metrics", response_model=DashboardMetrics)
def dashboard_metrics(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    channel: str | None = Query(default=None),
    agent_role: str | None = Query(default=None),
    _key: str = Depends(_verify_dashboard_key),
) -> DashboardMetrics:
    d_from, d_to = _default_dates(date_from, date_to)
    repo = DashboardRepository()
    data = repo.get_metrics(d_from, d_to, channel=channel, agent_role=agent_role)
    return DashboardMetrics(**data)


@router.get("/conversations", response_model=PaginatedConversations)
def dashboard_conversations(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    channel: str | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    _key: str = Depends(_verify_dashboard_key),
) -> PaginatedConversations:
    d_from, d_to = _default_dates(date_from, date_to)
    repo = DashboardRepository()
    data = repo.get_conversations(d_from, d_to, channel=channel, status=status, page=page, per_page=per_page)
    return PaginatedConversations(**data)


@router.get("/escalations", response_model=PaginatedEscalations)
def dashboard_escalations(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=20, ge=1, le=100),
    _key: str = Depends(_verify_dashboard_key),
) -> PaginatedEscalations:
    d_from, d_to = _default_dates(date_from, date_to)
    repo = DashboardRepository()
    data = repo.get_escalations(d_from, d_to, page=page, per_page=per_page)
    return PaginatedEscalations(**data)


@router.post("/escalations/{conversation_id}/resolve")
def resolve_escalation(
    conversation_id: str,
    _key: str = Depends(_verify_dashboard_key),
) -> dict:
    """De-escalate a conversation. Called from dashboard or manager tools."""
    from app.db.repository import ConversationRepository
    from app.db.events import EventTracker

    repo = ConversationRepository()
    resolved = repo.resolve_escalation(conversation_id, resolved_by="dashboard")
    if not resolved:
        raise HTTPException(404, "Conversation not found or not escalated")

    EventTracker().track(
        "escalation_resolved",
        conversation_id=conversation_id,
        data={"resolved_by": "dashboard", "source": "dashboard_api"},
    )
    return {"status": "resolved", "conversation_id": conversation_id}


@router.get("/unanswered", response_model=list[UnansweredQuestion])
def dashboard_unanswered(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    _key: str = Depends(_verify_dashboard_key),
) -> list[UnansweredQuestion]:
    d_from, d_to = _default_dates(date_from, date_to)
    repo = DashboardRepository()
    data = repo.get_unanswered(d_from, d_to, limit=limit)
    return [UnansweredQuestion(**item) for item in data]

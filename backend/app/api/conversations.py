from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from app.auth.service import AuthService
from app.db.repository import ConversationRepository
from app.models.chat import (
    AuthPayload,
    ConversationListItem,
    ConversationListRequest,
    ConversationListResponse,
    ConversationRenameRequest,
    ConversationSearchRequest,
)

logger = logging.getLogger("api.conversations")

router = APIRouter(prefix="/api/v1/conversations", tags=["conversations"])
auth_service = AuthService()
repo = ConversationRepository()


@router.post("/list", response_model=ConversationListResponse)
def list_conversations(req: ConversationListRequest) -> ConversationListResponse:
    actor = auth_service.resolve(req.auth)
    agent_role = req.agent_role.value if req.agent_role else None
    convs, total = repo.list_conversations(
        actor_id=actor.actor_id,
        agent_role=agent_role,
        offset=req.offset,
        limit=req.limit,
        include_archived=req.include_archived,
    )
    items = [
        ConversationListItem(
            id=c.id,
            title=c.title,
            agent_role=c.agent_role,
            status=c.status,
            message_count=c.message_count,
            last_user_message=c.last_user_message,
            created_at=c.created_at,
            updated_at=c.updated_at,
            archived_at=c.archived_at,
        )
        for c in convs
    ]
    return ConversationListResponse(
        conversations=items,
        total=total,
        has_more=(req.offset + req.limit) < total,
    )


@router.post("/search", response_model=ConversationListResponse)
def search_conversations(req: ConversationSearchRequest) -> ConversationListResponse:
    actor = auth_service.resolve(req.auth)
    agent_role = req.agent_role.value if req.agent_role else None
    convs = repo.search_conversations(
        actor_id=actor.actor_id,
        query=req.query,
        agent_role=agent_role,
    )
    items = [
        ConversationListItem(
            id=c.id,
            title=c.title,
            agent_role=c.agent_role,
            status=c.status,
            message_count=c.message_count,
            last_user_message=c.last_user_message,
            created_at=c.created_at,
            updated_at=c.updated_at,
            archived_at=c.archived_at,
        )
        for c in convs
    ]
    return ConversationListResponse(conversations=items, total=len(items), has_more=False)


@router.post("/{conversation_id}/archive")
def archive_conversation(conversation_id: str, auth: AuthPayload):
    actor = auth_service.resolve(auth)
    ok = repo.archive_conversation(conversation_id, actor.actor_id)
    if not ok:
        raise HTTPException(404, "Conversation not found or already archived")
    return {"status": "archived", "conversation_id": conversation_id}


@router.post("/{conversation_id}/unarchive")
def unarchive_conversation(conversation_id: str, auth: AuthPayload):
    actor = auth_service.resolve(auth)
    ok = repo.unarchive_conversation(conversation_id, actor.actor_id)
    if not ok:
        raise HTTPException(404, "Conversation not found or not archived")
    return {"status": "unarchived", "conversation_id": conversation_id}


@router.post("/{conversation_id}/rename")
def rename_conversation(conversation_id: str, req: ConversationRenameRequest):
    actor = auth_service.resolve(req.auth)
    owner = repo.get_conversation_owner(conversation_id)
    if not owner or owner != actor.actor_id:
        raise HTTPException(403, "Access denied")
    repo.update_conversation_title(conversation_id, req.title)
    return {"status": "renamed", "conversation_id": conversation_id, "title": req.title}


@router.post("/{conversation_id}/delete")
def delete_conversation(conversation_id: str, auth: AuthPayload):
    actor = auth_service.resolve(auth)
    ok = repo.delete_conversation(conversation_id, actor.actor_id)
    if not ok:
        raise HTTPException(404, "Conversation not found")
    return {"status": "deleted", "conversation_id": conversation_id}

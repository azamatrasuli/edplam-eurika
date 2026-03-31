"""User profile API — view, update, manage memory, stats."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request

from app.auth.service import AuthService
from app.db.memory_repository import MemoryRepository
from app.db.repository import ConversationRepository
from app.logging_config import enrich_ctx
from app.models.profile import (
    ChildInfo,
    DeletionRequest,
    DeletionStatusResponse,
    ExportRequest,
    ExportResponse,
    MemoryDeleteRequest,
    MemoryClearRequest,
    MemoryItem,
    MemoryListResponse,
    ProfileRequest,
    ProfileResponse,
    ProfileStats,
    ProfileUpdateRequest,
)
from app.services.onboarding import OnboardingService

logger = logging.getLogger("api.profile")

router = APIRouter(prefix="/api/v1/profile", tags=["profile"])
auth_service = AuthService()
repo = ConversationRepository()
mem_repo = MemoryRepository()
onboarding = OnboardingService()


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def _format_atom_text(atom: dict) -> str:
    """Convert raw atom (subject/predicate/object) to human-readable text."""
    subj = atom.get("subject", "")
    pred = atom.get("predicate", "")
    obj = atom.get("object", "")
    if obj:
        return f"{subj} {pred} {obj}".strip()
    return f"{subj} {pred}".strip()


def _calc_completeness(profile: dict | None) -> float:
    """Calculate profile completeness 0.0–1.0."""
    if not profile:
        return 0.0
    weights = {
        "display_name": 0.15,
        "phone": 0.20,
        "client_type": 0.10,
        "user_role": 0.10,
        "children": 0.15,
        "grade": 0.10,
        "dms_verified": 0.20,
    }
    score = 0.0
    for field, weight in weights.items():
        val = profile.get(field)
        if val is not None and val != "" and val != [] and val is not False:
            score += weight
    return round(min(score, 1.0), 2)


@router.post("", response_model=ProfileResponse)
def get_profile(req: ProfileRequest) -> ProfileResponse:
    """Get full user profile with memories and stats."""
    actor = auth_service.resolve(req.auth)
    enrich_ctx(user_id=actor.actor_id)

    profile = repo.get_user_profile(actor.actor_id) or {}

    # Build children list
    children = []
    raw_children = profile.get("children") or []
    dms_students = (profile.get("dms_data") or {}).get("students", [])
    for i, child in enumerate(raw_children):
        product = dms_students[i].get("product_name") if i < len(dms_students) else None
        children.append(ChildInfo(
            fio=child.get("fio"),
            grade=child.get("grade"),
            product_name=product,
        ))

    # Memory atoms (human-readable)
    raw_atoms = mem_repo.list_user_atoms(actor.actor_id, limit=20)
    memories = [
        MemoryItem(
            id=str(a["id"]),
            text=_format_atom_text(a),
            fact_type=a.get("fact_type", "entity"),
            created_at=a.get("created_at"),
        )
        for a in raw_atoms
    ]

    # Stats
    raw_stats = repo.get_profile_stats(actor.actor_id)
    memory_count = mem_repo.count_user_atoms(actor.actor_id)

    # Fallback: если БД пустая, использовать данные из JWT (ActorContext)
    meta = actor.metadata or {}
    p_name   = profile.get("display_name") or actor.display_name
    p_phone  = profile.get("phone") or actor.phone
    p_avatar = profile.get("avatar") or meta.get("avatar")
    p_portal_role = profile.get("portal_role") or (meta.get("user_role") if isinstance(meta.get("user_role"), int) else None)
    p_is_minor = profile.get("is_minor")
    if p_is_minor is None:
        p_is_minor = meta.get("is_minor")

    merged = {**profile, "display_name": p_name, "phone": p_phone, "avatar": p_avatar}

    return ProfileResponse(
        actor_id=actor.actor_id,
        display_name=p_name,
        fio=profile.get("fio"),
        phone=p_phone,
        client_type=profile.get("client_type"),
        user_role=profile.get("user_role"),
        grade=profile.get("grade"),
        children=children,
        dms_verified=profile.get("dms_verified", False),
        avatar=p_avatar,
        portal_role=p_portal_role,
        is_minor=p_is_minor,
        memories=memories,
        stats=ProfileStats(
            conversation_count=raw_stats["conversation_count"],
            memory_count=memory_count,
            last_active_at=raw_stats.get("last_active_at"),
        ),
        completeness=_calc_completeness(merged),
    )


@router.post("/update")
def update_profile(req: ProfileUpdateRequest):
    """Update editable profile fields (display_name, email)."""
    actor = auth_service.resolve(req.auth)
    enrich_ctx(user_id=actor.actor_id)

    if req.display_name is not None:
        repo.update_profile_display_name(actor.actor_id, req.display_name.strip())

    return {"status": "updated"}


@router.post("/memory", response_model=MemoryListResponse)
def list_memories(req: ProfileRequest) -> MemoryListResponse:
    """List all memory facts the agent knows about this user."""
    actor = auth_service.resolve(req.auth)
    enrich_ctx(user_id=actor.actor_id)

    raw_atoms = mem_repo.list_user_atoms(actor.actor_id, limit=50)
    memories = [
        MemoryItem(
            id=str(a["id"]),
            text=_format_atom_text(a),
            fact_type=a.get("fact_type", "entity"),
            created_at=a.get("created_at"),
        )
        for a in raw_atoms
    ]
    return MemoryListResponse(memories=memories, total=len(memories))


@router.post("/memory/{atom_id}/delete")
def delete_memory(atom_id: str, req: MemoryDeleteRequest):
    """Delete a single memory fact."""
    actor = auth_service.resolve(req.auth)
    enrich_ctx(user_id=actor.actor_id)

    ok = mem_repo.delete_atom(atom_id, actor.actor_id)
    if not ok:
        raise HTTPException(404, "Memory fact not found")
    return {"status": "deleted", "atom_id": atom_id}


@router.post("/memory/clear")
def clear_memories(req: MemoryClearRequest):
    """Delete all memory facts for this user."""
    actor = auth_service.resolve(req.auth)
    enrich_ctx(user_id=actor.actor_id)

    count = mem_repo.clear_user_atoms(actor.actor_id)
    return {"status": "cleared", "deleted_count": count}


# ---- Data export & deletion ------------------------------------------------

@router.post("/export", response_model=ExportResponse)
def export_data(req: ExportRequest, request: Request):
    """Export all user data as JSON."""
    from app.services.data_lifecycle import DataLifecycleService

    actor = auth_service.resolve(req.auth)
    enrich_ctx(user_id=actor.actor_id)

    svc = DataLifecycleService()
    request_id = svc.create_export_request(
        actor_id=actor.actor_id,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    if not request_id:
        raise HTTPException(500, "Failed to create export")
    return ExportResponse(request_id=request_id, status="ready")


@router.post("/export/{request_id}/download")
def download_export(request_id: str, req: ProfileRequest):
    """Download exported data."""
    from fastapi.responses import JSONResponse
    from app.services.data_lifecycle import DataLifecycleService

    actor = auth_service.resolve(req.auth)
    enrich_ctx(user_id=actor.actor_id)

    svc = DataLifecycleService()
    data = svc.get_export_data(request_id, actor.actor_id)
    if not data:
        raise HTTPException(404, "Export not found")
    return JSONResponse(
        content=data,
        headers={"Content-Disposition": f"attachment; filename=eurika_export_{actor.actor_id[:12]}.json"},
    )


@router.post("/delete", response_model=DeletionStatusResponse)
def request_deletion(req: DeletionRequest, request: Request):
    """Request account deletion with 14-day grace period."""
    from app.services.data_lifecycle import DataLifecycleService

    actor = auth_service.resolve(req.auth)
    enrich_ctx(user_id=actor.actor_id)

    svc = DataLifecycleService()

    # Check if already pending
    pending = svc.get_pending_deletion(actor.actor_id)
    if pending:
        return DeletionStatusResponse(
            has_pending=True,
            request_id=pending["id"],
            execute_after=pending.get("execute_after"),
            created_at=pending.get("created_at"),
        )

    request_id = svc.create_deletion_request(
        actor_id=actor.actor_id,
        reason=req.reason,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    if not request_id:
        raise HTTPException(500, "Failed to create deletion request")

    deletion = svc.get_pending_deletion(actor.actor_id)
    return DeletionStatusResponse(
        has_pending=True,
        request_id=request_id,
        execute_after=deletion.get("execute_after") if deletion else None,
        created_at=deletion.get("created_at") if deletion else None,
    )


@router.post("/delete/cancel")
def cancel_deletion(req: ProfileRequest):
    """Cancel pending deletion during grace period."""
    from app.services.data_lifecycle import DataLifecycleService

    actor = auth_service.resolve(req.auth)
    enrich_ctx(user_id=actor.actor_id)

    svc = DataLifecycleService()
    ok = svc.cancel_deletion(actor.actor_id)
    if not ok:
        raise HTTPException(404, "No pending deletion to cancel")
    return {"status": "cancelled"}


@router.post("/delete/status", response_model=DeletionStatusResponse)
def deletion_status(req: ProfileRequest):
    """Check if there is a pending deletion request."""
    from app.services.data_lifecycle import DataLifecycleService

    actor = auth_service.resolve(req.auth)
    enrich_ctx(user_id=actor.actor_id)

    svc = DataLifecycleService()
    pending = svc.get_pending_deletion(actor.actor_id)
    if not pending:
        return DeletionStatusResponse(has_pending=False)
    return DeletionStatusResponse(
        has_pending=True,
        request_id=pending["id"],
        execute_after=pending.get("execute_after"),
        created_at=pending.get("created_at"),
    )

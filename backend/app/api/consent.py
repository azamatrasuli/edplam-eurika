"""Consent management API — ФЗ-152 compliance."""
from __future__ import annotations

import logging
from datetime import date, datetime

from fastapi import APIRouter, HTTPException, Request

from app.auth.service import AuthService
from app.db.consent_repository import ConsentRepository
from app.logging_config import enrich_ctx
from app.models.profile import (
    ConsentGrantRequest,
    ConsentItem,
    ConsentRevokeRequest,
    ConsentStatusResponse,
    ProfileRequest,
)

logger = logging.getLogger("api.consent")

router = APIRouter(prefix="/api/v1/consent", tags=["consent"])
auth_service = AuthService()
consent_repo = ConsentRepository()


def _compute_age(birth_date_str: str | None) -> int | None:
    """Compute age from birth_date string (ISO or dd.mm.yyyy)."""
    if not birth_date_str:
        return None
    try:
        for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
            try:
                bd = datetime.strptime(birth_date_str, fmt).date()
                today = date.today()
                return today.year - bd.year - ((today.month, today.day) < (bd.month, bd.day))
            except ValueError:
                continue
        return None
    except Exception:
        return None


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


@router.post("/status", response_model=ConsentStatusResponse)
def consent_status(req: ProfileRequest, request: Request) -> ConsentStatusResponse:
    """Get all consent statuses for the current user."""
    actor = auth_service.resolve(req.auth)
    enrich_ctx(user_id=actor.actor_id)

    is_minor = actor.metadata.get("is_minor")
    minor_age = None
    if is_minor is None:
        minor_age = _compute_age(actor.metadata.get("birth_date"))
        if minor_age is not None and minor_age < 18:
            is_minor = True

    records = consent_repo.get_user_consents(actor.actor_id)
    items = [
        ConsentItem(
            purpose_id=r.purpose_id,
            title_ru=r.title_ru,
            description=r.description,
            required=r.required,
            granted=r.granted,
            version=r.version,
            granted_at=r.granted_at,
            revoked_at=r.revoked_at,
            is_minor=r.is_minor,
        )
        for r in records
    ]
    all_required = all(c.granted for c in items if c.required)
    return ConsentStatusResponse(
        consents=items,
        all_required_granted=all_required,
        is_minor_actor=is_minor,
        minor_age=minor_age if is_minor else None,
    )


@router.post("/grant")
def grant_consent(req: ConsentGrantRequest, request: Request):
    """Grant consent for a specific purpose."""
    actor = auth_service.resolve(req.auth)
    enrich_ctx(user_id=actor.actor_id)

    is_minor = actor.metadata.get("is_minor")

    ok = consent_repo.grant_consent(
        actor_id=actor.actor_id,
        purpose_id=req.purpose_id,
        method=req.method,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        is_minor=is_minor,
    )
    if not ok:
        raise HTTPException(500, "Failed to save consent")
    return {"status": "granted", "purpose_id": req.purpose_id}


@router.post("/revoke")
def revoke_consent(req: ConsentRevokeRequest, request: Request):
    """Revoke consent for a specific purpose. Triggers side effects (e.g., memory clear)."""
    actor = auth_service.resolve(req.auth)
    enrich_ctx(user_id=actor.actor_id)

    is_minor = actor.metadata.get("is_minor")

    # Check if this is a required consent
    purposes = consent_repo.get_purposes()
    purpose = next((p for p in purposes if p.id == req.purpose_id), None)
    if not purpose:
        raise HTTPException(404, "Unknown consent purpose")

    ok = consent_repo.revoke_consent(
        actor_id=actor.actor_id,
        purpose_id=req.purpose_id,
        method=req.method,
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent"),
        is_minor=is_minor,
    )
    if not ok:
        raise HTTPException(500, "Failed to revoke consent")

    result = {"status": "revoked", "purpose_id": req.purpose_id}
    if purpose.required:
        result["warning"] = "Отозвано обязательное согласие. Функции чата будут ограничены."
    if req.purpose_id == "ai_memory":
        result["side_effect"] = "Вся сохранённая память очищена."
    return result

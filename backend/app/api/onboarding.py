from __future__ import annotations

import logging

from fastapi import APIRouter

from app.auth.service import AuthService
from app.logging_config import enrich_ctx
from app.models.onboarding import (
    OnboardingVerifyRequest,
    OnboardingVerifyResponse,
    ProfileCheckRequest,
    ProfileCheckResponse,
    UserProfile,
)
from app.services.onboarding import OnboardingService

logger = logging.getLogger("api.onboarding")

router = APIRouter(prefix="/api/v1", tags=["onboarding"])
auth_service = AuthService()
onboarding_service = OnboardingService()


@router.post("/profile/check", response_model=ProfileCheckResponse)
def check_profile(req: ProfileCheckRequest) -> ProfileCheckResponse:
    """Check if the actor already has an onboarding profile."""
    actor = auth_service.resolve(req.auth)
    enrich_ctx(user_id=actor.actor_id)
    profile = onboarding_service.check_profile(actor.actor_id)
    return ProfileCheckResponse(
        has_profile=profile is not None,
        profile=profile,
    )


@router.post("/onboarding/verify", response_model=OnboardingVerifyResponse)
def verify_onboarding(req: OnboardingVerifyRequest) -> OnboardingVerifyResponse:
    """Verify user data against DMS and save the onboarding profile."""
    actor = auth_service.resolve(req.auth)
    enrich_ctx(user_id=actor.actor_id)
    return onboarding_service.verify_and_save(actor, req)

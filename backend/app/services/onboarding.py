from __future__ import annotations

import logging

from app.db.repository import ConversationRepository
from app.integrations.dms import DMSSearchResult, get_dms_service
from app.models.chat import ActorContext
from app.models.onboarding import (
    DMSContactData,
    DMSStudentData,
    OnboardingVerifyRequest,
    OnboardingVerifyResponse,
    UserProfile,
)

logger = logging.getLogger("onboarding")


def normalize_phone(phone: str) -> str:
    """Strip non-digits. Replace leading 8 with 7 (Russian convention)."""
    digits = "".join(c for c in phone if c.isdigit())
    if digits and digits[0] == "8":
        digits = "7" + digits[1:]
    return digits


class OnboardingService:
    def __init__(self) -> None:
        self.repo = ConversationRepository()
        self.dms = get_dms_service()

    def check_profile(self, actor_id: str) -> UserProfile | None:
        row = self.repo.get_user_profile(actor_id)
        if not row:
            return None
        return UserProfile(**row)

    def verify_and_save(
        self, actor: ActorContext, req: OnboardingVerifyRequest
    ) -> OnboardingVerifyResponse:
        phone = normalize_phone(req.phone)
        logger.info(
            "Onboarding verify: actor=%s client_type=%s phone=%s",
            actor.actor_id, req.client_type, phone,
        )

        # Search DMS by phone
        dms_result = self.dms.search_contact_by_phone(phone)

        # Determine verification status
        if req.client_type == "existing":
            status = "found" if dms_result else "not_found"
        else:
            status = "unexpected_found" if dms_result else "new_lead"

        # Build DMS response data
        dms_data = self._build_dms_data(dms_result) if dms_result else None

        # Build children list for storage
        children = [{"fio": s.fio, "grade": s.grade} for s in req.students]

        # Save profile
        profile_id = self.repo.save_user_profile(
            actor_id=actor.actor_id,
            client_type=req.client_type,
            user_role=req.user_role,
            phone=phone,
            phone_raw=req.phone,
            fio=req.fio,
            grade=req.grade,
            children=children,
            dms_verified=dms_result is not None,
            dms_contact_id=dms_result.contact.contact_id if dms_result else None,
            dms_data=dms_data.model_dump() if dms_data else None,
            verification_status=status,
        )

        logger.info("Onboarding result: status=%s profile_id=%s", status, profile_id)

        return OnboardingVerifyResponse(
            status=status,
            profile_id=profile_id or "",
            dms_data=dms_data,
        )

    def get_profile_context_for_llm(self, actor_id: str) -> str:
        """Build context string for injection into LLM system messages."""
        profile = self.check_profile(actor_id)
        if not profile:
            return ""

        client_type_ru = "действующий клиент" if profile.client_type == "existing" else "новый клиент"
        role_ru = "родитель" if profile.user_role == "parent" else "ученик"

        parts = [
            "Профиль клиента (из онбординга):",
            f"- Статус: {client_type_ru}",
            f"- Роль: {role_ru}",
            f"- Телефон: {profile.phone}",
        ]

        if profile.fio:
            parts.append(f"- ФИО: {profile.fio}")
        if profile.grade:
            parts.append(f"- Класс: {profile.grade}")

        if profile.children:
            for child in profile.children:
                parts.append(f"- Ученик: {child.get('fio', '?')}, класс {child.get('grade', '?')}")

        if profile.dms_verified:
            parts.append("- Верификация DMS: подтверждён")
            if profile.dms_data:
                students = profile.dms_data.get("students", [])
                for s in students:
                    if s.get("product_name"):
                        parts.append(f"- Продукт: {s['product_name']}")
        else:
            parts.append("- Верификация DMS: не подтверждён")

        return "\n".join(parts)

    @staticmethod
    def _build_dms_data(result: DMSSearchResult) -> DMSContactData:
        return DMSContactData(
            contact_id=result.contact.contact_id,
            surname=result.contact.surname,
            name=result.contact.name,
            patronymic=result.contact.patronymic,
            phone=result.contact.phone,
            email=result.contact.email,
            students=[
                DMSStudentData(
                    student_id=s.student_id,
                    fio=s.fio,
                    grade=s.grade,
                    product_name=s.product_name,
                    moodle_id=s.moodle_id,
                )
                for s in result.students
            ],
        )

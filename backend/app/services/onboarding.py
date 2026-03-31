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
            "Onboarding verify: actor=%s client_type=%s",
            actor.actor_id, req.client_type,
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

        # Extract portal metadata from JWT claims (avatar не ПДн — URL на портале)
        meta = actor.metadata or {}
        portal_role = meta.get("user_role")    # int: 3=parent, 4=student, 5=guest
        is_minor = meta.get("is_minor")        # bool from JWT
        avatar = meta.get("avatar")            # portal avatar URL (internal)

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
            avatar=avatar,
            portal_role=portal_role if isinstance(portal_role, int) else None,
            is_minor=is_minor if isinstance(is_minor, bool) else None,
        )

        logger.info("Onboarding result: status=%s profile_id=%s", status, profile_id)

        # Enrich from existing profiles with same phone (background)
        self._try_enrich_from_phone(actor.actor_id, phone)

        return OnboardingVerifyResponse(
            status=status,
            profile_id=profile_id or "",
            dms_data=dms_data,
        )

    def save_profile_from_phone(
        self, actor_id: str, phone: str, actor_meta: dict | None = None,
    ) -> bool:
        """Auto-resolve DMS profile by phone and save. Returns True if saved."""
        norm_phone = normalize_phone(phone)
        dms_result = self.dms.search_contact_by_phone(norm_phone)
        if not dms_result:
            return False

        contact = dms_result.contact
        children = [{"fio": s.fio, "grade": s.grade} for s in dms_result.students]
        full_name = f"{contact.surname} {contact.name} {contact.patronymic or ''}".strip()
        first_grade = dms_result.students[0].grade if dms_result.students else None
        dms_data = self._build_dms_data(dms_result)

        meta = actor_meta or {}
        self.repo.save_user_profile(
            actor_id=actor_id,
            client_type="existing",
            user_role="parent",
            phone=norm_phone,
            phone_raw=phone,
            fio=full_name,
            grade=first_grade,
            children=children,
            dms_verified=True,
            dms_contact_id=contact.contact_id,
            dms_data=dms_data.model_dump() if dms_data else None,
            verification_status="found",
            avatar=meta.get("avatar"),
            portal_role=meta.get("user_role") if isinstance(meta.get("user_role"), int) else None,
            is_minor=meta.get("is_minor") if isinstance(meta.get("is_minor"), bool) else None,
        )
        logger.info("Auto-saved DMS profile for actor=%s", actor_id)

        # Enrich from existing profiles with same phone (background)
        self._try_enrich_from_phone(actor_id, norm_phone)

        return True

    def _try_enrich_from_phone(self, actor_id: str, phone: str) -> None:
        """If another actor has the same phone, copy their data to this profile (background)."""
        import threading

        def _run():
            try:
                donors = self.repo.find_profiles_by_phone(phone, exclude_actor_id=actor_id)
                if not donors:
                    return
                # Pick the richest donor (DMS-verified first, then most recent)
                donor = donors[0]
                logger.info(
                    "Phone merge: enriching actor=%s from donor=%s",
                    actor_id, donor.get("actor_id"),
                )
                self.repo.enrich_profile_from_existing(actor_id, donor)

                # Copy memory atoms (entity + preference)
                from app.db.memory_repository import MemoryRepository
                mem_repo = MemoryRepository()
                copied = mem_repo.copy_atoms_to_actor(donor["actor_id"], actor_id)
                if copied:
                    logger.info("Phone merge: copied %d atoms to actor=%s", copied, actor_id)
            except Exception:
                logger.warning("Phone merge failed for actor=%s", actor_id, exc_info=True)

        threading.Thread(target=_run, daemon=True).start()

    def get_profile_context_for_llm(self, actor_id: str) -> str | None:
        """Build context string for injection into LLM system messages."""
        profile = self.check_profile(actor_id)
        if not profile:
            return None

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

        # Portal role (из JWT портала, сохранён в БД)
        portal_role_map = {3: "родитель", 4: "ученик", 5: "гость"}
        p_role = getattr(profile, "portal_role", None)
        if p_role and p_role in portal_role_map:
            parts.append(f"- Роль на портале: {portal_role_map[p_role]}")

        # is_minor — критично для ФЗ-152 (ст. 9 ч. 6)
        p_minor = getattr(profile, "is_minor", None)
        if p_minor is True:
            parts.append("- Несовершеннолетний: да (требуется согласие родителя)")
        elif p_minor is False:
            parts.append("- Несовершеннолетний: нет")

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

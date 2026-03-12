from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.chat import AuthPayload


class StudentInfo(BaseModel):
    fio: str = Field(min_length=2, max_length=200)
    grade: int = Field(ge=1, le=11)


class OnboardingVerifyRequest(BaseModel):
    auth: AuthPayload
    client_type: Literal["existing", "new"]
    user_role: Literal["parent", "student"]
    phone: str = Field(min_length=5, max_length=30)
    students: list[StudentInfo] = Field(default_factory=list)
    fio: str | None = None
    grade: int | None = Field(default=None, ge=1, le=11)


class DMSStudentData(BaseModel):
    student_id: int
    fio: str
    grade: int | None = None
    product_name: str | None = None
    moodle_id: int | None = None


class DMSContactData(BaseModel):
    contact_id: int
    surname: str
    name: str
    patronymic: str | None = None
    phone: str | None = None
    email: str | None = None
    students: list[DMSStudentData] = Field(default_factory=list)


class OnboardingVerifyResponse(BaseModel):
    status: Literal["found", "not_found", "unexpected_found", "new_lead"]
    profile_id: str
    dms_data: DMSContactData | None = None


class UserProfile(BaseModel):
    id: str
    actor_id: str
    client_type: str
    user_role: str
    phone: str
    fio: str | None = None
    grade: int | None = None
    children: list[dict[str, Any]] = Field(default_factory=list)
    dms_verified: bool = False
    dms_contact_id: int | None = None
    dms_data: dict[str, Any] | None = None
    verification_status: str = "pending"


class ProfileCheckRequest(BaseModel):
    auth: AuthPayload


class ProfileCheckResponse(BaseModel):
    has_profile: bool
    profile: UserProfile | None = None

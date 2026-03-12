from __future__ import annotations

import hashlib
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.config import get_settings

DMS_PASSWORD_SALT = "w3X6SNW1ovcNrdggvRYzdH6jsQk7tlfkzJ7WnRclC3L52TGhq1lkWsUZTPF8DtqK"


def _hash_dms_password(password: str) -> str:
    """Hash password the same way DMS frontend does: SHA-256(password + salt)."""
    return hashlib.sha256((password + DMS_PASSWORD_SALT).encode()).hexdigest()

logger = logging.getLogger("integrations.dms")


@dataclass
class DMSContact:
    contact_id: int
    surname: str
    name: str
    patronymic: str | None = None
    phone: str | None = None
    email: str | None = None


@dataclass
class DMSStudent:
    student_id: int
    contact_id: int
    fio: str
    grade: int | None = None
    product_name: str | None = None
    moodle_id: int | None = None
    state: str | None = None
    enrollment_school: str | None = None
    is_active: bool = True


@dataclass
class DMSSearchResult:
    contact: DMSContact
    students: list[DMSStudent] = field(default_factory=list)


def _normalize_phone(phone: str) -> str:
    """Strip non-digits and replace leading 8 with 7."""
    digits = "".join(c for c in phone if c.isdigit())
    if digits.startswith("8") and len(digits) == 11:
        digits = "7" + digits[1:]
    return digits


def _format_phone_dms(digits: str) -> str:
    """Convert 79246724447 → 8 (924) 672-44-47 (DMS storage format)."""
    if len(digits) != 11:
        return digits
    # DMS stores as 8 (XXX) XXX-XX-XX
    d = digits
    if d.startswith("7"):
        d = "8" + d[1:]
    return f"{d[0]} ({d[1:4]}) {d[4:7]}-{d[7:9]}-{d[9:11]}"


class DMSServiceBase(ABC):
    """Abstract interface for DMS integration."""

    @abstractmethod
    def search_contact_by_phone(self, phone: str) -> DMSSearchResult | None:
        ...

    @abstractmethod
    def get_student_info(self, student_id: int) -> DMSStudent | None:
        ...

    @abstractmethod
    def get_students_by_contact(self, contact_id: int) -> list[DMSStudent]:
        ...


class MockDMSService(DMSServiceBase):
    """Mock DMS with test data. Used until real credentials are available."""

    MOCK_DATA: dict[str, DMSSearchResult] = {
        "79991234567": DMSSearchResult(
            contact=DMSContact(
                contact_id=1001,
                surname="Иванов",
                name="Пётр",
                patronymic="Сергеевич",
                phone="79991234567",
                email="ivanov@example.com",
            ),
            students=[
                DMSStudent(
                    student_id=2001,
                    contact_id=1001,
                    fio="Иванов Иван Петрович",
                    grade=7,
                    product_name="Экстернат Классный",
                    moodle_id=3001,
                ),
            ],
        ),
        "79998887766": DMSSearchResult(
            contact=DMSContact(
                contact_id=1002,
                surname="Петрова",
                name="Анна",
                patronymic="Владимировна",
                phone="79998887766",
            ),
            students=[
                DMSStudent(
                    student_id=2002,
                    contact_id=1002,
                    fio="Петров Максим Дмитриевич",
                    grade=5,
                    product_name="Экстернат Базовый",
                    moodle_id=3002,
                ),
                DMSStudent(
                    student_id=2003,
                    contact_id=1002,
                    fio="Петрова София Дмитриевна",
                    grade=3,
                    product_name="Экстернат Базовый",
                    moodle_id=3003,
                ),
            ],
        ),
        "79161112233": DMSSearchResult(
            contact=DMSContact(
                contact_id=1003,
                surname="Сидоров",
                name="Алексей",
                patronymic="Николаевич",
                phone="79161112233",
            ),
            students=[
                DMSStudent(
                    student_id=2004,
                    contact_id=1003,
                    fio="Сидоров Алексей Николаевич",
                    grade=10,
                    product_name="Экстернат Персональный",
                    moodle_id=3004,
                ),
            ],
        ),
    }

    def search_contact_by_phone(self, phone: str) -> DMSSearchResult | None:
        logger.info("MockDMS: search_contact_by_phone(%s)", phone)
        result = self.MOCK_DATA.get(phone)
        if result:
            logger.info(
                "MockDMS: found contact_id=%d with %d students",
                result.contact.contact_id,
                len(result.students),
            )
        else:
            logger.info("MockDMS: no contact found for phone=%s", phone)
        return result

    def get_student_info(self, student_id: int) -> DMSStudent | None:
        for result in self.MOCK_DATA.values():
            for student in result.students:
                if student.student_id == student_id:
                    return student
        return None

    def get_students_by_contact(self, contact_id: int) -> list[DMSStudent]:
        for result in self.MOCK_DATA.values():
            if result.contact.contact_id == contact_id:
                return result.students
        return []


class RealDMSService(DMSServiceBase):
    """Real DMS service — calls the Go backend REST API."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.base_url = self.settings.dms_base_url
        self._token: str | None = None
        self._client: "httpx.Client | None" = None

    def _get_client(self) -> "httpx.Client":
        if self._client is None:
            import httpx

            self._client = httpx.Client(
                base_url=self.base_url,
                verify=False,  # proxy.hss.center has expired SSL cert
                timeout=10,
            )
        return self._client

    def _authenticate(self) -> str:
        client = self._get_client()
        hashed = _hash_dms_password(self.settings.dms_password)
        resp = client.post(
            "/v1/api/auth",
            json={
                "username": self.settings.dms_username,
                "password": hashed,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        # grpc-gateway returns camelCase keys
        self._token = data.get("accessToken") or data.get("access_token")
        logger.info("DMS authenticated as %s", self.settings.dms_username)
        return self._token

    def _ensure_token(self) -> str:
        if not self._token:
            self._authenticate()
        return self._token

    def _request(self, method: str, path: str, **kwargs) -> "httpx.Response":
        """Make an authenticated request with auto-retry on 401."""
        client = self._get_client()
        token = self._ensure_token()
        kwargs.setdefault("headers", {})["Authorization"] = f"Bearer {token}"
        resp = client.request(method, path, **kwargs)
        if resp.status_code == 401:
            logger.info("DMS token expired, re-authenticating")
            token = self._authenticate()
            kwargs["headers"]["Authorization"] = f"Bearer {token}"
            resp = client.request(method, path, **kwargs)
        return resp

    def _search_contact_raw(self, query: str) -> dict | None:
        """Search DMS contacts by query string, return first match or None."""
        resp = self._request("GET", "/v1/api/contacts/search", params={"q": query, "limit": 5})
        if resp.status_code != 200:
            logger.error("DMS search failed: %d %s", resp.status_code, resp.text)
            return None
        data = resp.json()
        items = data.get("items", [])
        return items[0] if items else None

    def search_contact_by_phone(self, phone: str) -> DMSSearchResult | None:
        try:
            digits = _normalize_phone(phone)
            # Try multiple phone formats — DMS stores as "8 (924) 672-44-47"
            queries = [phone]  # original input first
            if digits != phone:
                queries.append(digits)
            dms_formatted = _format_phone_dms(digits)
            if dms_formatted not in queries:
                queries.append(dms_formatted)

            item = None
            for q in queries:
                logger.info("DMS: searching contact by q=%s", q)
                item = self._search_contact_raw(q)
                if item:
                    break

            if not item:
                logger.info("DMS: no contact found for phone=%s", phone)
                return None

            contact = DMSContact(
                contact_id=item["id"],
                surname=item.get("surname", ""),
                name=item.get("name", ""),
                patronymic=item.get("patronymic"),
                phone=item.get("phone"),
                email=item.get("email"),
            )
            logger.info("DMS: found contact_id=%d (%s %s)", contact.contact_id, contact.surname, contact.name)

            # Fetch students for this contact
            students = self.get_students_by_contact(contact.contact_id)
            return DMSSearchResult(contact=contact, students=students)
        except Exception:
            logger.exception("DMS search_contact_by_phone error")
            return None

    @staticmethod
    def _extract_grade_from_product(product_name: str | None) -> int | None:
        """Extract grade number from product name like 'Экстернат Классный 5 класс'."""
        if not product_name:
            return None
        m = re.search(r"(\d{1,2})\s*класс", product_name)
        return int(m.group(1)) if m else None

    def _parse_student(self, data: dict) -> DMSStudent:
        """Parse a student object from DMS API response (camelCase keys)."""
        contact = data.get("contact", {})
        product = data.get("product") or {}
        # FIO from the student's own contact record
        fio_parts = [
            contact.get("surname", ""),
            contact.get("name", ""),
            contact.get("patronymic", ""),
        ]
        fio = " ".join(p for p in fio_parts if p).strip() or data.get("login", "")
        # Grade: extract from product name ("Экстернат Классный 5 класс" → 5)
        product_name = product.get("name")
        grade = self._extract_grade_from_product(product_name)
        return DMSStudent(
            student_id=data.get("id", 0),
            contact_id=contact.get("id", 0),
            fio=fio,
            grade=int(grade) if grade is not None else None,
            product_name=product.get("name"),
            moodle_id=data.get("moodleId") or data.get("moodle_id"),
            state=data.get("state"),
            enrollment_school=data.get("enrollmentSchool") or data.get("enrollment_school"),
            is_active=data.get("isActive", True),
        )

    def get_students_by_contact(self, contact_id: int) -> list[DMSStudent]:
        """Fetch all students linked to a parent contact via POST /v1/api/students."""
        try:
            resp = self._request(
                "POST", "/v1/api/students",
                json={"contact_id": contact_id, "limit": 20},
            )
            if resp.status_code != 200:
                logger.error("DMS get_students failed: %d %s", resp.status_code, resp.text)
                return []
            data = resp.json()
            raw_students = data.get("students", [])
            students = [self._parse_student(s) for s in raw_students]
            logger.info("DMS: found %d students for contact_id=%d", len(students), contact_id)
            return students
        except Exception:
            logger.exception("DMS get_students_by_contact error")
            return []

    def get_student_info(self, student_id: int) -> DMSStudent | None:
        try:
            resp = self._request("GET", "/v1/api/student", params={"student_id": student_id})
            if resp.status_code != 200:
                logger.error("DMS get_student failed: %d %s", resp.status_code, resp.text)
                return None
            data = resp.json()
            return self._parse_student(data)
        except Exception:
            logger.exception("DMS get_student_info error")
            return None


def get_dms_service() -> DMSServiceBase:
    """Factory: real service if credentials configured, else mock."""
    settings = get_settings()
    if settings.dms_base_url and settings.dms_username:
        return RealDMSService()
    return MockDMSService()

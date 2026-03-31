"""Portal internal API client — server-to-server.

Fetches user context (profile + children) from portal without passing PII
through JWT/URLs. Compliant with ФЗ-152.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger("integrations.portal")

# Маскирование ПДн в логах (production)
_MASK = "***"


def _mask_fio(fio: str | None) -> str:
    if not fio:
        return _MASK
    parts = fio.split()
    if len(parts) >= 2:
        return f"{parts[0]} {_MASK}"
    return _MASK


@dataclass
class PortalChild:
    portal_user_id: int
    fio: str
    moodle_id: int | None = None


@dataclass
class PortalUserContext:
    user_id: int
    fio: str | None = None
    phone: str | None = None
    avatar: str | None = None
    moodle_id: int | None = None
    role_id: int = 0             # 3=parent, 4=student, 5=guest
    children: list[PortalChild] = field(default_factory=list)


class PortalClient:
    """Client for portal internal API."""

    def __init__(self) -> None:
        self._base_url = os.getenv("PORTAL_API_URL", "").rstrip("/")
        self._api_key = os.getenv("PORTAL_INTERNAL_API_KEY", "")
        self._timeout = 10.0

    def is_configured(self) -> bool:
        return bool(self._base_url and self._api_key)

    def get_user_context(self, portal_user_id: int) -> PortalUserContext | None:
        """Fetch user profile + children from portal. Returns None on error."""
        if not self.is_configured():
            logger.debug("PortalClient not configured, skipping")
            return None

        url = f"{self._base_url}/portal/api/internal/user_context"
        try:
            resp = httpx.get(
                url,
                params={"user_id": portal_user_id},
                headers={"X-Internal-Api-Key": self._api_key},
                timeout=self._timeout,
            )
            if resp.status_code != 200:
                logger.warning(
                    "Portal API returned %d for user_id=%d",
                    resp.status_code, portal_user_id,
                )
                return None

            data = resp.json()
            children = [
                PortalChild(
                    portal_user_id=c["portal_user_id"],
                    fio=c["fio"],
                    moodle_id=c.get("moodle_id"),
                )
                for c in data.get("children", [])
            ]

            ctx = PortalUserContext(
                user_id=data["user_id"],
                fio=data.get("fio"),
                phone=data.get("phone"),
                avatar=data.get("avatar"),
                moodle_id=data.get("moodle_id"),
                role_id=data.get("role_id", 0),
                children=children,
            )

            logger.info(
                "Portal context fetched: user_id=%d role=%d children=%d fio=%s",
                ctx.user_id, ctx.role_id, len(ctx.children),
                _mask_fio(ctx.fio),
            )
            return ctx

        except Exception:
            logger.warning(
                "Portal API request failed for user_id=%d",
                portal_user_id, exc_info=True,
            )
            return None


# Singleton
_client: PortalClient | None = None


def get_portal_client() -> PortalClient:
    global _client
    if _client is None:
        _client = PortalClient()
    return _client

from __future__ import annotations

from datetime import datetime, timezone

import jwt
from fastapi import HTTPException, status

from app.config import get_settings
from app.models.chat import ActorContext, Channel


class PortalAuth:
    def __init__(self) -> None:
        self.settings = get_settings()

    def resolve(self, token: str) -> ActorContext:
        try:
            payload = jwt.decode(
                token,
                self.settings.portal_jwt_secret,
                algorithms=[self.settings.portal_jwt_algorithm],
                options={"require": ["exp", "user_id"]},
            )
        except jwt.InvalidTokenError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid portal JWT token",
            ) from exc

        exp = payload.get("exp")
        if exp is not None and datetime.fromtimestamp(exp, tz=timezone.utc) < datetime.now(tz=timezone.utc):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Expired portal JWT token")

        user_id = payload.get("user_id")
        if not user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Portal token missing user_id")

        return ActorContext(
            channel=Channel.portal,
            actor_id=f"portal:{user_id}",
            display_name=payload.get("name"),
            phone=payload.get("phone"),
            metadata={
                "raw_claims": {k: v for k, v in payload.items() if k not in {"exp"}},
                "is_minor": payload.get("is_minor"),
                "birth_date": payload.get("birth_date"),
                "user_role": payload.get("user_role"),
                "avatar": payload.get("avatar"),
            },
        )

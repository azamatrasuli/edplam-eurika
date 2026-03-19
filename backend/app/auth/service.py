from __future__ import annotations

from fastapi import HTTPException, status

from app.auth.external import ExternalLinkAuth
from app.auth.portal import PortalAuth
from app.auth.telegram import TelegramAuth
from app.models.chat import ActorContext, AuthPayload, Channel


class AuthService:
    def __init__(self) -> None:
        self.portal_auth = PortalAuth()
        self.telegram_auth = TelegramAuth()
        self.external_auth = ExternalLinkAuth()

    def resolve(self, auth: AuthPayload) -> ActorContext:
        provided = [
            bool(auth.portal_token),
            bool(auth.telegram_init_data),
            bool(auth.external_token),
            bool(auth.guest_id),
        ]
        if sum(provided) != 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ошибка аутентификации. Обновите страницу и попробуйте снова.",
            )

        if auth.portal_token:
            return self.portal_auth.resolve(auth.portal_token)
        if auth.telegram_init_data:
            return self.telegram_auth.resolve(auth.telegram_init_data)
        if auth.external_token:
            return self.external_auth.resolve(auth.external_token)
        if auth.guest_id:
            return ActorContext(
                channel=Channel.guest,
                actor_id=f"guest:{auth.guest_id}",
                display_name=None,
                phone=None,
                metadata={},
            )

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ошибка аутентификации. Обновите страницу и попробуйте снова.")

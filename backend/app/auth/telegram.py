from __future__ import annotations

import hashlib
import hmac
import json
import urllib.parse
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status

from app.config import get_settings
from app.models.chat import ActorContext, Channel


class TelegramAuth:
    def __init__(self) -> None:
        self.settings = get_settings()

    def resolve(self, init_data: str) -> ActorContext:
        if not self.settings.telegram_bot_token:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="TELEGRAM_BOT_TOKEN is not configured",
            )

        try:
            parsed = urllib.parse.parse_qs(init_data, strict_parsing=True)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed Telegram initData")
        flattened = {k: v[0] for k, v in parsed.items()}

        recv_hash = flattened.pop("hash", None)
        if not recv_hash:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="initData has no hash")

        check_string = "\n".join(f"{k}={flattened[k]}" for k in sorted(flattened.keys()))

        secret_key = hmac.new(
            b"WebAppData",
            self.settings.telegram_bot_token.encode("utf-8"),
            hashlib.sha256,
        ).digest()

        calc_hash = hmac.new(secret_key, check_string.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc_hash, recv_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Telegram initData signature")

        auth_date = int(flattened.get("auth_date", "0"))
        if auth_date <= 0:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Telegram auth_date")
        if datetime.fromtimestamp(auth_date, tz=timezone.utc) < datetime.now(tz=timezone.utc) - timedelta(hours=24):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Stale Telegram initData")

        user_json = flattened.get("user")
        if not user_json:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Telegram initData has no user")

        try:
            user = json.loads(user_json)
        except (json.JSONDecodeError, TypeError):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Telegram user data")
        tg_id = user.get("id")
        if not tg_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Telegram user id is missing")

        display_name = " ".join(filter(None, [user.get("first_name"), user.get("last_name")])).strip() or None

        return ActorContext(
            channel=Channel.telegram,
            actor_id=f"telegram:{tg_id}",
            display_name=display_name,
            metadata={"telegram_user": user},
        )

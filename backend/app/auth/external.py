from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.config import get_settings
from app.models.chat import ActorContext, Channel


class ExternalLinkAuth:
    def __init__(self) -> None:
        self.settings = get_settings()

    def resolve(self, token: str) -> ActorContext:
        # Format: lead_id:expires_ts:signature
        parts = token.split(":")
        if len(parts) != 3:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed external token")

        lead_id, expires_ts, signature = parts
        if not lead_id or not expires_ts or not signature:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed external token")

        try:
            expires_at = datetime.fromtimestamp(int(expires_ts), tz=timezone.utc)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid external token expiry") from exc

        if expires_at < datetime.now(tz=timezone.utc):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="External token expired")

        msg = f"{lead_id}:{expires_ts}".encode("utf-8")
        expected = hmac.new(
            self.settings.external_link_secret.encode("utf-8"),
            msg,
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(expected, signature):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid external token signature")

        lead_hash = hashlib.sha256(lead_id.encode("utf-8")).hexdigest()[:16]
        return ActorContext(
            channel=Channel.external,
            actor_id=f"external:{lead_hash}",
            metadata={"lead_id": lead_id, "expires_at": expires_at.isoformat()},
        )

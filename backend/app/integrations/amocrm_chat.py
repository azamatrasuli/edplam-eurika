"""amoCRM Chat API (imBox) client — HMAC-SHA1 signed requests to amojo.amocrm.ru."""

from __future__ import annotations

import hashlib
import hmac
import json as _json
import logging
import time
from dataclasses import dataclass
from email.utils import formatdate
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger("amocrm_chat")

AMOJO_BASE_URL = "https://amojo.amocrm.ru"


@dataclass
class ChatSendResult:
    success: bool
    msgid: str | None = None
    error: str | None = None
    raw: dict | None = None


class AmoCRMChatClient:
    """
    Synchronous amoCRM Chat API (amojo) client.

    Uses HMAC-SHA1 per-request signatures (not OAuth Bearer).
    Separate from AmoCRMClient (REST API v4).
    Graceful degradation: never raises, returns ChatSendResult(success=False).
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._channel_id = self._settings.amocrm_chat_channel_id
        self._secret_key = self._settings.amocrm_chat_secret_key
        self._http = httpx.Client(timeout=15.0)
        self._cached_scope_id: str | None = None
        self._cached_amojo_id: str | None = None
        logger.info(
            "[init] AmoCRMChatClient created: channel_id=%s, secret_key_len=%d, configured=%s",
            self._channel_id, len(self._secret_key), self.is_configured(),
        )

    def is_configured(self) -> bool:
        return self._settings.amocrm_chat_configured

    # ---- HMAC-SHA1 signing -------------------------------------------------

    def _content_md5(self, body: str) -> str:
        return hashlib.md5(body.encode()).hexdigest()

    def _rfc2822_date(self) -> str:
        return formatdate(usegmt=True).replace("GMT", "+0000")

    def _sign(self, method: str, content_md5: str, content_type: str, date: str, path: str) -> str:
        canonical = "\n".join([method.upper(), content_md5, content_type, date, path])
        sig = hmac.new(self._secret_key.encode(), canonical.encode(), hashlib.sha1).hexdigest()
        logger.debug("[sign] canonical=%r -> sig=%s", canonical, sig[:12] + "...")
        return sig

    # ---- scope_id ----------------------------------------------------------

    def _get_amojo_id(self) -> str | None:
        if self._cached_amojo_id:
            logger.debug("[amojo_id] using cached: %s", self._cached_amojo_id)
            return self._cached_amojo_id
        logger.info("[amojo_id] fetching from amoCRM REST API...")
        from app.integrations.amocrm import AmoCRMClient
        data = AmoCRMClient()._request("GET", "/account", params={"with": "amojo_id"})
        if data and data.get("amojo_id"):
            self._cached_amojo_id = data["amojo_id"]
            logger.info("[amojo_id] OK: %s", self._cached_amojo_id)
            return self._cached_amojo_id
        logger.error("[amojo_id] FAILED — could not fetch amojo_id from /account")
        return None

    def get_scope_id(self) -> str | None:
        if self._cached_scope_id:
            logger.debug("[scope_id] using cached: %s", self._cached_scope_id)
            return self._cached_scope_id
        amojo_id = self._get_amojo_id()
        if not amojo_id:
            logger.error("[scope_id] FAILED — no amojo_id")
            return None
        self._cached_scope_id = f"{self._channel_id}_{amojo_id}"
        logger.info("[scope_id] constructed: %s", self._cached_scope_id)
        return self._cached_scope_id

    # ---- signed request ----------------------------------------------------

    def _signed_request(self, method: str, path: str, body_dict: dict) -> dict | None:
        body_str = _json.dumps(body_dict, ensure_ascii=False)
        content_type = "application/json"
        md5 = self._content_md5(body_str)
        date = self._rfc2822_date()
        sig = self._sign(method, md5, content_type, date, path)

        headers = {
            "Content-Type": content_type,
            "Content-MD5": md5.lower(),
            "X-Signature": sig.lower(),
            "Date": date,
        }
        url = f"{AMOJO_BASE_URL}{path}"

        logger.info("[request] %s %s", method, url)
        logger.debug("[request] headers=%s", {k: v for k, v in headers.items() if k != "X-Signature"})
        logger.debug("[request] body=%s", body_str[:500])

        try:
            resp = self._http.request(method, url, headers=headers, content=body_str.encode())
        except httpx.HTTPError:
            logger.exception("[request] HTTP error: %s %s", method, path)
            return None

        logger.info("[response] %s %s -> %d", method, path, resp.status_code)

        if not resp.is_success:
            logger.error("[response] FAILED: %d %s", resp.status_code, resp.text[:500])
            return None

        if not resp.text.strip():
            logger.info("[response] empty body (OK)")
            return {}
        try:
            data = resp.json()
            logger.info("[response] OK: %s", _json.dumps(data, ensure_ascii=False)[:300])
            return data
        except Exception:
            logger.warning("[response] non-JSON body: %s", resp.text[:200])
            return {"raw": resp.text}

    # ---- channel connection (one-time) -------------------------------------

    def connect_channel(self) -> bool:
        logger.info("[connect_channel] starting...")
        if not self.is_configured():
            logger.warning("[connect_channel] not configured, skipping")
            return False
        amojo_id = self._get_amojo_id()
        if not amojo_id:
            return False
        path = f"/v2/origin/custom/{self._channel_id}/connect"
        result = self._signed_request("POST", path, {
            "account_id": amojo_id,
            "title": "EdPalm AI Agent",
            "hook_api_version": "v2",
        })
        if result is not None:
            logger.info("[connect_channel] OK: %s", result)
            self._cached_scope_id = f"{self._channel_id}_{amojo_id}"
            return True
        logger.error("[connect_channel] FAILED")
        return False

    # ---- explicit chat creation (required for imBox visibility) --------------

    def create_chat(
        self,
        *,
        conversation_id: str,
        user_id: str,
        user_name: str,
        phone: str | None = None,
    ) -> dict | None:
        """
        POST /v2/origin/custom/{scope_id}/chats

        Explicitly registers a chat in amoCRM with user profile.
        This is REQUIRED for the conversation to appear in imBox.
        amoCRM auto-links to a contact if phone matches.
        """
        if not self.is_configured():
            return None
        scope_id = self.get_scope_id()
        if not scope_id:
            return None

        payload: dict[str, Any] = {
            "conversation_id": conversation_id,
            "user": {
                "id": user_id,
                "name": user_name or "Клиент EdPalm",
                "profile": {
                    "phone": phone,
                    "email": None,
                },
            },
        }

        path = f"/v2/origin/custom/{scope_id}/chats"
        logger.info("[create_chat] POST %s conv=%s user=%s phone=%s", path, conversation_id, user_id, phone)
        result = self._signed_request("POST", path, payload)
        if result:
            logger.info("[create_chat] OK: %s", result)
        else:
            logger.error("[create_chat] FAILED for conv=%s", conversation_id)
        return result

    # ---- send message to imBox ---------------------------------------------

    def send_message(
        self,
        *,
        conversation_id: str,
        sender_id: str,
        sender_name: str,
        text: str,
        is_bot: bool = False,
        sender_phone: str | None = None,
        receiver_id: str | None = None,
        receiver_name: str | None = None,
        receiver_phone: str | None = None,
    ) -> ChatSendResult:
        logger.info(
            "[send_message] conv=%s sender=%s is_bot=%s text=%s",
            conversation_id, sender_id, is_bot, text[:80],
        )

        if not self.is_configured():
            logger.warning("[send_message] not configured — channel_id=%s, secret_key_len=%d",
                           self._channel_id, len(self._secret_key))
            return ChatSendResult(success=False, error="not configured")

        scope_id = self.get_scope_id()
        if not scope_id:
            logger.error("[send_message] no scope_id, aborting")
            return ChatSendResult(success=False, error="no scope_id")

        now = int(time.time())
        now_ms = int(time.time() * 1000)
        prefix = "agent_bot" if is_bot else "agent_user"
        msgid = f"{prefix}_{now}_{now_ms % 1000}"

        if is_bot and receiver_id:
            # Outgoing (bot→user): amoCRM v2 requires receiver = origin user (client).
            # No explicit sender for outgoing messages — amoCRM treats them as from the channel.
            origin_user: dict[str, Any] = {"id": receiver_id, "name": receiver_name or "Клиент"}
            if receiver_phone:
                origin_user["profile"] = {"phone": receiver_phone}

            inner: dict[str, Any] = {
                "timestamp": now,
                "msec_timestamp": now_ms,
                "msgid": msgid,
                "conversation_id": conversation_id,
                "receiver": origin_user,
                "message": {"type": "text", "text": text},
                "silent": False,
            }
        else:
            # Incoming (user→bot): sender = actual user
            sender: dict[str, Any] = {"id": sender_id, "name": sender_name}
            if sender_phone:
                sender["profile"] = {"phone": sender_phone}

            inner: dict[str, Any] = {
                "timestamp": now,
                "msec_timestamp": now_ms,
                "msgid": msgid,
                "conversation_id": conversation_id,
                "sender": sender,
                "message": {"type": "text", "text": text},
                "silent": False,
            }

        payload: dict[str, Any] = {
            "event_type": "new_message",
            "payload": inner,
        }

        path = f"/v2/origin/custom/{scope_id}"
        logger.info("[send_message] POST %s scope=%s msgid=%s", path, scope_id, msgid)

        result = self._signed_request("POST", path, payload)

        if result is None:
            logger.error("[send_message] FAILED: request returned None")
            return ChatSendResult(success=False, msgid=msgid, error="request failed")

        logger.info(
            "[send_message] OK: msgid=%s conv=%s is_bot=%s response=%s",
            msgid, conversation_id, is_bot, _json.dumps(result, ensure_ascii=False)[:200],
        )
        return ChatSendResult(success=True, msgid=msgid, raw=result)

    # ---- webhook verification ----------------------------------------------

    def verify_webhook_signature(self, body: bytes | str, signature: str) -> bool:
        if isinstance(body, str):
            body = body.encode()
        expected = hmac.new(self._secret_key.encode(), body, hashlib.sha1).hexdigest()
        valid = hmac.compare_digest(expected, signature)
        logger.info("[verify_webhook] valid=%s", valid)
        return valid

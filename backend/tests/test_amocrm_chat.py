"""Tests for amoCRM Chat API (imBox) client."""

from __future__ import annotations

import hashlib
import hmac
import os

os.environ.setdefault("AMOCRM_CHAT_CHANNEL_ID", "test-channel-id")
os.environ.setdefault("AMOCRM_CHAT_SECRET_KEY", "test-secret-key")
os.environ.setdefault("AMOCRM_CLIENT_ID", "test_id")
os.environ.setdefault("AMOCRM_CLIENT_SECRET", "test_secret")
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("EXTERNAL_LINK_SECRET", "test")
os.environ.setdefault("PORTAL_JWT_SECRET", "test")
os.environ.setdefault("SESSION_SIGNING_SECRET", "test")
os.environ.setdefault("OPENAI_API_KEY", "")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")

from unittest.mock import patch

from app.integrations.amocrm_chat import AmoCRMChatClient


class TestSignature:
    def test_content_md5(self):
        client = AmoCRMChatClient()
        body = '{"test": "data"}'
        md5 = client._content_md5(body)
        assert md5 == hashlib.md5(body.encode()).hexdigest()

    def test_signature_is_sha1_hex(self):
        client = AmoCRMChatClient()
        sig = client._sign("POST", "md5", "application/json", "date", "/path")
        assert len(sig) == 40
        assert all(c in "0123456789abcdef" for c in sig)

    def test_date_uses_plus0000(self):
        client = AmoCRMChatClient()
        date = client._rfc2822_date()
        assert "+0000" in date
        assert "GMT" not in date


class TestWebhookVerification:
    def test_valid_signature(self):
        client = AmoCRMChatClient()
        body = b'{"event_type": "new_message"}'
        expected = hmac.new(b"test-secret-key", body, hashlib.sha1).hexdigest()
        assert client.verify_webhook_signature(body, expected) is True

    def test_invalid_signature(self):
        client = AmoCRMChatClient()
        assert client.verify_webhook_signature(b"body", "wrong") is False


class TestGracefulDegradation:
    def test_not_configured_returns_error(self):
        with patch.object(AmoCRMChatClient, "is_configured", return_value=False):
            client = AmoCRMChatClient()
            result = client.send_message(
                conversation_id="test", sender_id="u1", sender_name="Test", text="hi",
            )
            assert result.success is False

    def test_no_scope_id_returns_error(self):
        client = AmoCRMChatClient()
        with patch.object(client, "_get_amojo_id", return_value=None):
            result = client.send_message(
                conversation_id="test", sender_id="u1", sender_name="Test", text="hi",
            )
            assert result.success is False


class TestImBoxService:
    def test_forward_does_not_raise(self):
        from app.models.chat import ActorContext, Channel
        from app.services.imbox import ImBoxService

        service = ImBoxService()
        actor = ActorContext(channel=Channel.portal, actor_id="portal:123", display_name="Test")
        # Should not raise even when everything fails
        service.forward_user_message(actor, "hello")
        service.forward_agent_response(actor, "world")

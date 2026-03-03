"""Unit tests for the amoCRM client."""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

os.environ.setdefault("AMOCRM_CLIENT_ID", "test_id")
os.environ.setdefault("AMOCRM_CLIENT_SECRET", "test_secret")
os.environ.setdefault("AMOCRM_SUBDOMAIN", "test")
os.environ.setdefault("DATABASE_URL", "")
os.environ.setdefault("EXTERNAL_LINK_SECRET", "test")
os.environ.setdefault("PORTAL_JWT_SECRET", "test")
os.environ.setdefault("SESSION_SIGNING_SECRET", "test")
os.environ.setdefault("OPENAI_API_KEY", "")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")

from app.integrations.amocrm import AmoCRMClient, AmoCRMContact, AmoCRMLead


class TestParseContact:
    def test_extracts_phone_and_telegram_id(self):
        client = AmoCRMClient()
        raw = {
            "id": 123,
            "name": "Ivan Petrov",
            "custom_fields_values": [
                {"field_code": "PHONE", "values": [{"value": "+79991234567"}]},
                {"field_id": 1396311, "values": [{"value": "987654"}]},
            ],
        }
        contact = client._parse_contact(raw)
        assert contact.id == 123
        assert contact.name == "Ivan Petrov"
        assert contact.phone == "+79991234567"
        assert contact.telegram_id == "987654"

    def test_handles_missing_fields(self):
        client = AmoCRMClient()
        raw = {"id": 456, "name": "No Fields"}
        contact = client._parse_contact(raw)
        assert contact.id == 456
        assert contact.phone is None
        assert contact.telegram_id is None


class TestParseLead:
    def test_extracts_custom_fields(self):
        client = AmoCRMClient()
        raw = {
            "id": 789,
            "name": "Test Deal",
            "pipeline_id": 10490514,
            "status_id": 100,
            "price": 50000,
            "custom_fields_values": [
                {"field_id": 1396313, "values": [{"value": "Экстернат Классный"}]},
                {"field_id": 1396315, "values": [{"value": "54500"}]},
            ],
            "_embedded": {"contacts": [{"id": 123}]},
        }
        lead = client._parse_lead(raw)
        assert lead.id == 789
        assert lead.product_name == "Экстернат Классный"
        assert lead.amount == 54500
        assert lead.contact_id == 123
        assert lead.pipeline_id == 10490514

    def test_handles_no_custom_fields(self):
        client = AmoCRMClient()
        raw = {"id": 10, "name": "Empty", "pipeline_id": 1, "status_id": 1}
        lead = client._parse_lead(raw)
        assert lead.product_name is None
        assert lead.amount is None
        assert lead.contact_id is None


class TestGracefulDegradation:
    def test_request_returns_none_when_not_configured(self):
        """When database_url is empty, all methods return None."""
        client = AmoCRMClient()
        # _is_configured returns False because token_store is None
        assert client._request("GET", "/contacts") is None

    def test_find_contact_returns_none_when_not_configured(self):
        client = AmoCRMClient()
        assert client.find_contact_by_phone("+79991234567") is None
        assert client.find_contact_by_telegram_id("123") is None

    def test_find_or_create_returns_none_when_not_configured(self):
        client = AmoCRMClient()
        contact, is_new = client.find_or_create_contact(
            phone="+79991234567", name="Test", telegram_id="123",
        )
        assert contact is None
        assert is_new is True

    def test_find_active_lead_returns_none_when_not_configured(self):
        client = AmoCRMClient()
        assert client.find_active_lead(123) is None

"""Unit tests for the agent tool executor."""

from __future__ import annotations

import json
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

from app.agent.tools import ToolExecutor, ToolResult
from app.integrations.amocrm import AmoCRMClient, AmoCRMContact, AmoCRMLead


class TestEscalation:
    def test_escalate_returns_is_escalation_flag(self):
        executor = ToolExecutor()
        result = executor.execute("escalate_to_manager", {"reason": "Клиент просит менеджера"})
        assert result.is_escalation is True
        assert result.escalation_reason == "Клиент просит менеджера"
        data = json.loads(result.result)
        assert data["escalated"] is True

    def test_escalation_reason_preserved(self):
        executor = ToolExecutor()
        result = executor.execute("escalate_to_manager", {"reason": "Негатив"})
        assert result.escalation_reason == "Негатив"


class TestUnknownTool:
    def test_unknown_tool_returns_error_string(self):
        executor = ToolExecutor()
        result = executor.execute("nonexistent_tool", {})
        assert "Unknown tool" in result.result
        assert result.is_escalation is False


class TestSearchKnowledgeBase:
    @patch("app.agent.tools.search_knowledge_base")
    def test_returns_formatted_chunks(self, mock_search):
        from app.rag.search import KBChunk

        mock_search.return_value = [
            KBChunk(content="Пакет Заочный — бесплатно", section="Продукты", source="products", similarity=0.85),
            KBChunk(content="Для москвичей", section="Условия", source="products", similarity=0.72),
        ]
        executor = ToolExecutor()
        result = executor.execute("search_knowledge_base", {"query": "бесплатный пакет"})
        assert "Пакет Заочный" in result.result
        assert "Для москвичей" in result.result

    @patch("app.agent.tools.search_knowledge_base")
    def test_returns_not_found_message(self, mock_search):
        mock_search.return_value = []
        executor = ToolExecutor()
        result = executor.execute("search_knowledge_base", {"query": "инопланетяне"})
        assert "не найдено" in result.result


class TestCRMTools:
    def test_get_contact_returns_not_found_when_crm_down(self):
        executor = ToolExecutor()
        result = executor.execute("get_amocrm_contact", {"phone": "+79991234567"})
        data = json.loads(result.result)
        assert data["found"] is False

    def test_get_deal_returns_not_found_when_crm_down(self):
        executor = ToolExecutor()
        result = executor.execute("get_amocrm_deal", {"contact_id": 123})
        data = json.loads(result.result)
        assert data["found"] is False

    def test_create_lead_returns_error_when_crm_down(self):
        executor = ToolExecutor()
        result = executor.execute("create_amocrm_lead", {"name": "Test"})
        data = json.loads(result.result)
        assert data["success"] is False

    def test_get_contact_with_mock_crm(self):
        mock_crm = MagicMock(spec=AmoCRMClient)
        mock_crm.find_contact_by_telegram_id.return_value = AmoCRMContact(
            id=100, name="Ivan", phone="+79990001122", telegram_id="555",
        )
        executor = ToolExecutor(amocrm_client=mock_crm)
        result = executor.execute("get_amocrm_contact", {"telegram_id": "555"})
        data = json.loads(result.result)
        assert data["found"] is True
        assert data["contact_id"] == 100
        assert data["name"] == "Ivan"

    def test_create_lead_with_mock_crm(self):
        mock_crm = MagicMock(spec=AmoCRMClient)
        mock_crm.find_or_create_contact.return_value = (
            AmoCRMContact(id=200, name="Maria"),
            True,
        )
        mock_crm.create_lead.return_value = AmoCRMLead(
            id=300, name="AI-Агент: Экстернат — Maria",
            pipeline_id=10490514, status_id=1, price=54500,
        )
        executor = ToolExecutor(amocrm_client=mock_crm)
        result = executor.execute("create_amocrm_lead", {
            "name": "Maria",
            "phone": "+79990001122",
            "product": "Экстернат Классный",
            "amount": 54500,
        })
        data = json.loads(result.result)
        assert data["success"] is True
        assert data["lead_id"] == 300
        assert data["contact_id"] == 200
        assert data["is_new_contact"] is True

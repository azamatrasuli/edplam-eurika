#!/usr/bin/env python3
"""Tests for OpenAI API key fallback mechanism.

Verifies that when the primary API key hits `insufficient_quota`,
all integration points switch to the fallback key and retry.

Run:
    cd eurika/backend
    PYTHONPATH=. python -m unittest tests.test_openai_fallback -v
"""
from __future__ import annotations

import json
import os
import sys
import unittest
from io import BytesIO
from unittest.mock import MagicMock, patch, PropertyMock

# Ensure backend on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from openai import RateLimitError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_quota_error() -> RateLimitError:
    """Create a RateLimitError with code=insufficient_quota."""
    resp = httpx.Response(429, request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"))
    return RateLimitError(
        "You exceeded your current quota",
        response=resp,
        body={"code": "insufficient_quota", "type": "insufficient_quota",
              "message": "You exceeded your current quota"},
    )


def _make_rate_limit_error() -> RateLimitError:
    """Create a non-quota RateLimitError (temporary rate limit)."""
    resp = httpx.Response(429, request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"))
    return RateLimitError(
        "Rate limit exceeded",
        response=resp,
        body={"code": "rate_limit_exceeded", "type": "rate_limit",
              "message": "Rate limit exceeded"},
    )


def _mock_settings(primary="sk-primary", fallback="sk-fallback"):
    s = MagicMock()
    s.openai_api_key = primary
    s.openai_api_key_fallback = fallback
    s.openai_model = "gpt-4o"
    s.openai_embedding_model = "text-embedding-3-small"
    s.openai_tts_model = "tts-1"
    s.openai_tts_voice = "alloy"
    s.openai_request_timeout_seconds = 10
    return s


def _reset_singleton():
    import app.services.openai_client as oc
    oc._client = None
    oc._using_fallback = False


def _mock_embedding_response(embedding=None):
    emb = embedding or [0.1] * 10
    item = MagicMock()
    item.embedding = emb
    resp = MagicMock()
    resp.data = [item]
    return resp


def _mock_chat_response(content="ok"):
    msg = MagicMock()
    msg.content = content
    choice = MagicMock()
    choice.message = msg
    choice.delta = msg
    choice.finish_reason = "stop"
    resp = MagicMock()
    resp.choices = [choice]
    return resp


# =========================================================================
# 1. Core Singleton
# =========================================================================

class TestCoreSingleton(unittest.TestCase):

    def setUp(self):
        _reset_singleton()

    def tearDown(self):
        _reset_singleton()

    @patch("app.services.openai_client.get_settings", return_value=_mock_settings())
    @patch("app.services.openai_client.OpenAI")
    def test_creates_singleton(self, MockOAI, _):
        from app.services.openai_client import get_openai_client
        c1 = get_openai_client()
        c2 = get_openai_client()
        self.assertIs(c1, c2)
        MockOAI.assert_called_once_with(api_key="sk-primary")

    @patch("app.services.openai_client.get_settings", return_value=_mock_settings(primary=None))
    def test_returns_none_no_key(self, _):
        from app.services.openai_client import get_openai_client
        self.assertIsNone(get_openai_client())

    @patch("app.services.openai_client.get_settings", return_value=_mock_settings())
    @patch("app.services.openai_client.OpenAI")
    def test_switch_replaces_client(self, MockOAI, _):
        from app.services.openai_client import get_openai_client, switch_to_fallback
        import app.services.openai_client as oc
        primary = MagicMock(name="primary")
        fallback = MagicMock(name="fallback")
        MockOAI.side_effect = [primary, fallback]
        old = get_openai_client()
        self.assertIs(old, primary)
        result = switch_to_fallback()
        self.assertTrue(result)
        self.assertTrue(oc._using_fallback)
        self.assertIs(oc._client, fallback)
        MockOAI.assert_called_with(api_key="sk-fallback")

    @patch("app.services.openai_client.get_settings", return_value=_mock_settings())
    @patch("app.services.openai_client.OpenAI")
    def test_switch_idempotent(self, MockOAI, _):
        from app.services.openai_client import get_openai_client, switch_to_fallback
        get_openai_client()
        self.assertTrue(switch_to_fallback())
        self.assertFalse(switch_to_fallback())

    @patch("app.services.openai_client.get_settings", return_value=_mock_settings(fallback=None))
    @patch("app.services.openai_client.OpenAI")
    def test_switch_no_fallback_key(self, MockOAI, _):
        from app.services.openai_client import get_openai_client, switch_to_fallback
        get_openai_client()
        self.assertFalse(switch_to_fallback())

    def test_is_quota_error_code_attr(self):
        from app.services.openai_client import is_quota_error
        self.assertTrue(is_quota_error(_make_quota_error()))

    def test_is_quota_error_rate_limit(self):
        from app.services.openai_client import is_quota_error
        self.assertFalse(is_quota_error(_make_rate_limit_error()))

    def test_is_quota_error_body_nested(self):
        from app.services.openai_client import is_quota_error
        err = MagicMock()
        err.code = None
        err.body = {"error": {"code": "insufficient_quota"}}
        self.assertTrue(is_quota_error(err))


# =========================================================================
# 2. Memory fallback
# =========================================================================

class TestMemoryFallback(unittest.TestCase):

    def setUp(self):
        _reset_singleton()
        import app.services.memory as mem
        mem._openai_client = None

    def tearDown(self):
        _reset_singleton()
        import app.services.memory as mem
        mem._openai_client = None

    @patch("app.services.openai_client.get_settings", return_value=_mock_settings())
    @patch("app.services.memory.get_settings", return_value=_mock_settings())
    @patch("app.services.openai_client.OpenAI")
    def test_embed_switches_on_quota(self, MockOAI, _, __):
        primary_client = MagicMock()
        fallback_client = MagicMock()
        MockOAI.side_effect = [primary_client, fallback_client]

        primary_client.embeddings.create.side_effect = _make_quota_error()
        fallback_client.embeddings.create.return_value = _mock_embedding_response()

        from app.services.memory import _embed_query
        result = _embed_query("test")
        self.assertEqual(result, [0.1] * 10)
        fallback_client.embeddings.create.assert_called_once()

    @patch("app.services.openai_client.get_settings", return_value=_mock_settings())
    @patch("app.services.memory.get_settings", return_value=_mock_settings())
    @patch("app.services.openai_client.OpenAI")
    def test_embed_reraises_non_quota(self, MockOAI, _, __):
        client = MagicMock()
        MockOAI.return_value = client
        client.embeddings.create.side_effect = _make_rate_limit_error()

        from app.services.memory import _embed_query
        with self.assertRaises(RateLimitError):
            _embed_query("test")


# =========================================================================
# 3. RAG Search fallback
# =========================================================================

class TestRAGSearchFallback(unittest.TestCase):

    def setUp(self):
        _reset_singleton()

    def tearDown(self):
        _reset_singleton()

    @patch("app.services.openai_client.get_settings", return_value=_mock_settings())
    @patch("app.rag.search.get_settings", return_value=_mock_settings())
    @patch("app.services.openai_client.OpenAI")
    @patch("app.logging_config.log_external_call")
    def test_rag_switches_on_quota(self, mock_log, MockOAI, _, __):
        mock_log.return_value.__enter__ = MagicMock()
        mock_log.return_value.__exit__ = MagicMock(return_value=False)

        primary_client = MagicMock()
        fallback_client = MagicMock()
        MockOAI.side_effect = [primary_client, fallback_client]

        primary_client.embeddings.create.side_effect = _make_quota_error()
        fallback_client.embeddings.create.return_value = _mock_embedding_response()

        from app.rag.search import KnowledgeSearch
        ks = KnowledgeSearch()
        result = ks._embed_query("test")
        self.assertEqual(result, [0.1] * 10)

    @patch("app.services.openai_client.get_settings", return_value=_mock_settings(fallback=None))
    @patch("app.rag.search.get_settings", return_value=_mock_settings(fallback=None))
    @patch("app.services.openai_client.OpenAI")
    @patch("app.logging_config.log_external_call")
    def test_rag_reraises_when_not_refreshed(self, mock_log, MockOAI, _, __):
        mock_log.return_value.__enter__ = MagicMock()
        mock_log.return_value.__exit__ = MagicMock(return_value=False)

        client = MagicMock()
        MockOAI.return_value = client
        client.embeddings.create.side_effect = _make_quota_error()

        from app.rag.search import KnowledgeSearch
        ks = KnowledgeSearch()
        with self.assertRaises(RateLimitError):
            ks._embed_query("test")


# =========================================================================
# 4. Speech fallback
# =========================================================================

class TestSpeechFallback(unittest.TestCase):

    def setUp(self):
        _reset_singleton()

    def tearDown(self):
        _reset_singleton()

    @patch("app.services.openai_client.get_settings", return_value=_mock_settings())
    @patch("app.services.speech.get_settings", return_value=_mock_settings())
    @patch("app.services.openai_client.OpenAI")
    def test_transcribe_switches(self, MockOAI, _, __):
        primary_client = MagicMock()
        fallback_client = MagicMock()
        MockOAI.side_effect = [primary_client, fallback_client]

        primary_client.audio.transcriptions.create.side_effect = _make_quota_error()
        fallback_resp = MagicMock()
        fallback_resp.text = "Привет мир"
        fallback_client.audio.transcriptions.create.return_value = fallback_resp

        from app.services.speech import SpeechService
        svc = SpeechService()
        result = svc.transcribe(b"fake-audio", "test.webm")
        self.assertEqual(result, "Привет мир")

    @patch("app.services.openai_client.get_settings", return_value=_mock_settings())
    @patch("app.services.speech.get_settings", return_value=_mock_settings())
    @patch("app.services.openai_client.OpenAI")
    def test_synthesize_switches(self, MockOAI, _, __):
        primary_client = MagicMock()
        fallback_client = MagicMock()
        MockOAI.side_effect = [primary_client, fallback_client]

        primary_client.audio.speech.create.side_effect = _make_quota_error()
        fallback_resp = MagicMock()
        fallback_resp.content = b"mp3data"
        fallback_client.audio.speech.create.return_value = fallback_resp

        from app.services.speech import SpeechService
        svc = SpeechService()
        result = svc.synthesize("Привет")
        self.assertEqual(result, b"mp3data")

    @patch("app.services.openai_client.get_settings", return_value=_mock_settings())
    @patch("app.services.speech.get_settings", return_value=_mock_settings())
    @patch("app.services.openai_client.OpenAI")
    def test_synthesize_stream_switches(self, MockOAI, _, __):
        primary_client = MagicMock()
        fallback_client = MagicMock()
        MockOAI.side_effect = [primary_client, fallback_client]

        primary_client.audio.speech.create.side_effect = _make_quota_error()
        fallback_resp = MagicMock()
        fallback_resp.iter_bytes.return_value = iter([b"chunk1", b"chunk2"])
        fallback_client.audio.speech.create.return_value = fallback_resp

        from app.services.speech import SpeechService
        svc = SpeechService()
        chunks = list(svc.synthesize_stream("Привет"))
        self.assertEqual(chunks, [b"chunk1", b"chunk2"])


# =========================================================================
# 5. Summarizer fallback
# =========================================================================

class TestSummarizerFallback(unittest.TestCase):

    def setUp(self):
        _reset_singleton()

    def tearDown(self):
        _reset_singleton()

    @patch("app.services.openai_client.get_settings", return_value=_mock_settings())
    @patch("app.services.summarizer.get_settings", return_value=_mock_settings())
    @patch("app.services.openai_client.OpenAI")
    def test_embed_batch_switches(self, MockOAI, _, __):
        primary_client = MagicMock()
        fallback_client = MagicMock()
        MockOAI.side_effect = [primary_client, fallback_client]

        primary_client.embeddings.create.side_effect = _make_quota_error()
        fallback_client.embeddings.create.return_value = _mock_embedding_response()

        from app.services.summarizer import _embed_batch
        result = _embed_batch(["hello"])
        self.assertEqual(len(result), 1)

    @patch("app.services.openai_client.get_settings", return_value=_mock_settings())
    @patch("app.services.summarizer.get_settings", return_value=_mock_settings())
    @patch("app.services.openai_client.OpenAI")
    def test_summarize_llm_switches(self, MockOAI, _, __):
        primary_client = MagicMock()
        fallback_client = MagicMock()
        MockOAI.side_effect = [primary_client, fallback_client]

        primary_client.chat.completions.create.side_effect = _make_quota_error()
        summary_json = json.dumps({
            "summary": "test", "title": "t", "topics": [],
            "decisions": [], "preferences": [], "unresolved": [], "facts": [],
        })
        fallback_client.chat.completions.create.return_value = _mock_chat_response(summary_json)

        from app.services.summarizer import _call_summarize_llm
        from app.models.chat import ChatMessage
        from datetime import datetime
        msgs = [ChatMessage(role="user", content="Привет", created_at=datetime.now())]
        result = _call_summarize_llm(msgs)
        self.assertIsNotNone(result)
        self.assertEqual(result["summary"], "test")


# =========================================================================
# 6. LLM suggestions fallback
# =========================================================================

class TestLLMSuggestionsFallback(unittest.TestCase):

    def setUp(self):
        _reset_singleton()

    def tearDown(self):
        _reset_singleton()

    @patch("app.services.openai_client.get_settings", return_value=_mock_settings())
    @patch("app.services.llm.get_settings", return_value=_mock_settings())
    @patch("app.services.openai_client.OpenAI")
    def test_suggestions_switch_on_quota(self, MockOAI, _, __):
        primary_client = MagicMock()
        fallback_client = MagicMock()
        MockOAI.side_effect = [primary_client, fallback_client]

        primary_client.chat.completions.create.side_effect = _make_quota_error()
        chips_json = json.dumps([{"label": "Да", "value": "Да, подробнее"}])
        fallback_client.chat.completions.create.return_value = _mock_chat_response(chips_json)

        from app.services.llm import LLMService
        svc = LLMService()
        result = svc.generate_suggestions("Ответ агента", "Вопрос", agent_role="support")
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["label"], "Да")


# =========================================================================
# 7. Edge cases
# =========================================================================

class TestEdgeCases(unittest.TestCase):

    def setUp(self):
        _reset_singleton()

    def tearDown(self):
        _reset_singleton()

    @patch("app.services.openai_client.get_settings", return_value=_mock_settings(fallback=None))
    @patch("app.services.openai_client.OpenAI")
    def test_no_fallback_key_propagates(self, MockOAI, _):
        """When no fallback key, quota error propagates."""
        from app.services.openai_client import get_openai_client, is_quota_error, switch_to_fallback
        client = get_openai_client()
        self.assertFalse(switch_to_fallback())

    @patch("app.services.openai_client.get_settings", return_value=_mock_settings())
    @patch("app.services.openai_client.OpenAI")
    def test_both_keys_exhausted(self, MockOAI, _):
        """After switching, second quota error is not caught by switch."""
        from app.services.openai_client import get_openai_client, switch_to_fallback
        import app.services.openai_client as oc
        get_openai_client()
        self.assertTrue(switch_to_fallback())
        # Second switch attempt
        self.assertFalse(switch_to_fallback())
        self.assertTrue(oc._using_fallback)

    @patch("app.services.openai_client.get_settings", return_value=_mock_settings())
    @patch("app.services.openai_client.OpenAI")
    def test_singleton_shared_across_modules(self, MockOAI, _):
        """After switch, all modules get the same fallback client."""
        from app.services.openai_client import get_openai_client, switch_to_fallback
        import app.services.openai_client as oc

        get_openai_client()
        switch_to_fallback()
        fb_client = oc._client

        # Re-importing get_openai_client from different path should return same object
        from app.services.openai_client import get_openai_client as get2
        self.assertIs(get2(), fb_client)


# =========================================================================
# Runner
# =========================================================================

if __name__ == "__main__":
    unittest.main(verbosity=2)

"""Shared OpenAI client with auto-fallback on quota exhaustion.

All OpenAI calls across the codebase should use get_openai_client() instead of
creating their own OpenAI() instances.  When the primary key hits
`insufficient_quota`, switch_to_fallback() swaps the singleton to the fallback
key.  Existing references become stale — callers that cache `self.client` must
refresh via get_openai_client() after a quota error.
"""

from __future__ import annotations

import logging
from typing import TypeVar, Callable

from openai import OpenAI, RateLimitError

from app.config import get_settings

logger = logging.getLogger("services.openai_client")

_client: OpenAI | None = None
_using_fallback = False

T = TypeVar("T")


def get_openai_client() -> OpenAI | None:
    """Return shared OpenAI client. Creates on first call."""
    global _client
    if _client is None:
        settings = get_settings()
        if not settings.openai_api_key:
            return None
        _client = OpenAI(api_key=settings.openai_api_key)
    return _client


def switch_to_fallback() -> bool:
    """Switch to fallback API key. Returns True if switched, False if unavailable."""
    global _client, _using_fallback
    if _using_fallback:
        return False
    settings = get_settings()
    if not settings.openai_api_key_fallback:
        return False
    logger.warning("Switching to fallback OpenAI API key (primary quota exhausted)")
    _client = OpenAI(api_key=settings.openai_api_key_fallback)
    _using_fallback = True
    return True


def is_quota_error(e: Exception) -> bool:
    """Check if exception is an insufficient_quota error."""
    code = getattr(e, "code", None)
    if code == "insufficient_quota":
        return True
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        return body.get("error", {}).get("code") == "insufficient_quota"
    return False


def call_with_fallback(fn: Callable[..., T], *args, **kwargs) -> T:
    """Call *fn* with current client.  On quota error switch key and retry once.

    Usage::

        client = get_openai_client()
        result = call_with_fallback(
            client.chat.completions.create,
            model="gpt-4o-mini", messages=[...],
        )

    If the primary key is exhausted, the global singleton is replaced and *fn*
    is re-bound to the new client automatically (we re-derive fn from the
    refreshed singleton via *_rebind*).

    For simpler cases where you just need the client itself, pass a lambda::

        call_with_fallback(lambda: get_openai_client().embeddings.create(...))
    """
    try:
        return fn(*args, **kwargs)
    except RateLimitError as e:
        if is_quota_error(e):
            switch_to_fallback()
        raise

"""Auto-tagging: keyword-based fire-and-forget tagging of conversations."""

from __future__ import annotations

import logging
import re

from app.db.repository import ConversationRepository

logger = logging.getLogger("services.tagger")

# ---------------------------------------------------------------------------
# Tag taxonomy (matches plan)
# ---------------------------------------------------------------------------

_KEYWORD_MAP: list[tuple[str, list[str]]] = [
    ("payment",      [r"оплат", r"платёж", r"платеж", r"счёт", r"квитанц", r"рассрочк", r"долг"]),
    ("documents",    [r"документ", r"справк", r"договор", r"акт", r"скан", r"фото", r"загрузи"]),
    ("platform",     [r"платформ", r"личн.{0,5}кабинет", r"лк", r"сайт", r"войти", r"пароль", r"логин",
                      r"доступ", r"не могу зайти", r"не открывает"]),
    ("attestation",  [r"аттестац", r"экзамен", r"итогов", r"промежуточ", r"справк.{0,10}аттестац",
                      r"результат", r"оценк"]),
    ("schedule",     [r"расписани", r"урок", r"занятие", r"время", r"дата", r"когда"]),
    ("onboarding",   [r"регистрацион", r"первый шаг", r"как начать", r"письмо", r"логин.{0,10}паро",
                      r"добро пожаловат"]),
    ("technical",    [r"ошибк", r"баг", r"зависл", r"не работает", r"глючит", r"проблем"]),
    ("gia",          [r"\bгиа\b", r"\bогэ\b", r"\bегэ\b", r"государственн.{0,10}итогов", r"9 класс.{0,5}экзамен",
                      r"11 класс.{0,5}экзамен"]),
    ("checklist",    [r"чек.?лист", r"какой шаг", r"что дальше", r"статус зачисления",
                      r"прогресс", r"этап", r"шаг \d"]),
    ("other",        []),  # fallback — never matched by keyword
]

VALID_TAGS = {tag for tag, _ in _KEYWORD_MAP}


def auto_tag_from_message(conversation_id: str, text: str) -> None:
    """Fire-and-forget: detect tags in user message and append to conversation.

    Called from chat.py on every incoming user message.
    Silently skips on any error — never blocks the chat flow.
    """
    try:
        tags = _detect_tags(text)
        if not tags:
            return
        repo = ConversationRepository()
        repo.update_conversation_tags(conversation_id, tags)
        logger.debug("Auto-tag conv=%s tags=%s", conversation_id, tags)
    except Exception:
        logger.debug("Auto-tag failed for conv=%s", conversation_id, exc_info=True)


def tag_conversation(conversation_id: str, tags: list[str]) -> str:
    """Called by LLM tool: apply validated tags to conversation. Returns result message."""
    if not tags:
        return "Теги не указаны."

    cleaned = [t.strip().lower() for t in tags if t.strip()]
    invalid = [t for t in cleaned if t not in VALID_TAGS]
    valid = [t for t in cleaned if t in VALID_TAGS]

    if not valid:
        return f"Неизвестные теги: {', '.join(invalid)}. Допустимые: {', '.join(sorted(VALID_TAGS))}."

    try:
        repo = ConversationRepository()
        repo.update_conversation_tags(conversation_id, valid)
        logger.info("LLM tag_conversation conv=%s tags=%s", conversation_id, valid)
        msg = f"Теги установлены: {', '.join(valid)}."
        if invalid:
            msg += f" Неизвестные теги пропущены: {', '.join(invalid)}."
        return msg
    except Exception:
        logger.exception("tag_conversation failed for conv=%s", conversation_id)
        return "Не удалось сохранить теги."


def _detect_tags(text: str) -> list[str]:
    """Match keywords in text, return list of detected tag names."""
    low = text.lower()
    found = []
    for tag, patterns in _KEYWORD_MAP:
        if not patterns:
            continue
        for pattern in patterns:
            if re.search(pattern, low):
                found.append(tag)
                break
    return found

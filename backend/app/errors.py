"""Standardised error responses with Russian user-facing messages."""
from __future__ import annotations

from fastapi.responses import JSONResponse

# ---------------------------------------------------------------------------
# Error catalog
# ---------------------------------------------------------------------------

ERROR_MESSAGES: dict[str, dict] = {
    "message_too_long": {
        "status": 422,
        "detail": "Сообщение слишком длинное (максимум 4000 символов)",
        "hint": "Сократите текст и попробуйте снова",
    },
    "message_empty": {
        "status": 422,
        "detail": "Сообщение не может быть пустым",
    },
    "rate_limit": {
        "status": 429,
        "detail": "Слишком много запросов. Подождите минуту",
    },
    "auth_expired": {
        "status": 401,
        "detail": "Сессия истекла. Обновите страницу",
    },
    "auth_invalid": {
        "status": 401,
        "detail": "Ошибка авторизации. Попробуйте войти заново",
    },
    "audio_too_large": {
        "status": 413,
        "detail": "Аудиофайл слишком большой (максимум 25 МБ)",
        "hint": "Запишите сообщение покороче",
    },
    "audio_format": {
        "status": 400,
        "detail": "Формат аудио не поддерживается",
        "hint": "Используйте WebM, MP3 или WAV",
    },
    "stt_unavailable": {
        "status": 502,
        "detail": "Распознавание речи временно недоступно",
        "hint": "Напишите сообщение текстом",
    },
    "internal_error": {
        "status": 500,
        "detail": "Внутренняя ошибка. Попробуйте позже",
    },
    "validation_error": {
        "status": 422,
        "detail": "Ошибка валидации данных",
    },
}


def error_response(
    code: str,
    status: int | None = None,
    detail: str | None = None,
    hint: str | None = None,
) -> JSONResponse:
    """Build a JSON error response.

    ``code`` is looked up in ``ERROR_MESSAGES`` for defaults; explicit
    ``status``, ``detail``, and ``hint`` override catalog values.
    """
    entry = ERROR_MESSAGES.get(code, {})
    body: dict[str, str] = {
        "error": code,
        "detail": detail or entry.get("detail", "Произошла ошибка"),
    }
    resolved_hint = hint or entry.get("hint")
    if resolved_hint:
        body["hint"] = resolved_hint
    return JSONResponse(
        status_code=status or entry.get("status", 500),
        content=body,
    )

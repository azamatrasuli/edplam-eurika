"""Speech-to-text service using OpenAI Whisper API."""

from __future__ import annotations

import logging
from io import BytesIO

from openai import OpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)

ALLOWED_FORMATS = {"ogg", "mp3", "wav", "m4a", "webm", "mp4", "mpeg", "mpga"}


class SpeechService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = OpenAI(api_key=self.settings.openai_api_key) if self.settings.openai_api_key else None

    def transcribe(self, audio_bytes: bytes, filename: str = "audio.webm") -> str | None:
        """Transcribe audio bytes to text using Whisper API.

        Returns transcribed text or None if service unavailable.
        """
        if not self.client:
            return None

        try:
            audio_file = BytesIO(audio_bytes)
            audio_file.name = filename

            response = self.client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="ru",
            )
            return response.text.strip() if response.text else None
        except Exception:
            logger.error("Whisper transcription failed", exc_info=True)
            return None

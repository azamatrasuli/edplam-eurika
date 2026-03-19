"""Speech-to-text (Whisper) and text-to-speech (TTS) service using OpenAI API."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from io import BytesIO

from openai import OpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)

ALLOWED_FORMATS = {"ogg", "mp3", "wav", "m4a", "webm", "mp4", "mpeg", "mpga"}

# Max input length for OpenAI TTS API
_TTS_MAX_CHARS = 4096


class SpeechService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = OpenAI(api_key=self.settings.openai_api_key) if self.settings.openai_api_key else None

    # ---- STT (Whisper) ----

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

    # ---- TTS (OpenAI Text-to-Speech) ----

    def synthesize(
        self,
        text: str,
        voice: str | None = None,
        model: str | None = None,
    ) -> bytes | None:
        """Synthesize text to speech. Returns MP3 bytes or None."""
        if not self.client:
            return None

        voice = voice or self.settings.openai_tts_voice
        model = model or self.settings.openai_tts_model

        if len(text) > _TTS_MAX_CHARS:
            text = text[: _TTS_MAX_CHARS - 3] + "..."

        try:
            response = self.client.audio.speech.create(
                model=model,
                voice=voice,
                input=text,
                response_format="mp3",
            )
            return response.content
        except Exception:
            logger.error("TTS synthesis failed", exc_info=True)
            return None

    def synthesize_stream(
        self,
        text: str,
        voice: str | None = None,
        model: str | None = None,
    ) -> Iterator[bytes]:
        """Yield MP3 audio chunks for streaming playback."""
        if not self.client:
            return

        voice = voice or self.settings.openai_tts_voice
        model = model or self.settings.openai_tts_model

        if len(text) > _TTS_MAX_CHARS:
            text = text[: _TTS_MAX_CHARS - 3] + "..."

        try:
            response = self.client.audio.speech.create(
                model=model,
                voice=voice,
                input=text,
                response_format="mp3",
            )
            yield from response.iter_bytes(chunk_size=4096)
        except Exception:
            logger.error("TTS streaming synthesis failed", exc_info=True)

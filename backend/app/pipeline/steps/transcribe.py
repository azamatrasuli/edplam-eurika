"""Step 2: Transcribe audio using OpenAI gpt-4o-transcribe API."""

from __future__ import annotations

import logging
from pathlib import Path

from openai import OpenAI

from app.pipeline.config import TRANSCRIBE_MODEL
from app.pipeline.steps.extract_audio import split_audio

logger = logging.getLogger(__name__)


def transcribe_audio(wav_path: Path, output_dir: Path, api_key: str) -> str:
    """Transcribe WAV file via OpenAI API. Handles files >25MB by splitting."""
    transcript_path = output_dir / "transcript_raw.txt"
    if transcript_path.exists():
        logger.info("transcript_raw.txt already exists, skipping transcription")
        return transcript_path.read_text(encoding="utf-8")

    client = OpenAI(api_key=api_key, max_retries=5, timeout=300.0)
    chunks = split_audio(wav_path, output_dir)

    parts: list[str] = []
    for i, chunk_path in enumerate(chunks):
        logger.info("Transcribing chunk %d/%d: %s (%.1f MB)", i + 1, len(chunks), chunk_path.name, chunk_path.stat().st_size / 1e6)
        with open(chunk_path, "rb") as f:
            response = client.audio.transcriptions.create(
                model=TRANSCRIBE_MODEL,
                file=f,
                language="ru",
            )
        parts.append(response.text)

    full_transcript = "\n\n".join(parts)
    transcript_path.write_text(full_transcript, encoding="utf-8")
    logger.info("Transcript saved: %d chars", len(full_transcript))
    return full_transcript

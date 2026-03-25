"""Step 3: Clean and structure raw transcript using GPT-4o."""

from __future__ import annotations

import logging
from pathlib import Path

from openai import OpenAI

from app.pipeline.config import STRUCTURE_MODEL
from app.pipeline.prompts import CLEAN_STRUCTURE_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


def clean_and_structure(raw_transcript: str, output_dir: Path, api_key: str) -> str:
    """Clean filler words, structure into markdown with H2/H3 headings."""
    structured_path = output_dir / "structured.md"
    if structured_path.exists():
        logger.info("structured.md already exists, skipping")
        return structured_path.read_text(encoding="utf-8")

    from app.services.openai_client import get_openai_client
    client = get_openai_client() or OpenAI(api_key=api_key)

    # Split into small chunks (~4K chars each) so GPT-4o preserves maximum detail.
    # Smaller chunks = less compression = more content preserved.
    max_chunk_chars = 4_000
    text_parts = []
    paragraphs = raw_transcript.split("\n\n")
    buf = ""
    for para in paragraphs:
        if len(buf) + len(para) > max_chunk_chars and buf:
            text_parts.append(buf)
            buf = ""
        buf = buf + "\n\n" + para if buf else para
    if buf.strip():
        text_parts.append(buf)
    if not text_parts:
        text_parts = [raw_transcript]

    structured_parts: list[str] = []
    for i, part in enumerate(text_parts):
        logger.info("Structuring part %d/%d (%d chars)", i + 1, len(text_parts), len(part))
        response = client.chat.completions.create(
            model=STRUCTURE_MODEL,
            temperature=0,
            messages=[
                {"role": "system", "content": CLEAN_STRUCTURE_SYSTEM_PROMPT},
                {"role": "user", "content": part},
            ],
        )
        structured_parts.append(response.choices[0].message.content)

    result = "\n\n".join(structured_parts)
    structured_path.write_text(result, encoding="utf-8")
    logger.info("Structured text saved: %d chars", len(result))
    return result

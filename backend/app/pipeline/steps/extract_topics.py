"""Step 4: Extract FAQ, sales arguments, objections from structured text."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from openai import OpenAI

from app.pipeline.config import EXTRACT_MODEL
from app.pipeline.prompts import EXTRACT_TOPICS_SYSTEM_PROMPT

logger = logging.getLogger(__name__)


def extract_topics(structured_text: str, output_dir: Path, api_key: str) -> dict:
    """Extract structured topics from cleaned transcript via GPT-4o."""
    topics_path = output_dir / "topics.json"
    if topics_path.exists():
        logger.info("topics.json already exists, skipping")
        return json.loads(topics_path.read_text(encoding="utf-8"))

    client = OpenAI(api_key=api_key)

    logger.info("Extracting topics (%d chars input)", len(structured_text))
    response = client.chat.completions.create(
        model=EXTRACT_MODEL,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": EXTRACT_TOPICS_SYSTEM_PROMPT},
            {"role": "user", "content": structured_text},
        ],
    )

    data = json.loads(response.choices[0].message.content)
    topics_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(
        "Topics extracted: %d FAQ, %d arguments, %d objections",
        len(data.get("faq", [])),
        len(data.get("sales_arguments", [])),
        len(data.get("objections", [])),
    )
    return data

"""Step 6: Load markdown into pgvector (append mode, safe for existing KB)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import psycopg
from openai import OpenAI

from app.rag.loader import Chunk, chunk_sections, embed_texts, parse_markdown

logger = logging.getLogger(__name__)


def store_chunks_by_file(
    chunks: list[Chunk],
    embeddings: list[list[float]],
    database_url: str,
    namespace: str,
    file_source: str,
) -> int:
    """Insert chunks, deleting only previous chunks from the same file_source.

    Unlike store_chunks() in loader.py which deletes ALL chunks for a namespace,
    this function only removes chunks matching the specific file_source.
    This is safe to call without affecting existing KB files.
    """
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            # Delete only chunks from this specific file
            cur.execute(
                "DELETE FROM knowledge_chunks WHERE namespace = %s AND metadata->>'file_source' = %s",
                (namespace, file_source),
            )
            deleted = cur.rowcount
            if deleted:
                logger.info("Deleted %d previous chunks for file_source=%s", deleted, file_source)

            for chunk, emb in zip(chunks, embeddings):
                meta = {**chunk.metadata, "file_source": chunk.file_source}
                cur.execute(
                    """
                    INSERT INTO knowledge_chunks (source, section, chunk_index, content, metadata, embedding, namespace)
                    VALUES (%s, %s, %s, %s, %s::jsonb, %s::vector, %s)
                    """,
                    (
                        chunk.source,
                        chunk.section,
                        chunk.chunk_index,
                        chunk.content,
                        json.dumps(meta),
                        str(emb),
                        namespace,
                    ),
                )
        conn.commit()
    return len(chunks)


# Sources that go to deep_talk (educational/philosophical content for voice mode)
_DEEP_TALK_SOURCES = {"education", "general"}


def load_to_rag(md_path: Path, namespace: str, api_key: str, embedding_model: str, database_url: str, video_slug: str = "") -> int:
    """Parse, chunk, embed, and store a markdown file into pgvector.

    Automatically routes chunks:
    - education, general → namespace 'deep_talk' (for voice mode / long conversations)
    - everything else → namespace 'sales' (for sales agent RAG)
    """
    text = md_path.read_text(encoding="utf-8")
    file_source = f"webinar_{video_slug}.md" if video_slug else f"webinar_{md_path.stem}.md"

    sections = parse_markdown(text)
    logger.info("Parsed %d sections", len(sections))

    chunks = chunk_sections(sections, file_source=file_source)
    # Route chunks by source category
    for chunk in chunks:
        if chunk.source in _DEEP_TALK_SOURCES:
            chunk.namespace = "deep_talk"
        else:
            chunk.namespace = namespace

    sales_count = sum(1 for c in chunks if c.namespace == namespace)
    deep_count = sum(1 for c in chunks if c.namespace == "deep_talk")
    logger.info("Created %d chunks (%d sales, %d deep_talk)", len(chunks), sales_count, deep_count)

    if not chunks:
        logger.warning("No chunks to store")
        return 0

    client = OpenAI(api_key=api_key)
    texts = [c.content for c in chunks]
    embeddings = embed_texts(texts, client, embedding_model)
    logger.info("Generated %d embeddings", len(embeddings))

    # Store sales chunks
    sales_chunks = [(c, e) for c, e in zip(chunks, embeddings) if c.namespace == namespace]
    if sales_chunks:
        s_chunks, s_embs = zip(*sales_chunks)
        store_chunks_by_file(list(s_chunks), list(s_embs), database_url, namespace, file_source)
        logger.info("Stored %d sales chunks", len(s_chunks))

    # Store deep_talk chunks
    deep_chunks = [(c, e) for c, e in zip(chunks, embeddings) if c.namespace == "deep_talk"]
    if deep_chunks:
        d_chunks, d_embs = zip(*deep_chunks)
        store_chunks_by_file(list(d_chunks), list(d_embs), database_url, "deep_talk", file_source)
        logger.info("Stored %d deep_talk chunks", len(d_chunks))

    return len(chunks)

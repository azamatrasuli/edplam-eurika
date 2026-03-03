"""Knowledge base loader: parse markdown → chunk → embed → store in pgvector."""

from __future__ import annotations

import json
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import psycopg
from openai import OpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)

# --- Section-to-source mapping ---------------------------------------------------

_SOURCE_MAP: dict[str, str] = {
    "О КОМПАНИИ": "company",
    "КЛЮЧЕВЫЕ ЦИФРЫ": "company",
    "ПРОДУКТОВАЯ ЛИНЕЙКА": "products",
    "Пакет": "products",
    "Сравнительная таблица": "products",
    "АТТЕСТАЦИЯ": "attestation",
    "EDPALM DUBAI": "products",
    "ПАРТНЁРСКИЕ ПРОГРАММЫ": "products",
    "ДОПОЛНИТЕЛЬНЫЕ УСЛУГИ": "products",
    "УЧЕБНЫЙ ПРОЦЕСС": "education",
    "ИИ-АССИСТЕНТ": "education",
    "СЕМЕЙНОЕ ОБРАЗОВАНИЕ": "education",
    "БОЛИ КЛИЕНТОВ": "objections",
    "ВОЗРАЖЕНИЯ И ОТВЕТЫ": "objections",
    "КАК НАЧАТЬ ОБУЧЕНИЕ": "process",
    "ОПЛАТА": "payments",
    "ТЕХНИЧЕСКАЯ ПЛАТФОРМА": "education",
    "КЛЮЧЕВЫЕ УТП": "sales",
    "ЮРИДИЧЕСКИЕ ВОПРОСЫ": "faq",
    "КОНТАКТЫ И КАНАЛЫ": "contacts",
    "СОБЫТИЯ И СООБЩЕСТВО": "company",
    "ЧЕКЛИСТ КВАЛИФИКАЦИИ": "sales",
    "ЧЕКЛИСТ ОНБОРДИНГА": "process",
    "ШАБЛОНЫ КОММУНИКАЦИЙ": "sales",
    "ССЫЛКИ-СПРАВОЧНИК": "contacts",
}


def _resolve_source(heading: str) -> str:
    for pattern, source in _SOURCE_MAP.items():
        if pattern.lower() in heading.lower():
            return source
    return "general"


# --- Markdown parsing ------------------------------------------------------------

@dataclass
class Section:
    heading: str
    level: int
    content: str
    source: str


def parse_markdown(text: str) -> list[Section]:
    """Split markdown into sections by ## and ### headings.

    ### sections inherit source from their parent ## heading.
    """
    lines = text.split("\n")
    sections: list[Section] = []
    current_heading = "Введение"
    current_level = 1
    current_lines: list[str] = []
    parent_h2_heading = "Введение"

    for line in lines:
        match = re.match(r"^(#{2,3})\s+(.+)", line)
        if match:
            # Save previous section
            body = "\n".join(current_lines).strip()
            if body:
                # For ### headings, try own source first; fall back to parent ## source
                source = _resolve_source(current_heading)
                if source == "general" and current_level == 3:
                    source = _resolve_source(parent_h2_heading)
                sections.append(Section(
                    heading=current_heading,
                    level=current_level,
                    content=body,
                    source=source,
                ))
            current_heading = match.group(2).strip()
            current_level = len(match.group(1))
            if current_level == 2:
                parent_h2_heading = current_heading
            current_lines = []
        else:
            current_lines.append(line)

    # Last section
    body = "\n".join(current_lines).strip()
    if body:
        source = _resolve_source(current_heading)
        if source == "general" and current_level == 3:
            source = _resolve_source(parent_h2_heading)
        sections.append(Section(
            heading=current_heading,
            level=current_level,
            content=body,
            source=source,
        ))

    return sections


# --- Chunking --------------------------------------------------------------------

@dataclass
class Chunk:
    source: str
    section: str
    chunk_index: int
    content: str
    metadata: dict = field(default_factory=dict)
    file_source: str = ""


def chunk_sections(
    sections: list[Section],
    max_chars: int = 1500,
    overlap_chars: int = 150,
    file_source: str = "",
) -> list[Chunk]:
    """Split sections into chunks of ~400-600 tokens (approx max_chars characters)."""
    chunks: list[Chunk] = []

    for sec in sections:
        text = f"[{sec.heading}]\n{sec.content}"

        if len(text) <= max_chars:
            chunks.append(Chunk(
                source=sec.source,
                section=sec.heading,
                chunk_index=len(chunks),
                content=text,
                metadata={"level": sec.level},
                file_source=file_source,
            ))
        else:
            # Split by paragraphs first, then by size
            paragraphs = re.split(r"\n{2,}", text)
            buffer = ""
            for para in paragraphs:
                if len(buffer) + len(para) + 2 > max_chars and buffer:
                    chunks.append(Chunk(
                        source=sec.source,
                        section=sec.heading,
                        chunk_index=len(chunks),
                        content=buffer.strip(),
                        metadata={"level": sec.level},
                        file_source=file_source,
                    ))
                    # Keep overlap from the end of the previous chunk
                    buffer = buffer[-overlap_chars:] + "\n\n" + para if overlap_chars else para
                else:
                    buffer = buffer + "\n\n" + para if buffer else para

            if buffer.strip():
                chunks.append(Chunk(
                    source=sec.source,
                    section=sec.heading,
                    chunk_index=len(chunks),
                    content=buffer.strip(),
                    metadata={"level": sec.level},
                    file_source=file_source,
                ))

    return chunks


# --- Embedding -------------------------------------------------------------------

def embed_texts(texts: list[str], client: OpenAI, model: str, batch_size: int = 20) -> list[list[float]]:
    """Generate embeddings via OpenAI API in batches."""
    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        response = client.embeddings.create(model=model, input=batch)
        for item in response.data:
            all_embeddings.append(item.embedding)
    return all_embeddings


# --- Database storage ------------------------------------------------------------

def store_chunks(chunks: list[Chunk], embeddings: list[list[float]], database_url: str) -> int:
    """Truncate old data and insert new chunks with embeddings."""
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE knowledge_chunks")

            for chunk, emb in zip(chunks, embeddings):
                meta = {**chunk.metadata, "file_source": chunk.file_source}
                cur.execute(
                    """
                    INSERT INTO knowledge_chunks (source, section, chunk_index, content, metadata, embedding)
                    VALUES (%s, %s, %s, %s, %s::jsonb, %s::vector)
                    """,
                    (
                        chunk.source,
                        chunk.section,
                        chunk.chunk_index,
                        chunk.content,
                        json.dumps(meta),
                        str(emb),
                    ),
                )
        conn.commit()
    return len(chunks)


# --- CLI entry point -------------------------------------------------------------

def main() -> None:
    settings = get_settings()

    if not settings.openai_api_key:
        print("ERROR: OPENAI_API_KEY not set in .env")
        sys.exit(1)
    if not settings.database_url:
        print("ERROR: DATABASE_URL not set in .env")
        sys.exit(1)

    # Find knowledge_base/ directory relative to project root
    project_root = Path(__file__).resolve().parents[3]
    kb_dir = project_root / "knowledge_base"

    # Fallback to single file for backward compatibility
    if not kb_dir.exists():
        kb_file = project_root / "knowledge_base.md"
        if not kb_file.exists():
            print(f"ERROR: Neither {kb_dir} nor {kb_file} found")
            sys.exit(1)
        kb_files = [kb_file]
    else:
        kb_files = sorted(kb_dir.glob("*.md"))
        if not kb_files:
            print(f"ERROR: No .md files found in {kb_dir}")
            sys.exit(1)

    print(f"Found {len(kb_files)} knowledge base file(s)")

    # Parse → chunk all files
    all_chunks: list[Chunk] = []
    for kb_path in kb_files:
        print(f"\nLoading: {kb_path.name}")
        raw_text = kb_path.read_text(encoding="utf-8")

        sections = parse_markdown(raw_text)
        print(f"  Sections: {len(sections)}")

        chunks = chunk_sections(sections, file_source=kb_path.name)
        print(f"  Chunks: {len(chunks)}")
        all_chunks.extend(chunks)

    print(f"\nTotal chunks across all files: {len(all_chunks)}")

    # Embed
    client = OpenAI(api_key=settings.openai_api_key)
    texts = [c.content for c in all_chunks]
    print(f"Embedding {len(texts)} chunks via {settings.openai_embedding_model}...")
    embeddings = embed_texts(texts, client, settings.openai_embedding_model)
    print(f"Embeddings generated: {len(embeddings)}")

    # Store
    count = store_chunks(all_chunks, embeddings, settings.database_url)
    print(f"Stored in DB: {count} chunks")
    print("Done.")


if __name__ == "__main__":
    main()

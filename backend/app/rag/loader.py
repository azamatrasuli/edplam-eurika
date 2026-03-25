"""Knowledge base loader: parse markdown → chunk → embed → store in pgvector."""

from __future__ import annotations

import argparse
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
    # H1 titles
    "База знаний ИИ-агента": "general",
    "ЧАСТО ЗАДАВАЕМЫЕ ВОПРОСЫ": "faq",
    "Тариф Базовый": "products",
    "Тариф Классный": "products",
    "Тариф Выпускник": "products",
    "Тариф Персональный": "products",
    "Тариф Заочный": "products",
    # H2 sections
    "О КОМПАНИИ": "company",
    "О компании": "company",
    "КЛЮЧЕВЫЕ ЦИФРЫ": "company",
    "ПРОДУКТОВАЯ ЛИНЕЙКА": "products",
    "Пакет": "products",
    "НАШИ ПАКЕТЫ И ЦЕНЫ": "products",
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
    "ТИПОВЫЕ ВОЗРАЖЕНИЯ": "objections",
    "ЧАСТЫЕ СОМНЕНИЯ": "objections",
    "КАК НАЧАТЬ ОБУЧЕНИЕ": "process",
    "ОПЛАТА": "payments",
    "РАССРОЧКА": "payments",
    "ТЕХНИЧЕСКАЯ ПЛАТФОРМА": "education",
    "КЛЮЧЕВЫЕ УТП": "sales",
    "преимущества": "sales",
    "ЮРИДИЧЕСКИЕ ВОПРОСЫ": "faq",
    "КОНТАКТЫ И КАНАЛЫ": "contacts",
    "СВЯЗАТЬСЯ С МЕНЕДЖЕРОМ": "contacts",
    "СОБЫТИЯ И СООБЩЕСТВО": "company",
    "ЧЕКЛИСТ КВАЛИФИКАЦИИ": "sales",
    "ЧЕКЛИСТ ОНБОРДИНГА": "process",
    "ШАБЛОНЫ КОММУНИКАЦИЙ": "sales",
    "ССЫЛКИ-СПРАВОЧНИК": "contacts",
    "ПРОГРАММА И ФОРМАТ": "education",
    "ПОСТУПЛЕНИЕ И ЗАЧИСЛЕНИЕ": "process",
    "ПРОЖИВАНИЕ И ГРАЖДАНСТВО": "faq",
    "СРОКИ ПОКУПКИ": "process",
    "ЧТО МОЖНО ОБЕЩАТЬ": "sales",
    "ДОКУМЕНТЫ": "process",
    # H3 sections
    "Финансовые инструменты": "payments",
    "Ценообразование": "products",
    "Логика": "sales",
    "Для кого этот тариф": "products",
    "Целевая аудитория": "products",
    # H4 sections
    "Линейка": "products",
    # Support KB sections
    "Зачисление": "enrollment",
    "зачисление": "enrollment",
    "Заочное обучение": "enrollment_zo",
    "Пошаговый чек-лист": "enrollment",
    "Документы для зачисления": "documents",
    "Передача оригиналов": "documents",
    "Аттестация": "attestation",
    "аттестация": "attestation",
    "Попытки аттестации": "attestation",
    "Шкала оценок": "attestation",
    "Сроки сдачи аттестации": "attestation",
    "Сроки аттестации": "attestation",
    "Правила прохождения": "attestation",
    "Правила оформления ответов": "attestation",
    "Претензии по аттестации": "attestation",
    "Платформа": "platform",
    "платформа": "platform",
    "Навигация": "platform",
    "Не грузится": "platform",
    "Неверный логин": "platform",
    "Ошибка 502": "platform",
    "Не отображаются формулы": "platform",
    "Завершить класс": "platform",
    "тренажёры": "platform",
    "ГИА": "gia",
    "ОГЭ": "gia",
    "ЕГЭ": "gia",
    "Итоговое собеседование": "gia",
    "Итоговое сочинение": "gia",
    "Аттестат с отличием": "gia",
    "Выдача аттестатов": "gia",
    "Апелляция": "gia",
    "Дистанционная сдача": "gia",
    "медаль": "gia",
    "Онбординг": "onboarding",
    "После оплаты": "onboarding",
    "Действия клиента": "onboarding",
    "Типичные проблемы": "onboarding",
    "Шаблон": "notifications",
    "Напоминание": "notifications",
    "Эскалация": "escalation",
    "эскалация": "escalation",
    "Когда передавать": "escalation",
    "Кому передавать": "escalation",
    "Вопросы по оплате": "escalation",
    "Вопросы по договору": "escalation",
    "Отчисление": "processes",
    "Перевод": "processes",
    "МЦКО": "processes",
    "Индивидуальный проект": "processes",
    "Справки": "processes",
    "Контакты": "contacts",
    "контакты": "contacts",
    "Офис ЦПСО": "contacts",
    "Почтовый адрес": "contacts",
    "Полезные ссылки": "contacts",
    "Частые вопросы": "faq",
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
    """Split markdown into sections by #, ##, ### and #### headings.

    Sub-headings inherit source from their nearest parent heading.
    """
    lines = text.split("\n")
    sections: list[Section] = []
    current_heading = "Введение"
    current_level = 1
    current_lines: list[str] = []
    parent_h2_heading = "Введение"

    for line in lines:
        match = re.match(r"^(#{1,4})\s+(.+)", line)
        if match:
            # Save previous section
            body = "\n".join(current_lines).strip()
            if body:
                # For sub-headings, try own source first; fall back to parent heading source
                source = _resolve_source(current_heading)
                if source == "general" and current_level >= 3:
                    source = _resolve_source(parent_h2_heading)
                sections.append(Section(
                    heading=current_heading,
                    level=current_level,
                    content=body,
                    source=source,
                ))
            current_heading = match.group(2).strip()
            current_level = len(match.group(1))
            if current_level <= 2:
                parent_h2_heading = current_heading
            current_lines = []
        else:
            current_lines.append(line)

    # Last section
    body = "\n".join(current_lines).strip()
    if body:
        source = _resolve_source(current_heading)
        if source == "general" and current_level >= 3:
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
    namespace: str = "sales"


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

def store_chunks(chunks: list[Chunk], embeddings: list[list[float]], database_url: str, namespace: str = "sales") -> int:
    """Delete old data for the given namespace and insert new chunks with embeddings."""
    with psycopg.connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM knowledge_chunks WHERE namespace = %s", (namespace,))

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


# --- CLI entry point -------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Load knowledge base into pgvector")
    parser.add_argument(
        "--namespace",
        default="sales",
        choices=["sales", "support", "teacher", "shared"],
        help="Namespace for knowledge chunks (default: sales)",
    )
    parser.add_argument(
        "--dir",
        default=None,
        help="Path to knowledge base directory (default: auto-detect)",
    )
    args = parser.parse_args()
    namespace: str = args.namespace

    settings = get_settings()

    if not settings.openai_api_key:
        print("ERROR: OPENAI_API_KEY not set in .env")
        sys.exit(1)
    if not settings.database_url:
        print("ERROR: DATABASE_URL not set in .env")
        sys.exit(1)

    # Find knowledge_base/ directory
    if args.dir:
        kb_dir = Path(args.dir)
    else:
        project_root = Path(__file__).resolve().parents[3]
        kb_dir = project_root / "knowledge_base"

    # Fallback to single file for backward compatibility
    if not kb_dir.exists():
        project_root = Path(__file__).resolve().parents[3]
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

    print(f"Namespace: {namespace}")
    print(f"Found {len(kb_files)} knowledge base file(s)")

    # Parse → chunk all files
    all_chunks: list[Chunk] = []
    for kb_path in kb_files:
        print(f"\nLoading: {kb_path.name}")
        raw_text = kb_path.read_text(encoding="utf-8")

        sections = parse_markdown(raw_text)
        print(f"  Sections: {len(sections)}")

        chunks = chunk_sections(sections, file_source=kb_path.name)
        for chunk in chunks:
            chunk.namespace = namespace
        print(f"  Chunks: {len(chunks)}")
        all_chunks.extend(chunks)

    print(f"\nTotal chunks across all files: {len(all_chunks)}")

    # Embed
    from app.services.openai_client import get_openai_client
    client = get_openai_client() or OpenAI(api_key=settings.openai_api_key)
    texts = [c.content for c in all_chunks]
    print(f"Embedding {len(texts)} chunks via {settings.openai_embedding_model}...")
    embeddings = embed_texts(texts, client, settings.openai_embedding_model)
    print(f"Embeddings generated: {len(embeddings)}")

    # Store
    count = store_chunks(all_chunks, embeddings, settings.database_url, namespace=namespace)
    print(f"Stored in DB: {count} chunks (namespace={namespace})")
    print("Done.")


if __name__ == "__main__":
    main()

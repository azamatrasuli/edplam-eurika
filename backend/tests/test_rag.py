"""Unit tests for RAG: markdown parsing, chunking, source resolution."""

from __future__ import annotations

import os

os.environ.setdefault("EXTERNAL_LINK_SECRET", "test")
os.environ.setdefault("PORTAL_JWT_SECRET", "test")
os.environ.setdefault("SESSION_SIGNING_SECRET", "test")
os.environ.setdefault("OPENAI_API_KEY", "")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test")
os.environ.setdefault("DATABASE_URL", "")

from app.rag.loader import (
    Chunk,
    Section,
    _resolve_source,
    chunk_sections,
    parse_markdown,
)


class TestParseMarkdown:
    def test_splits_by_h2_headings(self):
        md = "## First\nContent one\n\n## Second\nContent two"
        sections = parse_markdown(md)
        assert len(sections) == 2
        assert sections[0].heading == "First"
        assert sections[0].level == 2
        assert "Content one" in sections[0].content
        assert sections[1].heading == "Second"

    def test_splits_by_h3_headings(self):
        md = "## Parent\n\n### Child A\nText A\n\n### Child B\nText B"
        sections = parse_markdown(md)
        assert any(s.heading == "Child A" for s in sections)
        assert any(s.heading == "Child B" for s in sections)

    def test_empty_sections_skipped(self):
        md = "## Empty\n## HasContent\nSome text"
        sections = parse_markdown(md)
        assert len(sections) == 1
        assert sections[0].heading == "HasContent"

    def test_h1_and_plain_text_before_first_heading(self):
        md = "# Title\nIntro paragraph\n\n## Real Section\nBody"
        sections = parse_markdown(md)
        # Intro goes under default heading "Введение"
        assert sections[0].heading == "Введение"
        assert "Intro paragraph" in sections[0].content
        assert sections[1].heading == "Real Section"

    def test_source_resolved_for_known_heading(self):
        md = "## ПРОДУКТОВАЯ ЛИНЕЙКА\nDetails about products"
        sections = parse_markdown(md)
        assert sections[0].source == "products"

    def test_h3_inherits_parent_source(self):
        md = "## ПРОДУКТОВАЯ ЛИНЕЙКА\n\n### Пакет «Заочный»\nDescription"
        sections = parse_markdown(md)
        child = [s for s in sections if s.heading == "Пакет «Заочный»"]
        assert len(child) == 1
        assert child[0].source == "products"


class TestResolveSource:
    def test_known_patterns(self):
        assert _resolve_source("ПРОДУКТОВАЯ ЛИНЕЙКА") == "products"
        assert _resolve_source("БОЛИ КЛИЕНТОВ") == "objections"
        assert _resolve_source("ОПЛАТА") == "payments"
        assert _resolve_source("КОНТАКТЫ И КАНАЛЫ") == "contacts"

    def test_partial_match(self):
        assert _resolve_source("Пакет «Базовый» 3 класс") == "products"

    def test_unknown_returns_general(self):
        assert _resolve_source("Случайный заголовок") == "general"


class TestChunkSections:
    def test_small_section_single_chunk(self):
        sections = [Section(heading="Test", level=2, content="Short text", source="general")]
        chunks = chunk_sections(sections)
        assert len(chunks) == 1
        assert "[Test]" in chunks[0].content
        assert "Short text" in chunks[0].content

    def test_large_section_split_into_multiple_chunks(self):
        long_text = "\n\n".join(f"Paragraph {i}: " + "x" * 200 for i in range(20))
        sections = [Section(heading="Big", level=2, content=long_text, source="products")]
        chunks = chunk_sections(sections, max_chars=500)
        assert len(chunks) > 1

    def test_overlap_present(self):
        long_text = "\n\n".join(f"Para_{i}: " + "y" * 300 for i in range(5))
        sections = [Section(heading="Overlap", level=2, content=long_text, source="products")]
        chunks = chunk_sections(sections, max_chars=500, overlap_chars=100)
        # Check that second chunk contains some text from end of first
        if len(chunks) >= 2:
            tail_of_first = chunks[0].content[-100:]
            assert any(word in chunks[1].content for word in tail_of_first.split() if len(word) > 3)

    def test_file_source_propagated(self):
        sections = [Section(heading="Test", level=2, content="Body", source="general")]
        chunks = chunk_sections(sections, file_source="03_tariffs.md")
        assert chunks[0].file_source == "03_tariffs.md"

    def test_metadata_contains_level(self):
        sections = [Section(heading="H3", level=3, content="Text", source="general")]
        chunks = chunk_sections(sections)
        assert chunks[0].metadata["level"] == 3


class TestSearchGracefulWithoutDB:
    def test_search_returns_empty_when_no_pool(self):
        """search_knowledge_base returns [] when DB is not configured."""
        from app.rag.search import search_knowledge_base

        result = search_knowledge_base("test query")
        assert result == []

"""RAG retrieval: embed query → cosine similarity search in pgvector."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache

import psycopg
from openai import OpenAI

from app.config import get_settings
from app.db.pool import get_connection, has_pool

logger = logging.getLogger(__name__)


@dataclass
class KBChunk:
    content: str
    section: str
    source: str
    similarity: float


class KnowledgeSearch:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.client = OpenAI(api_key=self.settings.openai_api_key) if self.settings.openai_api_key else None

    def _embed_query(self, text: str) -> list[float]:
        response = self.client.embeddings.create(
            model=self.settings.openai_embedding_model,
            input=text,
        )
        return response.data[0].embedding

    def search(
        self,
        query: str,
        top_k: int | None = None,
        threshold: float | None = None,
        namespace: str | None = None,
    ) -> list[KBChunk]:
        """Search knowledge base by semantic similarity.

        Returns list of KBChunk sorted by relevance (highest first).
        If namespace is provided, only chunks with that namespace are searched.
        """
        if not self.client or not has_pool():
            return []

        top_k = top_k or self.settings.rag_top_k
        threshold = threshold or self.settings.rag_similarity_threshold

        try:
            embedding = self._embed_query(query)
        except Exception:
            logger.warning("Failed to embed query for RAG search", exc_info=True)
            return []

        try:
            with get_connection() as conn:
                if conn is None:
                    return []
                with conn.cursor() as cur:
                    if namespace:
                        cur.execute(
                            """
                            SELECT content, section, source,
                                   1 - (embedding <=> %s::vector) AS similarity
                            FROM knowledge_chunks
                            WHERE 1 - (embedding <=> %s::vector) > %s
                              AND namespace = %s
                            ORDER BY embedding <=> %s::vector
                            LIMIT %s
                            """,
                            (str(embedding), str(embedding), threshold, namespace, str(embedding), top_k),
                        )
                    else:
                        cur.execute(
                            """
                            SELECT content, section, source,
                                   1 - (embedding <=> %s::vector) AS similarity
                            FROM knowledge_chunks
                            WHERE 1 - (embedding <=> %s::vector) > %s
                            ORDER BY embedding <=> %s::vector
                            LIMIT %s
                            """,
                            (str(embedding), str(embedding), threshold, str(embedding), top_k),
                        )
                    rows = cur.fetchall()

            return [
                KBChunk(
                    content=row["content"],
                    section=row["section"] or "",
                    source=row["source"],
                    similarity=round(float(row["similarity"]), 4),
                )
                for row in rows
            ]
        except (psycopg.Error, OSError):
            logger.error("Knowledge base search failed", exc_info=True)
            return []


@lru_cache(maxsize=1)
def _get_searcher() -> KnowledgeSearch:
    return KnowledgeSearch()


def search_knowledge_base(
    query: str,
    top_k: int | None = None,
    threshold: float | None = None,
    namespace: str | None = None,
) -> list[KBChunk]:
    """Convenience function: search KB with singleton instance."""
    return _get_searcher().search(query, top_k=top_k, threshold=threshold, namespace=namespace)

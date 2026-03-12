-- ============================================================================
-- 010: Conversational Memory — dynamic RAG from chat history
-- Tables: agent_conversation_summaries, agent_memory_atoms
-- ============================================================================

-- Conversation summaries (L1 and L2 memory)
CREATE TABLE IF NOT EXISTS agent_conversation_summaries (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  actor_id        TEXT NOT NULL,
  agent_role      TEXT NOT NULL DEFAULT 'sales',
  summary_type    TEXT NOT NULL DEFAULT 'conversation'
    CHECK (summary_type IN ('conversation', 'weekly', 'monthly')),
  summary_text    TEXT NOT NULL,
  topics          TEXT[] NOT NULL DEFAULT '{}',
  decisions       JSONB NOT NULL DEFAULT '[]'::JSONB,
  preferences     JSONB NOT NULL DEFAULT '[]'::JSONB,
  unresolved      JSONB NOT NULL DEFAULT '[]'::JSONB,
  embedding       vector(1536),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_summaries_actor_role
  ON agent_conversation_summaries(actor_id, agent_role);
CREATE INDEX IF NOT EXISTS idx_summaries_type
  ON agent_conversation_summaries(summary_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_summaries_conversation
  ON agent_conversation_summaries(conversation_id);
CREATE INDEX IF NOT EXISTS idx_summaries_embedding
  ON agent_conversation_summaries USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

-- Atomic memory facts (Mem0-inspired)
CREATE TABLE IF NOT EXISTS agent_memory_atoms (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  actor_id        TEXT NOT NULL,
  agent_role      TEXT NOT NULL DEFAULT 'sales',
  conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
  fact_type       TEXT NOT NULL
    CHECK (fact_type IN ('preference', 'decision', 'entity', 'action_item', 'question', 'feedback')),
  subject         TEXT NOT NULL,
  predicate       TEXT NOT NULL,
  object          TEXT,
  confidence      REAL NOT NULL DEFAULT 0.8,
  embedding       vector(1536),
  expires_at      TIMESTAMPTZ,
  superseded_by   UUID REFERENCES agent_memory_atoms(id),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_memory_atoms_actor_role
  ON agent_memory_atoms(actor_id, agent_role);
CREATE INDEX IF NOT EXISTS idx_memory_atoms_type
  ON agent_memory_atoms(fact_type);
CREATE INDEX IF NOT EXISTS idx_memory_atoms_active
  ON agent_memory_atoms(actor_id)
  WHERE superseded_by IS NULL;
CREATE INDEX IF NOT EXISTS idx_memory_atoms_embedding
  ON agent_memory_atoms USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

-- Add 'summarized' to allowed conversation statuses (no constraint exists, just documenting)
-- conversations.status is free-text; we now use: active, escalated, closed, summarized

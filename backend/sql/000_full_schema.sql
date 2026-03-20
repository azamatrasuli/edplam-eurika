-- ============================================================================
-- Eurika AI Agent — Full Database Schema
-- Run this on a FRESH Supabase project to create all tables at once.
-- Combines migrations 001-006 into a single idempotent script.
-- ============================================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================================
-- 1. Core: Conversations + Messages
-- ============================================================================

CREATE TABLE IF NOT EXISTS conversations (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  actor_id          TEXT NOT NULL,
  channel           TEXT NOT NULL,
  agent_role        TEXT NOT NULL DEFAULT 'sales',
  status            TEXT NOT NULL DEFAULT 'active',
  metadata          JSONB NOT NULL DEFAULT '{}'::JSONB,
  escalated_at      TIMESTAMPTZ,
  escalated_reason  TEXT,
  escalated_lead_id BIGINT,
  resolved_at       TIMESTAMPTZ,
  resolved_by       TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conversations_actor_updated
  ON conversations(actor_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_conversations_agent_role
  ON conversations(agent_role);

CREATE TABLE IF NOT EXISTS chat_messages (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id UUID NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  role            TEXT NOT NULL CHECK (role IN ('system', 'user', 'assistant')),
  content         TEXT NOT NULL,
  model           TEXT,
  token_usage     INTEGER,
  metadata        JSONB NOT NULL DEFAULT '{}'::JSONB,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation_created
  ON chat_messages(conversation_id, created_at ASC);

-- ============================================================================
-- 2. RAG: Knowledge Chunks with pgvector
-- ============================================================================

CREATE TABLE IF NOT EXISTS knowledge_chunks (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  namespace   TEXT NOT NULL DEFAULT 'sales',
  source      TEXT NOT NULL,
  section     TEXT,
  chunk_index INTEGER NOT NULL,
  content     TEXT NOT NULL,
  metadata    JSONB DEFAULT '{}',
  embedding   vector(1536) NOT NULL,
  created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chunks_embedding
  ON knowledge_chunks USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);
CREATE INDEX IF NOT EXISTS idx_chunks_source
  ON knowledge_chunks(source);
CREATE INDEX IF NOT EXISTS idx_chunks_namespace
  ON knowledge_chunks(namespace);

-- ============================================================================
-- 3. amoCRM Integration
-- ============================================================================

-- OAuth tokens (shared with Node.js TG bot)
CREATE TABLE IF NOT EXISTS amocrm_tokens (
  account_id    TEXT PRIMARY KEY DEFAULT 'default',
  access_token  TEXT NOT NULL,
  refresh_token TEXT NOT NULL,
  expires_at    TIMESTAMPTZ NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Actor → amoCRM contact mapping
CREATE TABLE IF NOT EXISTS agent_contact_mapping (
  actor_id          TEXT PRIMARY KEY,
  amocrm_contact_id BIGINT NOT NULL,
  contact_name      TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_contact_mapping_amocrm_id
  ON agent_contact_mapping(amocrm_contact_id);

-- Conversation → amoCRM lead mapping
CREATE TABLE IF NOT EXISTS agent_deal_mapping (
  conversation_id   UUID PRIMARY KEY REFERENCES conversations(id) ON DELETE CASCADE,
  amocrm_lead_id    BIGINT NOT NULL,
  amocrm_contact_id BIGINT,
  pipeline_id       BIGINT,
  status_id         BIGINT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_deal_mapping_lead_id
  ON agent_deal_mapping(amocrm_lead_id);

-- ============================================================================
-- 4. amoCRM Chat API (imBox)
-- ============================================================================

CREATE TABLE IF NOT EXISTS agent_chat_mapping (
  id                      SERIAL PRIMARY KEY,
  actor_id                TEXT NOT NULL UNIQUE,
  amocrm_chat_id          TEXT,
  amocrm_conversation_id  TEXT NOT NULL,
  amocrm_contact_id       INTEGER,
  created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_chat_mapping_conversation
  ON agent_chat_mapping(amocrm_conversation_id);

CREATE TABLE IF NOT EXISTS agent_manager_messages (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  actor_id              TEXT NOT NULL,
  conversation_id       TEXT,
  agent_conversation_id UUID REFERENCES conversations(id),
  amocrm_msgid          TEXT,
  sender_name           TEXT,
  content               TEXT NOT NULL,
  delivered             BOOLEAN NOT NULL DEFAULT FALSE,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_manager_messages_actor
  ON agent_manager_messages(actor_id, created_at DESC);

-- Escalation: open escalations for scheduler
CREATE INDEX IF NOT EXISTS idx_conversations_escalation_open
  ON conversations(status, updated_at)
  WHERE status = 'escalated' AND resolved_at IS NULL;

-- ============================================================================
-- 5. Onboarding User Profiles
-- ============================================================================

CREATE TABLE IF NOT EXISTS agent_user_profiles (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  actor_id            TEXT NOT NULL,
  client_type         TEXT NOT NULL CHECK (client_type IN ('existing', 'new')),
  user_role           TEXT NOT NULL CHECK (user_role IN ('parent', 'student')),
  phone               TEXT NOT NULL,
  phone_raw           TEXT,
  fio                 TEXT,
  grade               INT,
  children            JSONB NOT NULL DEFAULT '[]'::JSONB,
  dms_verified        BOOLEAN NOT NULL DEFAULT FALSE,
  dms_contact_id      INT,
  dms_data            JSONB,
  verification_status TEXT NOT NULL DEFAULT 'pending'
    CHECK (verification_status IN ('pending', 'found', 'not_found', 'unexpected_found', 'new_lead')),
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_user_profiles_actor
  ON agent_user_profiles(actor_id);
CREATE INDEX IF NOT EXISTS idx_agent_user_profiles_phone
  ON agent_user_profiles(phone);

-- ============================================================================
-- 6. Triggers: auto-update updated_at
-- ============================================================================

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- conversations
DROP TRIGGER IF EXISTS trg_conversations_updated_at ON conversations;
CREATE TRIGGER trg_conversations_updated_at
  BEFORE UPDATE ON conversations
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- amocrm_tokens
DROP TRIGGER IF EXISTS trg_amocrm_tokens_updated_at ON amocrm_tokens;
CREATE TRIGGER trg_amocrm_tokens_updated_at
  BEFORE UPDATE ON amocrm_tokens
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- agent_contact_mapping
DROP TRIGGER IF EXISTS trg_agent_contact_mapping_updated_at ON agent_contact_mapping;
CREATE TRIGGER trg_agent_contact_mapping_updated_at
  BEFORE UPDATE ON agent_contact_mapping
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- agent_deal_mapping
DROP TRIGGER IF EXISTS trg_agent_deal_mapping_updated_at ON agent_deal_mapping;
CREATE TRIGGER trg_agent_deal_mapping_updated_at
  BEFORE UPDATE ON agent_deal_mapping
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- agent_chat_mapping
DROP TRIGGER IF EXISTS trg_agent_chat_mapping_updated_at ON agent_chat_mapping;
CREATE TRIGGER trg_agent_chat_mapping_updated_at
  BEFORE UPDATE ON agent_chat_mapping
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- agent_user_profiles
DROP TRIGGER IF EXISTS trg_agent_user_profiles_updated_at ON agent_user_profiles;
CREATE TRIGGER trg_agent_user_profiles_updated_at
  BEFORE UPDATE ON agent_user_profiles
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

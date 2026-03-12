-- ============================================================================
-- Eurika AI Agent — Staging Database Schema (Render PostgreSQL)
-- No pgvector (vector extension) — RAG gracefully degrades to empty results.
-- Combines 000_full_schema + 007 + 008.
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS pgcrypto;
-- NOTE: vector extension NOT available on Render free tier
-- RAG search returns [] when knowledge_chunks table doesn't exist

-- ============================================================================
-- 1. Core: Conversations + Messages
-- ============================================================================

CREATE TABLE IF NOT EXISTS conversations (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  actor_id    TEXT NOT NULL,
  channel     TEXT NOT NULL,
  agent_role  TEXT NOT NULL DEFAULT 'sales',
  status      TEXT NOT NULL DEFAULT 'active',
  display_name TEXT,
  metadata    JSONB NOT NULL DEFAULT '{}'::JSONB,
  started_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  ended_at    TIMESTAMPTZ,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
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
-- 2. amoCRM Integration
-- ============================================================================

CREATE TABLE IF NOT EXISTS amocrm_tokens (
  account_id    TEXT PRIMARY KEY DEFAULT 'default',
  access_token  TEXT NOT NULL,
  refresh_token TEXT NOT NULL,
  expires_at    TIMESTAMPTZ NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_contact_mapping (
  actor_id          TEXT PRIMARY KEY,
  amocrm_contact_id BIGINT NOT NULL,
  contact_name      TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_contact_mapping_amocrm_id
  ON agent_contact_mapping(amocrm_contact_id);

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
-- 3. amoCRM Chat API (imBox)
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
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  actor_id        TEXT NOT NULL,
  conversation_id TEXT,
  amocrm_msgid    TEXT,
  sender_name     TEXT,
  content         TEXT NOT NULL,
  delivered       BOOLEAN NOT NULL DEFAULT FALSE,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_manager_messages_actor
  ON agent_manager_messages(actor_id, created_at DESC);

-- ============================================================================
-- 4. Onboarding User Profiles
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
-- 5. Sprint 4: Payment Orders + Follow-up Chain
-- ============================================================================

CREATE TABLE IF NOT EXISTS agent_payment_orders (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id UUID NOT NULL,
  actor_id        TEXT NOT NULL,
  dms_order_uuid  TEXT NOT NULL,
  dms_contact_id  INT,
  product_name    TEXT,
  product_uuid    TEXT,
  amount_kopecks  BIGINT NOT NULL,
  payment_url     TEXT NOT NULL,
  pay_type        INT NOT NULL DEFAULT 1,
  status          TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'paid', 'expired', 'cancelled')),
  amocrm_lead_id  BIGINT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  paid_at         TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_payment_orders_pending
  ON agent_payment_orders(status) WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS agent_followup_chain (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id UUID NOT NULL,
  actor_id        TEXT NOT NULL,
  payment_order_id UUID REFERENCES agent_payment_orders(id) ON DELETE SET NULL,
  step            INT NOT NULL DEFAULT 1,
  status          TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'sent', 'cancelled', 'escalated')),
  next_fire_at    TIMESTAMPTZ NOT NULL,
  sent_at         TIMESTAMPTZ,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_followup_pending
  ON agent_followup_chain(status, next_fire_at) WHERE status = 'pending';

-- ============================================================================
-- 6. Sprint 5: Event Logging
-- ============================================================================

CREATE TABLE IF NOT EXISTS agent_events (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id UUID,
  actor_id        TEXT NOT NULL,
  channel         TEXT,
  agent_role      TEXT DEFAULT 'sales',
  event_type      TEXT NOT NULL,
  event_data      JSONB NOT NULL DEFAULT '{}'::JSONB,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_events_type_created
  ON agent_events(event_type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_events_conversation
  ON agent_events(conversation_id);
CREATE INDEX IF NOT EXISTS idx_agent_events_created
  ON agent_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_events_channel
  ON agent_events(channel);

-- ============================================================================
-- 7. Triggers: auto-update updated_at
-- ============================================================================

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_conversations_updated_at ON conversations;
CREATE TRIGGER trg_conversations_updated_at
  BEFORE UPDATE ON conversations
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_amocrm_tokens_updated_at ON amocrm_tokens;
CREATE TRIGGER trg_amocrm_tokens_updated_at
  BEFORE UPDATE ON amocrm_tokens
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_agent_contact_mapping_updated_at ON agent_contact_mapping;
CREATE TRIGGER trg_agent_contact_mapping_updated_at
  BEFORE UPDATE ON agent_contact_mapping
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_agent_deal_mapping_updated_at ON agent_deal_mapping;
CREATE TRIGGER trg_agent_deal_mapping_updated_at
  BEFORE UPDATE ON agent_deal_mapping
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_agent_chat_mapping_updated_at ON agent_chat_mapping;
CREATE TRIGGER trg_agent_chat_mapping_updated_at
  BEFORE UPDATE ON agent_chat_mapping
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS trg_agent_user_profiles_updated_at ON agent_user_profiles;
CREATE TRIGGER trg_agent_user_profiles_updated_at
  BEFORE UPDATE ON agent_user_profiles
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

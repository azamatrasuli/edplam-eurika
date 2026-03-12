-- ============================================================================
-- 009: Chat History — multi-conversation support
-- Adds title, archived_at, message_count, last_user_message to conversations
-- ============================================================================

-- New columns
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS title TEXT;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS message_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS last_user_message TEXT;

-- Partial index for active (non-archived) conversations per actor+role
CREATE INDEX IF NOT EXISTS idx_conversations_actor_role_active
  ON conversations(actor_id, agent_role, updated_at DESC)
  WHERE archived_at IS NULL;

-- Ensure pg_trgm extension for trigram search (must come before trgm index)
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Full-text search support (Russian config)
CREATE INDEX IF NOT EXISTS idx_conversations_title_trgm
  ON conversations USING gin (title gin_trgm_ops);

-- Sprint 3b: amoCRM Chat API (imBox) mapping for AI Agent
-- Maps agent actor_id to amoCRM conversation for imBox display

CREATE TABLE IF NOT EXISTS agent_chat_mapping (
  id SERIAL PRIMARY KEY,
  actor_id TEXT NOT NULL UNIQUE,
  amocrm_chat_id TEXT,
  amocrm_conversation_id TEXT NOT NULL,
  amocrm_contact_id INTEGER,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_chat_mapping_conversation
  ON agent_chat_mapping(amocrm_conversation_id);

DROP TRIGGER IF EXISTS trg_agent_chat_mapping_updated_at ON agent_chat_mapping;
CREATE TRIGGER trg_agent_chat_mapping_updated_at
BEFORE UPDATE ON agent_chat_mapping
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE IF NOT EXISTS agent_manager_messages (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  actor_id TEXT NOT NULL,
  conversation_id TEXT,
  amocrm_msgid TEXT,
  sender_name TEXT,
  content TEXT NOT NULL,
  delivered BOOLEAN NOT NULL DEFAULT FALSE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_manager_messages_actor
  ON agent_manager_messages(actor_id, created_at DESC);

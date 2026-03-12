-- Sprint 4: Support role + knowledge base namespaces

ALTER TABLE conversations ADD COLUMN IF NOT EXISTS agent_role text NOT NULL DEFAULT 'sales';
CREATE INDEX IF NOT EXISTS idx_conversations_agent_role ON conversations(agent_role);

ALTER TABLE knowledge_chunks ADD COLUMN IF NOT EXISTS namespace text NOT NULL DEFAULT 'sales';
CREATE INDEX IF NOT EXISTS idx_chunks_namespace ON knowledge_chunks(namespace);

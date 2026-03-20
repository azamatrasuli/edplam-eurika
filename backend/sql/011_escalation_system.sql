-- ============================================================================
-- 011: Escalation system — metadata columns + manager message linking
-- Adds escalation tracking fields to conversations,
-- links manager messages back to agent conversations,
-- and indexes for scheduler job (auto-escalation).
-- ============================================================================

-- Escalation metadata on conversations
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS escalated_at TIMESTAMPTZ;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS escalated_reason TEXT;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS escalated_lead_id BIGINT;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS resolved_by TEXT;

-- Link manager messages to agent conversation (for delivery tracking)
ALTER TABLE agent_manager_messages
  ADD COLUMN IF NOT EXISTS agent_conversation_id UUID REFERENCES conversations(id);

-- Index for scheduler: find open escalations efficiently
CREATE INDEX IF NOT EXISTS idx_conversations_escalation_open
  ON conversations(status, updated_at)
  WHERE status = 'escalated' AND resolved_at IS NULL;

-- Backfill: set escalated_at for existing escalated conversations
UPDATE conversations
SET escalated_at = updated_at
WHERE status = 'escalated' AND escalated_at IS NULL;

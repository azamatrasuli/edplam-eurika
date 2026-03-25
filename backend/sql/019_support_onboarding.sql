-- ============================================================================
-- 019: Support Onboarding — state tracking + followup chain extension
-- Sprint: Support S3 (Онбординг + DMS интеграция)
-- ============================================================================

-- 1. Onboarding state table
CREATE TABLE IF NOT EXISTS agent_onboarding (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  payment_order_id  UUID REFERENCES agent_payment_orders(id) ON DELETE SET NULL,
  actor_id          TEXT NOT NULL,
  conversation_id   UUID REFERENCES conversations(id) ON DELETE SET NULL,
  dms_contact_id    INT,
  product_name      TEXT,
  child_name        TEXT,
  child_grade       INT,
  status            TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending','greeting_sent','followup_sent','responded','escalated','completed')),
  greeting_sent_at  TIMESTAMPTZ,
  followup_sent_at  TIMESTAMPTZ,
  client_responded  BOOLEAN NOT NULL DEFAULT FALSE,
  escalated_at      TIMESTAMPTZ,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_onboarding_actor
  ON agent_onboarding(actor_id);
CREATE INDEX IF NOT EXISTS idx_onboarding_status
  ON agent_onboarding(status) WHERE status NOT IN ('completed','escalated');
CREATE INDEX IF NOT EXISTS idx_onboarding_payment
  ON agent_onboarding(payment_order_id);

-- 2. Extend followup chain with type discriminator
ALTER TABLE agent_followup_chain
  ADD COLUMN IF NOT EXISTS chain_type TEXT NOT NULL DEFAULT 'payment';

ALTER TABLE agent_followup_chain
  ADD COLUMN IF NOT EXISTS onboarding_id UUID REFERENCES agent_onboarding(id) ON DELETE SET NULL;

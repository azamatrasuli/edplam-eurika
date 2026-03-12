-- Sprint 4: Onboarding user profiles
-- Stores qualification data collected during onboarding wizard

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

-- updated_at trigger (reuses function from 001)
DROP TRIGGER IF EXISTS trg_agent_user_profiles_updated_at ON agent_user_profiles;
CREATE TRIGGER trg_agent_user_profiles_updated_at
  BEFORE UPDATE ON agent_user_profiles
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

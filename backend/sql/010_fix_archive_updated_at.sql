-- Fix: archiving a conversation should NOT change updated_at.
-- The generic set_updated_at() trigger fires on every UPDATE,
-- including SET archived_at = NOW(), which resets updated_at
-- and breaks date display in the sidebar.
--
-- Solution: use a smarter trigger for conversations only that
-- skips updated_at when the only change is archived_at.

CREATE OR REPLACE FUNCTION set_conversations_updated_at()
RETURNS trigger AS $$
BEGIN
  -- Skip updated_at update when only archived_at changed
  IF (OLD.archived_at IS DISTINCT FROM NEW.archived_at)
     AND OLD.title          IS NOT DISTINCT FROM NEW.title
     AND OLD.status         IS NOT DISTINCT FROM NEW.status
     AND OLD.message_count  IS NOT DISTINCT FROM NEW.message_count
     AND OLD.last_user_message IS NOT DISTINCT FROM NEW.last_user_message
  THEN
    NEW.updated_at = OLD.updated_at;
  ELSE
    NEW.updated_at = NOW();
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Replace the generic trigger with the smart one
DROP TRIGGER IF EXISTS trg_conversations_updated_at ON conversations;
CREATE TRIGGER trg_conversations_updated_at
BEFORE UPDATE ON conversations
FOR EACH ROW EXECUTE FUNCTION set_conversations_updated_at();

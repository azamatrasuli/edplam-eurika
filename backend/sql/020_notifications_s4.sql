-- Migration 020: Sprint 4 Support — Notifications, NPS, Tags
-- Tables: agent_notifications, agent_nps_ratings
-- Extension: conversations.tags

-- 1. Central notification registry
CREATE TABLE IF NOT EXISTS agent_notifications (
    id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    actor_id          TEXT        NOT NULL,
    conversation_id   UUID        REFERENCES conversations(id) ON DELETE SET NULL,
    notification_type TEXT        NOT NULL
        CHECK (notification_type IN (
            'payment_reminder',
            'classes_reminder',
            'homework_reminder',
            'document_reminder',
            'enrollment_congrats',
            'alert_nonresponsive',
            'alert_performance_drop'
        )),
    status            TEXT        NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'sent', 'cancelled', 'failed')),
    scheduled_at      TIMESTAMPTZ NOT NULL,
    sent_at           TIMESTAMPTZ,
    cancelled_at      TIMESTAMPTZ,
    template_data     JSONB       NOT NULL DEFAULT '{}'::JSONB,
    dedup_key         TEXT,           -- format: "{type}:{actor_id}:{date_or_entity}"
    channel           TEXT        NOT NULL DEFAULT 'telegram',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Dedup: один ключ = одно уведомление
CREATE UNIQUE INDEX IF NOT EXISTS idx_notif_dedup
    ON agent_notifications(dedup_key) WHERE dedup_key IS NOT NULL;

-- Быстрый поиск pending для процессора
CREATE INDEX IF NOT EXISTS idx_notif_pending
    ON agent_notifications(status, scheduled_at) WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_notif_actor
    ON agent_notifications(actor_id);

CREATE INDEX IF NOT EXISTS idx_notif_type_status
    ON agent_notifications(notification_type, status);

-- 2. NPS ratings
CREATE TABLE IF NOT EXISTS agent_nps_ratings (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID        NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    actor_id        TEXT        NOT NULL,
    rating          INT         NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment         TEXT,
    agent_role      TEXT        NOT NULL DEFAULT 'support',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_nps_actor
    ON agent_nps_ratings(actor_id);

CREATE INDEX IF NOT EXISTS idx_nps_role_created
    ON agent_nps_ratings(agent_role, created_at);

-- Один NPS на разговор
CREATE UNIQUE INDEX IF NOT EXISTS idx_nps_conv_unique
    ON agent_nps_ratings(conversation_id);

-- 3. Conversation tags (для автотегирования и аналитики)
ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS tags TEXT[] NOT NULL DEFAULT '{}';

CREATE INDEX IF NOT EXISTS idx_conv_tags
    ON conversations USING GIN(tags);

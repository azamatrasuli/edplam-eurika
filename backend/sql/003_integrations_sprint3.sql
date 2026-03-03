-- Sprint 3: CRM integration tables (AI Agent)
-- Run against Supabase PostgreSQL
-- NOTE: amocrm_tokens is shared with Node.js bot; agent mapping tables
--       are prefixed "agent_" to avoid conflicts with bot tables.

-- 1. amoCRM OAuth tokens (shared — used by both bot and agent)
create table if not exists amocrm_tokens (
  account_id text primary key default 'default',
  access_token text not null,
  refresh_token text not null,
  expires_at timestamptz not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- 2. Actor → amoCRM contact mapping (AI Agent)
create table if not exists agent_contact_mapping (
  actor_id text primary key,
  amocrm_contact_id bigint not null,
  contact_name text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- 3. Conversation → amoCRM lead mapping (AI Agent)
create table if not exists agent_deal_mapping (
  conversation_id uuid primary key references conversations(id) on delete cascade,
  amocrm_lead_id bigint not null,
  amocrm_contact_id bigint,
  pipeline_id bigint,
  status_id bigint,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_agent_deal_mapping_lead_id
  on agent_deal_mapping(amocrm_lead_id);

create index if not exists idx_agent_contact_mapping_amocrm_id
  on agent_contact_mapping(amocrm_contact_id);

-- Triggers (reuse set_updated_at from 001_init_sprint1.sql)
drop trigger if exists trg_amocrm_tokens_updated_at on amocrm_tokens;
create trigger trg_amocrm_tokens_updated_at
before update on amocrm_tokens
for each row execute function set_updated_at();

drop trigger if exists trg_agent_contact_mapping_updated_at on agent_contact_mapping;
create trigger trg_agent_contact_mapping_updated_at
before update on agent_contact_mapping
for each row execute function set_updated_at();

drop trigger if exists trg_agent_deal_mapping_updated_at on agent_deal_mapping;
create trigger trg_agent_deal_mapping_updated_at
before update on agent_deal_mapping
for each row execute function set_updated_at();

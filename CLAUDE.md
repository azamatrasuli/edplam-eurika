# CLAUDE.md — AI Agent: Eurika (EdPalm)

> Context for Claude when working in this directory.
> Full project context: /edpalm/CLAUDE.md
> Full PRD: /edpalm/eurika/PRD.md

---

## What we're building

A standalone AI sales agent for EdPalm online school (grades 1-11).
Looks and feels like ChatGPT. Works as: portal widget, Telegram Mini App, or standalone link.

**Stack:** React 19 (frontend) + Python FastAPI (backend) + OpenAI GPT-4o + pgvector RAG

---

## Repository structure

```
eurika/
├── CLAUDE.md           # this file
├── PRD.md              # product requirements
├── brief.md            # original client brief
├── frontend/           # React chat UI (standalone SPA)
│   ├── src/
│   │   ├── components/
│   │   │   ├── ChatWindow.jsx
│   │   │   ├── MessageInput.jsx
│   │   │   ├── TypingIndicator.jsx
│   │   │   ├── PaymentCard.jsx
│   │   │   └── EscalationBanner.jsx
│   │   ├── hooks/
│   │   ├── api/
│   │   └── main.jsx
│   ├── package.json
│   └── vite.config.js
├── backend/            # Python FastAPI AI agent
│   ├── app/
│   │   ├── main.py
│   │   ├── api/        # route handlers (chat.py, health.py)
│   │   ├── agent/      # LLM logic, tools, prompts
│   │   │   ├── prompt.py
│   │   │   └── tools.py
│   │   ├── rag/        # pgvector search, embeddings
│   │   ├── services/   # chat.py, llm.py
│   │   ├── integrations/
│   │   │   └── amocrm.py
│   │   ├── auth/       # JWT, Telegram initData, URL tokens
│   │   ├── db/         # pool.py, repository.py
│   │   └── models/     # Pydantic schemas
│   ├── sql/            # DB migrations
│   │   ├── 001_init_sprint1.sql
│   │   ├── 002_rag_sprint2.sql
│   │   └── 003_integrations_sprint3.sql
│   ├── tests/
│   ├── requirements.txt
│   └── .env.example
└── knowledge_base/     # raw docs for RAG (MD files)
```

---

## Agent identity

- **Name:** Эврика
- **Role:** Sales manager at EdPalm
- **Tone with parents:** respectful, expert, warm — no slang, no over-formality
- **Tone with teens (9-11):** friendly, modern, can use emoji
- **Hard rules:** never invent discounts, prices, or teacher names not in knowledge base

---

## Agent tools (OpenAI function calling)

| Tool | Status | Description |
|---|---|---|
| `search_knowledge_base` | Done (Sprint 2-3) | RAG search over EdPalm product docs |
| `get_amocrm_contact` | Done (Sprint 3) | Find contact in amoCRM by phone or telegram_id |
| `get_amocrm_deal` | Done (Sprint 3) | Get active deal for a contact |
| `create_amocrm_lead` | Done (Sprint 3) | Create contact + deal in amoCRM |
| `update_deal_stage` | Done (Sprint 3) | Update deal status/product/amount in amoCRM |
| `escalate_to_manager` | Done (Sprint 3) | Flag conversation for human takeover + notify via Telegram |
| `get_client_profile` | Blocked (DMS) | Fetch client data from DMS |
| `generate_payment_link` | Blocked (DMS) | Call DMS API -> return payment URL |
| `schedule_followup` | Sprint 4 | Schedule a follow-up message (24h / 48h / 7d) |

---

## Auth — three entry modes

| Mode | How it works |
|---|---|
| Portal | PHP portal issues short-lived JWT -> passed as `?token=` -> backend verifies |
| Telegram Mini App | `initData` HMAC-SHA256 verified with BOT_TOKEN -> user matched by telegram_id |
| External link | Signed one-time URL token (TTL 48h) -> treated as new lead if no match |

---

## Key integrations

**amoCRM** (Done - Sprint 3)
- Subdomain: `azaprimemat`
- Sales pipeline: `10490514` / Service pipeline: `10490518`
- Custom fields: Telegram ID `1396311`, Product `1396313`, Amount `1396315`
- OAuth tokens stored in `amocrm_tokens` table (shared with Node.js TG bot)
- Redirect URI: `https://edpalm-unified-tg-bot.onrender.com/api/amocrm/webhook/...`

**Supabase (PostgreSQL)** — shared between AI Agent and Node.js TG Bot
- Project: `qieftukvzjpcnakimxmo`
- Region: ap-southeast-1 (AWS)
- AI Agent tables: `conversations`, `chat_messages`, `knowledge_chunks`, `agent_contact_mapping`, `agent_deal_mapping`
- Shared table: `amocrm_tokens`
- Bot tables: `contacts`, `deals`, `messages`, `amocrm_contact_mapping`, `amocrm_deal_mapping`, etc.

**DMS API** — Go backend, source code studied (`/dms-main`). REST API on port 8080.
- Blocked: waiting for service account credentials
- Auth: `POST /v1/api/auth` -> JWT
- Client lookup, orders, payment links — all through DMS REST API

**LMS (Moodle)** — accessed through DMS, not directly.

---

## Database schema (shared Supabase)

AI Agent tables use `chat_` and `agent_` prefixes to avoid conflicts with Node.js bot:

```sql
-- Sprint 1
conversations (id uuid PK, actor_id, channel, status, metadata, created_at, updated_at)
chat_messages (id uuid PK, conversation_id FK, role, content, model, token_usage, metadata, created_at)

-- Sprint 2
knowledge_chunks (id serial PK, content, embedding vector(1536), source, metadata, created_at)

-- Sprint 3
amocrm_tokens (account_id text PK, access_token, refresh_token, expires_at)  -- shared
agent_contact_mapping (actor_id text PK, amocrm_contact_id, contact_name)
agent_deal_mapping (conversation_id uuid PK FK, amocrm_lead_id, amocrm_contact_id, pipeline_id, status_id)
```

---

## Sprint progress

| Sprint | Goal | Status |
|---|---|---|
| 1 | FastAPI skeleton + React Chat UI + SSE streaming + Auth | Done |
| 2 | RAG pipeline + knowledge base loader + system prompt | Done |
| 3 | amoCRM + escalation + function calling | Done |
| 4 | All 3 sales scenarios + follow-up scheduler | Next |
| 5 | Dashboard + portal embed | |
| 6 | Closed pilot deploy | |

---

## Deploy

- **Backend (local dev):** `python app/main.py` on port 8009
- **Frontend (local dev):** `npm run dev` on port 5177
- **Render (Node.js TG Bot):** `edpalm-unified-tg-bot` (prod, main branch)
- **Frontend prod:** Vercel (free tier)

## Blockers

| Blocker | Sprint |
|---|---|
| **DMS credentials** — service account login/password for the agent | Sprint 3-4 |

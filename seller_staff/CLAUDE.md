# CLAUDE.md — AI Agent: Sales (EdPalm)

> Context for Claude when working in this directory.
> Full project context: /edpalm/CLAUDE.md
> Full PRD: /edpalm/ai_agent_eurika/saller/PRD.md

---

## What we're building

A standalone AI sales agent for EdPalm online school (grades 1–11).
Looks and feels like ChatGPT. Works as: portal widget, Telegram Mini App, or standalone link.

**Stack:** React 19 (frontend) + Python FastAPI (backend) + OpenAI GPT-4o + pgvector RAG

---

## Repository structure (to be created)

```
saller/
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
│   │   ├── api/        # route handlers
│   │   ├── agent/      # LLM logic, tools, prompts
│   │   ├── rag/        # pgvector search, embeddings
│   │   ├── integrations/
│   │   │   ├── amocrm.py
│   │   │   ├── dms.py
│   │   │   └── lms.py
│   │   ├── auth/       # JWT, Telegram initData, URL tokens
│   │   └── models/     # Pydantic schemas
│   ├── requirements.txt
│   └── .env.example
└── knowledge_base/     # raw docs for RAG (PDFs, MD files)
```

---

## Agent identity

- **Name:** Эврика
- **Role:** Sales manager at EdPalm
- **Tone with parents:** respectful, expert, warm — no slang, no over-formality
- **Tone with teens (9–11):** friendly, modern, can use emoji
- **Hard rules:** never invent discounts, prices, or teacher names not in knowledge base

---

## Agent tools (OpenAI function calling)

| Tool | Description |
|---|---|
| `search_knowledge_base` | RAG search over EdPalm product docs |
| `get_client_profile` | Fetch client data from DMS by user_id or phone |
| `get_student_progress` | Fetch student grades/status via DMS API (DMS wraps Moodle internally) |
| `get_amocrm_deal` | Read active deal from amoCRM |
| `create_amocrm_lead` | Create contact + deal in amoCRM |
| `update_deal_stage` | Move deal to next stage in amoCRM |
| `generate_payment_link` | Call DMS API → return payment URL |
| `escalate_to_manager` | Flag conversation for human takeover + notify via Telegram |
| `schedule_followup` | Schedule a follow-up message (24h / 48h / 7d) |

---

## Auth — three entry modes

| Mode | How it works |
|---|---|
| Portal | PHP portal issues short-lived JWT → passed as `?token=` → backend verifies |
| Telegram Mini App | `initData` HMAC-SHA256 verified with BOT_TOKEN → user matched by telegram_id |
| External link | Signed one-time URL token (TTL 48h) → treated as new lead if no match |

---

## Key integrations

**amoCRM**
- Subdomain: `azaprimemat`
- Sales pipeline: `10490514` / Service pipeline: `10490518`
- Credentials: see `/amocrm_edpalm_bot/.env.development`

**Supabase (PostgreSQL)**
- Used for: conversation history, session state, RAG vectors, scheduled follow-ups
- URL: `https://phleydwqqjevlyfydlbf.supabase.co`
- Credentials: see `/amocrm_edpalm_bot/.env.development`

**DMS API** — Go backend, source code studied (`/dms-main`). REST API on port 8080.
- Auth: `POST /v1/api/auth` → JWT (access 10min + refresh). Agent uses a service account.
- Client lookup: `POST /v1/api/contacts/search` — by phone or email
- Create order: `POST /v1/api/orders`
- Payment link: `POST /v1/api/payment/link` — Tochka Bank (already integrated in DMS)
- Payment confirm: `POST /v1/api/payment/confirm` — triggered by webhook
- Student progress: available via DMS (Moodle is wrapped inside DMS — no direct Moodle calls needed)

**LMS (Moodle)** — accessed through DMS, not directly. No separate integration needed.

---

## Sales scenarios

1. **New lead** — qualify → match product → handle objections → payment link → follow-up
2. **Renewal** — triggered by CRM event → NPS → present next period → payment link → follow-up
3. **Cross-sell / Upsell** — detect fit → pitch add-on product → payment link

**Escalation triggers:** client asks for human / negative sentiment / unknown question / price not in KB

---

## Conversation storage (Supabase)

```sql
conversations (id, user_id, channel, started_at, status, amocrm_deal_id)
messages (id, conversation_id, role, content, tool_calls, created_at)
followups (id, conversation_id, scheduled_at, sent, message_template)
```

---

## Sprint plan

| Sprint | Goal |
|---|---|
| 1 | FastAPI skeleton + React Chat UI + SSE streaming + Auth |
| 2 | RAG pipeline + knowledge base loader + system prompt |
| 3 | amoCRM + DMS payments + escalation |
| 4 | All 3 sales scenarios + follow-up scheduler |
| 5 | Dashboard + portal embed |
| 6 | Closed pilot deploy |

---

## Deploy

- **Backend:** VPS (server provided by client)
- **Frontend:** Vercel (free tier)

## Blockers

| Blocker | Sprint |
|---|---|
| **Knowledge base content** — product texts, FAQ, objection scripts | Sprint 2 |
| **DMS credentials** — service account login/password for the agent | Sprint 3 |

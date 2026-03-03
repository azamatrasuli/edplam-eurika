# CLAUDE.md — AI Agent: Support (EdPalm)

> Context for Claude when working in this directory.
> Full project context: /edpalm/CLAUDE.md
> Full PRD: /edpalm/ai_agent_eurika/support/PRD.md

---

## What we're building

AI support agent for EdPalm — same "Эврика" platform as the sales agent, different role.
The portal map has multiple buildings. When user enters the "Support" building, Эврика switches to customer service mode.
Same React chat UI, same Python FastAPI backend — role is determined by entry point context.

---

## How role switching works

| Building (portal) | Эврика role | amoCRM pipeline |
|---|---|---|
| Магазин (Shop) | Sales manager | Sales `10490514` |
| Служба поддержки | CS manager | Service `10490518` |

The backend receives the building context at session start and loads the appropriate system prompt and toolset.

---

## Repository structure (to be created)

```
support/
├── CLAUDE.md           # this file
├── PRD.md              # product requirements
├── brief.md            # original client brief
└── (code lives in shared saller/ infra — same backend, same frontend)
```

Support agent does NOT have a separate codebase — it shares the same FastAPI backend and React frontend as the sales agent. The difference is:
- Different system prompt loaded based on `agent_role = "support"`
- Different toolset (no payment link generation, adds notification tools)
- Different amoCRM pipeline

---

## Agent identity

- **Name:** Эврика
- **Role:** Customer service manager at EdPalm
- **Tone — Parents:** Official, empathetic, calming. Focus on documents, payments, results
- **Tone — Students (1–4):** Friendly, simple language, no complex words
- **Tone — Students (5–8):** Friendly, supportive
- **Tone — Students (9–11):** Peer-level, modern, emoji ok
- **Tone — CS Managers:** Technical, structured, concise alerts
- **Hard rules:** Never reveal other clients' data. Never request full card numbers. Only answer from knowledge base.

---

## Agent tools (OpenAI function calling)

| Tool | Description |
|---|---|
| `search_knowledge_base` | RAG search over support KB (FAQ, regulations, GIA) |
| `get_client_profile` | DMS API: tariff, name, phone, status |
| `get_student_status` | DMS API: enrollment status, grades, attendance (Moodle via DMS) |
| `get_amocrm_ticket` | Read current service ticket from amoCRM |
| `create_amocrm_ticket` | Create escalation ticket in Service pipeline |
| `send_telegram_notification` | Push message to client's Telegram |
| `notify_manager_cs` | Alert CS manager in Telegram |
| `schedule_reminder` | Queue a trigger notification (date, template, user_id) |
| `collect_nps` | Send NPS survey after issue resolved |
| `tag_conversation` | Auto-tag conversation (#payment, #docs, #platform_error, etc.) |
| `generate_weekly_report` | AI summary report for CS head |

---

## Scenarios

1. **Inbound question** — client writes → RAG search → answer → NPS
2. **Onboarding** — triggered by payment webhook → welcome message → 24h follow-up
3. **Trigger notifications** — scheduled reminders (payment, homework, docs, class start)
4. **Manager alerts** — 48h ignore → alert CS manager; grade drop → alert CS manager
5. **GIA support** — exam dates, checklists, FAQ for grades 9–11
6. **Escalation** — unknown question / negativity → amoCRM ticket + CS manager notified

---

## Trigger notification schedule

| Trigger | Timing | Target |
|---|---|---|
| Payment reminder | 3 days, 1 day, day of | Client |
| Class start reminder | 1 day before | Client |
| Homework deadline | 1 day before | Client |
| Documents not uploaded | Day 3 of no action | Client |
| Post-enrollment | Day of order | Client |
| Client ignoring agent 48h | After 48h | CS Manager |
| Grade drop / low attendance | When detected in DMS | CS Manager |

---

## Key integrations

**amoCRM**
- Service pipeline: `10490518`
- Credentials: see `/amocrm_edpalm_bot/.env.development`

**DMS API** — Go backend, source code at `/dms-main`
- Client profile: `POST /v1/api/contacts/search`
- Student status / grades: via DMS (Moodle wrapped inside)
- Auth: `POST /v1/api/auth` → JWT. Uses service account credentials.

**Supabase**
- Conversations, messages, scheduled reminders, RAG vectors
- URL: `https://phleydwqqjevlyfydlbf.supabase.co`

**Telegram Bot** (`miniapp_edpalm_bot`)
- Proactive notifications to clients
- Alerts to CS managers on escalation

---

## Sprint plan

| Sprint | Goal |
|---|---|
| 1 | Role switching infra: support system prompt + entry context |
| 2 | Support knowledge base + FAQ scenario |
| 3 | Personalization by tariff/status + escalation to CS |
| 4 | Trigger notifications (client + manager alerts) |
| 5 | Onboarding + GIA module + NPS |
| 6 | Analytics, tagging, weekly report dashboard |
| 7 | Closed pilot deploy |

---

## Blockers

| Blocker | Sprint |
|---|---|
| **Knowledge base** — FAQ, regulations, GIA reference, tariff descriptions | Sprint 2 |
| **DMS credentials** — shared with sales agent, one service account for both | Sprint 3 |
| **CS system decision** — amoCRM or separate tool for CS team | Sprint 3 |

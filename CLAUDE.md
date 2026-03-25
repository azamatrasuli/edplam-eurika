# CLAUDE.md — ИИ-агент Эврика (EdPalm)

> Контекст для Claude при работе в этой директории.
> Полный контекст проекта: /edpalm/CLAUDE.md

---

## Что мы строим

ИИ-агент Эврика — три роли в одной платформе:
1. **Продавец** — виртуальный менеджер по продажам
2. **Поддержка** — менеджер клиентского сервиса
3. **Учитель** — виртуальный учитель для учеников

Выглядит как ChatGPT. Работает на портале, в Telegram Mini App и по внешней ссылке.

**Стек:** React 19 (frontend) + Python FastAPI (backend) + OpenAI GPT-4o + pgvector RAG

---

## Структура репозитория

```
eurika/
├── CLAUDE.md              # этот файл
├── PRD.md                 # обзор продукта (все 3 роли)
├── frontend/              # React SPA (общий для всех ролей)
│   ├── src/
│   │   ├── components/    # ChatWindow, MessageInput, VoiceRecorder, etc.
│   │   ├── hooks/         # useChat.js, useOnboarding.js
│   │   ├── api/           # client.js
│   │   └── lib/           # authContext.js
│   └── package.json
├── backend/               # Python FastAPI (общий для всех ролей)
│   ├── app/
│   │   ├── main.py
│   │   ├── api/           # chat.py, conversations.py, dashboard.py, onboarding.py, profile.py, consent.py, renewal.py, telegram.py
│   │   ├── agent/         # prompt.py (sprint5-v1), tools.py (sales 11 / support 8 / teacher 5)
│   │   ├── rag/           # search.py, loader.py
│   │   ├── services/      # chat.py, llm.py, onboarding.py, payment.py, memory.py, summarizer.py, notifications.py, scheduler.py, followup.py, funnel.py, nps.py, tagger.py, imbox.py, auto_escalation.py, telegram_sender.py, data_lifecycle.py, support_onboarding.py
│   │   ├── integrations/  # amocrm.py, amocrm_chat.py, dms.py
│   │   ├── auth/          # service.py, portal.py, telegram.py, external.py
│   │   ├── db/            # pool.py, repository.py, dashboard.py, events.py, memory_repository.py, consent_repository.py
│   │   ├── models/        # chat.py, onboarding.py, profile.py, dashboard.py, errors.py
│   │   └── pipeline/      # webinar → KB pipeline (CLI: extract_audio → transcribe → topics → clean → markdown → load_rag)
│   ├── sql/               # 001-020 миграции
│   ├── requirements.txt
│   └── .env.example
├── seller_staff/          # Роль: Продавец
│   ├── CLAUDE.md          # контекст роли
│   ├── TZ.md              # техническое задание
│   └── knowledge_base/    # 8 MD файлов для RAG (namespace: sales)
├── support_staff/         # Роль: Поддержка
│   ├── CLAUDE.md          # контекст роли
│   ├── TZ.md              # техническое задание
│   └── knowledge_base/    # 10 MD файлов для RAG (namespace: support, 94 чанка)
└── teacher_staff/         # Роль: Учитель
    ├── CLAUDE.md          # контекст роли
    ├── TZ.md              # техническое задание
    └── knowledge_base/    # (будущее)
```

---

## Аутентификация (три режима)

| Режим | Как работает |
|---|---|
| Portal | PHP портал выдаёт JWT (TTL 15 мин) → `?token=` → бэкенд верифицирует |
| Telegram Mini App | `initData` HMAC-SHA256 с BOT_TOKEN → пользователь по telegram_id |
| Внешняя ссылка | Подписанный одноразовый токен (TTL 48ч) → новый лид |

---

## Ключевые интеграции

**amoCRM** (Sprint 3, полностью работает)
- Subdomain: `azamatrasuli`
- Sales pipeline: `10689842` / Service pipeline: `10689990`
- Custom fields: Telegram ID `1404988`, Product `1404990`, Amount `1404992`
- OAuth токены в `amocrm_tokens` (shared с TG ботом)

**Supabase (PostgreSQL)** — shared между AI Agent и Node.js TG Bot
- Project: `vlywxexthbxehtmopird`
- AI Agent таблицы: `conversations`, `chat_messages`, `knowledge_chunks`, `agent_contact_mapping`, `agent_deal_mapping`, `agent_user_profiles`
- Shared: `amocrm_tokens`

**DMS API** — Go backend (`/dms-main`). REST API.
- Auth: `POST /v1/api/auth` → JWT (пароль хешируется SHA-256 с солью)
- Ответы в camelCase (`accessToken`, `moodleId`, `enrollmentSchool`)
- Телефоны в формате `8 (XXX) XXX-XX-XX`
- Цепочка профиля: contacts/search → POST /students → ученики с product/state
- Клиенты, заказы, платёжные ссылки

**LMS (Moodle)** — через DMS, не напрямую.

---

## Спринты по ролям

### Продавец (seller_staff/TZ.md)

| Спринт | Даты | Статус |
|---|---|---|
| 1 — Основа | 09.03 – 16.03 | Done |
| 2 — База знаний | 16.03 – 23.03 | Done |
| 3 — Целевые действия | 23.03 – 03.04 | Done |
| 4 — Сценарии + follow-up | 06.04 – 13.04 | Done |
| 5 — Дашборд + портал | 13.04 – 20.04 | Done |
| 6 — Пилот | 20.04 – 30.04 | Следующий |

### Поддержка (support_staff/TZ.md)

| Спринт | Даты | Статус |
|---|---|---|
| 1 — Переключение ролей + DMS + RAG | 06.04 – 13.04 | Done |
| 2 — База знаний КС (94 чанка, 10 файлов) | 13.04 – 20.04 | Done |
| 3 — Онбординг + DMS | 20.04 – 04.05 | Done |
| 4 — Уведомления + NPS + теги | 04.05 – 18.05 | Done |
| 5 — Чек-листы + ГИА | 18.05 – 01.06 | Следующий |
| 6 — Аналитика | 01.06 – 16.06 | — |
| 7 — Пилот | 16.06 – 30.06 | — |

### Учитель (teacher_staff/TZ.md)

| Спринт | Даты | Статус |
|---|---|---|
| 1–4 | Дек 2025 – Апр 2026 | Завершены |
| 5 — Проактивность | Апр – 12.05 | Следующий |
| 6 — Подготовка к аттестациям | 12.05 – 15.06 | — |
| 7–10 — Генерация материалов | 15.06 – 31.08 | — |

---

## Загрузка базы знаний (RAG)

```bash
# Из eurika/backend/:
PYTHONPATH=. python -m app.rag.loader --namespace sales --dir ../seller_staff/knowledge_base/
PYTHONPATH=. python -m app.rag.loader --namespace support --dir ../support_staff/knowledge_base/
```

---

## Деплой

- **Backend (dev):** `PYTHONPATH=. .venv/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8009 --reload`
- **Frontend (dev):** `npm run dev` (port 5177)
- **Frontend prod:** Vercel
- **Node.js TG Bot:** Render (`edpalm-unified-tg-bot`)

---

## Реализованные компоненты

**Backend (50 эндпоинтов, prompt sprint5-v1):**
- Chat (SSE streaming, tool execution loop до 5 итераций)
- Conversations (CRUD, search, archive, pagination)
- Dashboard (metrics, conversations, escalations, unanswered — API key auth)
- Profile (CRUD, memory management)
- Consent (ФЗ-152: grant/revoke/status)
- Data lifecycle (export JSON, deletion с 14-дневным recovery)
- Onboarding (DMS verification by phone)
- Manager mode (connect/handback/approve)
- Admin (trigger-renewals, check-stale-deals, reload-settings)
- Telegram webhook
- amoCRM Chat webhook (amojo)
- Scheduler (APScheduler: onboarding checks 2мин, payment reminders 6ч, alerts 30мин)

**Frontend (4 страницы):**
- ChatPage — основной чат (SSE, voice I/O, markdown, rich messages, cold-start UI)
- DashboardPage — KPI, графики (Recharts), фильтры
- SupervisorPage — мониторинг диалогов, manager connect
- ProfilePage — профиль, память, consent, GDPR

---

## Блокеры

| Блокер | Влияет на | Статус |
|---|---|---|
| ~~Чек-листы от заказчика~~ | ~~Поддержка Sprint 5~~ | Закрыт (всё в KB из файла db) |
| **Расписание** — автоматизация не завершена | Учитель Sprint 5 | Ожидает |
| **Аттестационные материалы** — нужны от методистов | Учитель Sprint 6 | Ожидает |
| **DMS schedule/grades API** — эндпоинты не предоставлены | Уведомления о занятиях, алерты успеваемости | STUB в коде |

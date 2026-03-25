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
│   │   ├── api/           # chat.py, onboarding.py
│   │   ├── agent/         # prompt.py, tools.py
│   │   ├── rag/           # search.py, loader.py
│   │   ├── services/      # chat.py, llm.py, onboarding.py
│   │   ├── integrations/  # amocrm.py, amocrm_chat.py, dms.py
│   │   ├── auth/          # portal.py, telegram.py, external.py
│   │   ├── db/            # pool.py, repository.py
│   │   └── models/        # chat.py, onboarding.py
│   ├── sql/               # 001-006 миграции
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
| 4 — Сценарии | 06.04 – 13.04 | Следующий |
| 5 — Дашборд | 13.04 – 20.04 | — |
| 6 — Пилот | 20.04 – 30.04 | — |

### Поддержка (support_staff/TZ.md)

| Спринт | Даты | Статус |
|---|---|---|
| 1 — Переключение ролей + DMS + RAG | 06.04 – 13.04 | Done |
| 2 — База знаний КС (94 чанка, 10 файлов) | 13.04 – 20.04 | Done |
| 3 — Онбординг + DMS | 20.04 – 04.05 | In Progress |
| 4 — Уведомления | 04.05 – 18.05 | — |
| 5 — Чек-листы + ГИА | 18.05 – 01.06 | — |
| 6 — Аналитика | 01.06 – 16.06 | — |
| 7 — Пилот | 16.06 – 30.06 | — |

### Учитель (teacher_staff/TZ.md)

| Спринт | Даты | Статус |
|---|---|---|
| 1–4 | Дек 2025 – Апр 2026 | Завершены |
| 5 — Проактивность | Апр – 12.05 | — |
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

## Блокеры

| Блокер | Влияет на |
|---|---|
| **Чек-листы от заказчика** — содержание процессов | Поддержка Sprint 5 |

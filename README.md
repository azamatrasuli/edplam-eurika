# AI Agent Seller - Sprint 1 MVP

Реализация спринта 1 из `dev_plan.md`:
- React Chat UI (streaming)
- FastAPI backend + OpenAI GPT-4o
- 3 режима входа (portal JWT / Telegram initData / external signed token)
- Сохранение диалогов и сообщений в PostgreSQL/Supabase

## Структура

- `frontend/` - SPA чат
- `backend/` - FastAPI API
- `backend/sql/001_init_sprint1.sql` - миграция таблиц

## Быстрый старт

### 1. Backend

```bash
cd ai_agent_eurika/saller/backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8009
```

### 2. DB миграция

Примените SQL из `backend/sql/001_init_sprint1.sql` в Supabase/PostgreSQL.

### 3. Frontend

```bash
cd ai_agent_eurika/saller/frontend
npm install
cp .env.example .env
npm run dev
```

Откройте:
- портал режим: `http://localhost:5177/?token=<jwt>`
- external режим: `http://localhost:5177/?t=<signed-token>`
- telegram режим: внутри Telegram Mini App

## Проверка

Backend health:

```bash
curl -sS http://127.0.0.1:8009/health
```

Smoke tests:

```bash
cd ai_agent_eurika/saller/backend
pytest -q
```

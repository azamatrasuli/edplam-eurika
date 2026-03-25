# Эврика — ИИ-агент EdPalm

Три роли в одной платформе:
- **Продавец** — виртуальный менеджер по продажам
- **Поддержка** — менеджер клиентского сервиса
- **Учитель** — виртуальный учитель для учеников

Стек: React 19 + Python FastAPI + OpenAI GPT-4o + pgvector RAG

## Структура

```
eurika/
├── backend/               # Python FastAPI
├── frontend/              # React SPA
├── seller_staff/          # Роль: Продавец (TZ + база знаний)
├── support_staff/         # Роль: Поддержка (TZ + база знаний)
├── teacher_staff/         # Роль: Учитель (TZ)
└── PRD.md                 # Обзор продукта
```

## Быстрый старт

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # заполнить ключи
PYTHONPATH=. .venv/bin/python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8009 --reload
```

### Frontend

```bash
cd frontend
npm install
cp .env.example .env
npm run dev                    # http://localhost:5177
```

### DB миграции

Применить SQL из `backend/sql/` в Supabase/PostgreSQL (файлы 001–020).

### Загрузка базы знаний (RAG)

```bash
cd backend
PYTHONPATH=. python -m app.rag.loader --namespace sales --dir ../seller_staff/knowledge_base/
PYTHONPATH=. python -m app.rag.loader --namespace support --dir ../support_staff/knowledge_base/
```

## Режимы входа

- **Портал:** `http://localhost:5177/?token=<jwt>`
- **Telegram Mini App:** внутри бота `miniapp_edpalm_bot`
- **Внешняя ссылка:** `http://localhost:5177/?t=<signed-token>`

## Проверка

```bash
curl -sS http://127.0.0.1:8009/health
cd backend && pytest -q
```

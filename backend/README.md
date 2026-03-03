# Backend (Sprint 1)

## Реализовано

- FastAPI service
- `/health`
- `/api/v1/conversations/start`
- `/api/v1/chat/stream` (SSE)
- `/api/v1/conversations/{id}/messages`
- auth: portal JWT / telegram initData / external signed token
- PostgreSQL persistence + in-memory fallback

## Запуск

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8009
```

## SQL

`sql/001_init_sprint1.sql`

## Тесты

```bash
pytest -q
```

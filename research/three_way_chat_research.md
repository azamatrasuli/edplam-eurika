# Three-Way Chat Research — EdPalm Eurika

## Проблема

Клиент написал "да" менеджеру → AI перехватил и ответил "есть ли московская регистрация?"

## Корневая причина

В chat_stream() нет проверки "активен ли менеджер". Все клиентские сообщения ВСЕГДА идут в LLM.

## Решение: manager_is_active state

### БД: добавить в conversations
- manager_is_active BOOLEAN DEFAULT FALSE
- last_manager_activity_at TIMESTAMPTZ

### Логика маршрутизации в chat_stream:
```
IF actor == manager → save as manager_message, broadcast via WS
ELIF conversation.manager_is_active → save as user_message, broadcast to manager via WS, НЕ вызывать LLM
ELSE → обычный LLM flow
```

### Переключение режимов:
- Менеджер пишет сообщение → manager_is_active = TRUE
- Менеджер нажимает "Вернуть ИИ" → manager_is_active = FALSE
- 30 мин без активности менеджера → auto manager_is_active = FALSE

## Файлы для изменения
- backend/sql/013_manager_active.sql — миграция
- backend/app/api/chat.py — routing logic
- backend/app/db/repository.py — get/set manager_is_active
- frontend/src/hooks/useChat.js — UI state для manager_active

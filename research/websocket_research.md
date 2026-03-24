# WebSocket Research — EdPalm Eurika

## Ключевые выводы

1. FastAPI 0.116.1 поддерживает WebSocket нативно
2. Можно добавить WS рядом с SSE без ломающих изменений
3. Нужен WebSocketManager — in-memory registry connections по conversation_id
4. Auth через первое сообщение (type: "auth")
5. Fallback на SSE если WS недоступен
6. ~150 строк нового кода

## Архитектура

```
Client ←→ WebSocket ←→ Backend ←→ DB
Manager ←→ WebSocket ←→ Backend ←→ DB
                   ↕
              WebSocketManager
         (broadcast по conversation_id)
```

## Файлы для изменения
- backend/app/services/ws_manager.py (новый) — WebSocketManager
- backend/app/api/chat.py — WS endpoint /chat/ws/{conv_id}
- frontend/src/api/client.js — WS transport
- frontend/src/hooks/useChat.js — убрать polling, использовать WS

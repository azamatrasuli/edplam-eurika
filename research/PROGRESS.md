# Прогресс: Реактивность + Три роли + Супервизор

## Фаза 1: Маршрутизация (три роли) — ✅ DONE
- [x] 1.1 SQL миграция 013_manager_routing — применена на Supabase
- [x] 1.2 Repository: set/get manager_is_active, is_manager_active
- [x] 1.3 Backend: routing в chat_stream (client → manager когда active, skip LLM)
- [x] 1.4 Backend: auto-activate при первом сообщении менеджера
- [x] 1.5 Backend: endpoint "вернуть ИИ" POST /manager/handback/{conv_id}
- [x] 1.6 Frontend: кнопка "Вернуть ИИ" в хедере менеджера
- [x] 1.7 Frontend: обработка status event (manager_active)

## Фаза 2: SSE Live Channel (реактивность) — ✅ DONE
- [x] 2.1 Repository: get_messages_since
- [x] 2.2 Backend: GET /chat/listen/{conv_id} — SSE keep-alive (1.5s interval)
- [x] 2.3 Frontend: EventSource listener (заменил polling)
- [x] 2.4 Дедупликация сообщений (dbId + content check)

## Фаза 3: Supervisor View — ✅ DONE
- [x] 3.1 Backend: GET /dashboard/conversations/{id}/messages
- [x] 3.2 Frontend: SupervisorPage.jsx (список + read-only history + фильтры)
- [x] 3.3 Frontend: route /#/supervisor
- [x] 3.4 Кнопка "Подключиться" из supervisor → manager mode

## E2E Test — ✅ ALL PASSED
- [x] Клиент → AI отвечает
- [x] Менеджер пишет → manager_is_active = true
- [x] Клиент пишет "да" → НЕ идёт в AI, идёт менеджеру
- [x] Handback → manager_is_active = false
- [x] Клиент → AI снова отвечает
- [x] SSE Listen endpoint работает

## Ссылки
- Клиент: `/#/?guest_id=ID&conv=CONV_ID&role=sales`
- Менеджер: `/#/?conv=CONV_ID&manager_key=KEY&role=sales`
- Supervisor: `/#/supervisor?key=KEY`
- Approve: `/api/v1/manager/approve/CONV_ID?key=KEY`
- Handback: `/api/v1/manager/handback/CONV_ID?key=KEY`

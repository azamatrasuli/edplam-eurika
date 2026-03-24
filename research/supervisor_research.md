# Supervisor View Research — EdPalm Eurika

## Что уже есть
- DashboardPage с метриками (/#/dashboard)
- Dashboard API: metrics, conversations, escalations, unanswered
- dashboard_api_key auth
- DashboardRepository с SQL-агрегациями

## Что нужно
1. Enriched conversation list: + last_message, + client_name, + manager_status
2. Read-only conversation view: GET /dashboard/conversations/{id}/messages
3. Frontend SupervisorPage: список всех диалогов + клик → история
4. Route: /#/supervisor

## Можно переиспользовать
- dashboard.js API client
- DashboardRepository.get_conversations()
- manager_key auth pattern
- ChatWindow component (isManagerView + readOnly mode)

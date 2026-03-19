# Eurika — Чек-лист тестирования

> **Дата:** 2026-03-20
> **Статусы:** ⬜ Не проверено · ✅ Работает · ❌ Баг · ⚠️ Частично
> **Токены живут 2 часа** (Portal JWT) / 48 часов (External). Перегенерировать: попросить Claude.

---

## Ссылки для тестирования

### Инфраструктура

| Среда | URL |
|---|---|
| Frontend (Vercel) | https://edplam-eurika.vercel.app |
| Backend Prod (Render) | https://edplam-eurika.onrender.com |
| Backend Staging (Render) | https://edplam-eurika-staging.onrender.com |
| Telegram Bot | @miniapp_edpalm_bot |
| amoCRM | https://azamatrasuli.amocrm.ru |
| Supabase | https://supabase.com/dashboard/project/vlywxexthbxehtmopird |
| Render Dashboard | https://dashboard.render.com/web/srv-d6p5lgp5pdvs739s999g |
| Vercel Dashboard | https://vercel.com/azamatrasuli-protonmes-projects/frontend |

### Готовые ссылки с токенами

#### Seller (роль по умолчанию)

| Кейс | Ссылка |
|---|---|
| **Portal JWT** (Тестовый Ученик, +79246724447) | https://edplam-eurika.vercel.app?token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyX2lkIjoidGVzdF9zdHVkZW50XzAwMSIsIm5hbWUiOiJcdTA0MjJcdTA0MzVcdTA0NDFcdTA0NDJcdTA0M2VcdTA0MzJcdTA0NGJcdTA0MzkgXHUwNDIzXHUwNDQ3XHUwNDM1XHUwNDNkXHUwNDM4XHUwNDNhIiwicGhvbmUiOiIrNzkyNDY3MjQ0NDciLCJhZ2VudF9yb2xlIjoic2VsbGVyIiwiZXhwIjoxNzczOTY0Njc4fQ.o6ebuREoSFq3vjsdJ1P86S_fKV9pTrb6BTlqad6T39g |
| **External Link** (новый лид, TTL 48ч) | https://edplam-eurika.vercel.app?t=test_lead_12345:1774130278:654d783b4d968fd5078620daf960b0df2f8565bb2a6092127486d9409bfdbbd1 |
| **Guest** (без авторизации) | https://edplam-eurika.vercel.app (incognito) |

#### Support

| Кейс | Ссылка |
|---|---|
| **Portal JWT** (Анна Тестова, +79161234567) | https://edplam-eurika.vercel.app?token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyX2lkIjoidGVzdF9jbGllbnRfMDAyIiwibmFtZSI6Ilx1MDQxMFx1MDQzZFx1MDQzZFx1MDQzMCBcdTA0MjJcdTA0MzVcdTA0NDFcdTA0NDJcdTA0M2VcdTA0MzJcdTA0MzAiLCJwaG9uZSI6Iis3OTE2MTIzNDU2NyIsImFnZW50X3JvbGUiOiJzdXBwb3J0IiwiZXhwIjoxNzczOTY0Njc4fQ.U9DMNay5LICJ4KA6wLU_KTydJxZGFiReL13QRsVElUk&role=support |

#### Teacher

| Кейс | Ссылка |
|---|---|
| **Portal JWT** (Максим Школьников, +79031112233) | https://edplam-eurika.vercel.app?token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VyX2lkIjoidGVzdF9zdHVkZW50XzAwMyIsIm5hbWUiOiJcdTA0MWNcdTA0MzBcdTA0M2FcdTA0NDFcdTA0MzhcdTA0M2MgXHUwNDI4XHUwNDNhXHUwNDNlXHUwNDNiXHUwNDRjXHUwNDNkXHUwNDM4XHUwNDNhXHUwNDNlXHUwNDMyIiwicGhvbmUiOiIrNzkwMzExMTIyMzMiLCJhZ2VudF9yb2xlIjoidGVhY2hlciIsImV4cCI6MTc3Mzk2NDY3OH0.jzcDqAM_SXnqWHrdikScSTAscKNTQhKho3LUNAg6Efg |

#### Telegram

| Кейс | Как |
|---|---|
| Mini App | Telegram → @miniapp_edpalm_bot → нажать кнопку **Open** |

#### Dashboard

| Кейс | Ссылка |
|---|---|
| Dashboard Prod | https://edplam-eurika.vercel.app/#/dashboard?key=eureka-dash-2026-prod |
| Dashboard Staging | https://edplam-eurika.vercel.app/#/dashboard?key=eureka-dash-2026-staging |

#### amoCRM (проверка результатов)

| Кейс | Ссылка |
|---|---|
| Sales pipeline | https://azamatrasuli.amocrm.ru/leads/pipeline/10689842 |
| Service pipeline | https://azamatrasuli.amocrm.ru/leads/pipeline/10689990 |

---

## 1. АУТЕНТИФИКАЦИЯ

| # | Фича | Как тестировать | Роль | Статус | Баг / Заметка |
|---|---|---|---|---|---|
| 1.1 | Portal JWT (Seller) | Открыть ссылку Seller Portal JWT выше | Seller | ⬜ | |
| 1.2 | Portal JWT (Support) | Открыть ссылку Support Portal JWT выше | Support | ⬜ | |
| 1.3 | Portal JWT (Teacher) | Открыть ссылку Teacher Portal JWT выше | Teacher | ⬜ | |
| 1.4 | External link | Открыть ссылку External Link выше | Seller | ⬜ | |
| 1.5 | Telegram Mini App | Telegram → @miniapp_edpalm_bot → Open | Все | ⬜ | |
| 1.6 | Guest (без токена) | Открыть https://edplam-eurika.vercel.app в incognito | Seller | ⬜ | |
| 1.7 | Expired token | Подождать 2ч+ → попробовать ссылку → должен отказать | Все | ⬜ | |

---

## 2. ЧАТ (ядро)

| # | Фича | Как тестировать | Роль | Статус | Баг / Заметка |
|---|---|---|---|---|---|
| 2.1 | Отправка сообщения | Написать → получить ответ стримингом | Все | ✅ | |
| 2.2 | Стриминг (SSE) | Токены появляются плавно, не блоком | Все | ✅ | |
| 2.3 | Markdown рендеринг | Спросить про продукты — жирный, списки, таблицы | Все | ✅ | |
| 2.4 | История сообщений | 3+ сообщений → обновить → история на месте | Все | ✅ | |
| 2.5 | Новый диалог | Кнопка "+" → чистый чат | Все | ✅ | |
| 2.6 | Переключение диалогов | Сайдбар → клик → загрузка другого диалога | Все | ✅ | |
| 2.7 | Поиск диалогов | Поиск в сайдбаре по тексту | Все | ✅ | |
| 2.8 | Автозаголовок | Новый диалог → после 1-го ответа заголовок | Все | ✅ | |
| 2.9 | Ограничение длины | >4000 символов → ошибка | Все | ⬜ | |
| 2.10 | Архивация | Удалить/архивировать диалог | Все | ⬜ | |

---

## 3. ГОЛОС

| # | Фича | Как тестировать | Роль | Статус | Баг / Заметка |
|---|---|---|---|---|---|
| 3.1 | Запись голоса | Нажать микрофон → записать → отправить | Все |  ✅  | |
| 3.2 | Транскрипция (Whisper) | Отправить голосовое → текст распознан | Все |  ✅  | |
| 3.3 | Ответ на голосовое | Голосовое → агент отвечает текстом (стриминг) | Все | ⬜ | |

---

## 4. RAG (База знаний)

| # | Фича | Как тестировать | Роль | Статус | Баг / Заметка |
|---|---|---|---|---|---|
| 4.1 | Поиск по продуктам | "Какие тарифы есть?" | Seller | ✅ | Базовый 12 500, Классный 70 000, Персональный 250 000 — из KB |
| 4.2 | Поиск по компании | "Сколько учеников у EdPalm?" | Seller | ✅ | "Более 75 000 учеников" — из KB |
| 4.3 | Поиск по аттестации | "Как проходит аттестация?" | Seller | ✅ | Онлайн-тесты, 30-35 вопросов, 2 попытки — из KB |
| 4.4 | Поиск по зачислению | "Как начать учиться?" | Seller | ✅ | Фикс: добавлены триггеры в промпт (de33433). RAG возвращает 7 шагов зачисления из KB |
| 4.5 | FAQ support | "Как получить справку?" | Support | ✅ | «Мои справки» в ЛК, бумажная копия за отдельную плату — из support KB |
| 4.6 | Нет ответа в KB | Вопрос вне темы → guardrails | Все | ✅ | «Специализируюсь на вопросах обучения в EdPalm» — RAG не вызывается |
| 4.7 | Namespace изоляция | Seller не видит support KB и наоборот | Все | ✅ | Support: «не нашла информации о тарифах». Seller: без деталей из support KB |
| 4.8 | Tool status UI | При поиске — "Ищу в базе знаний..." | Все | ✅ | SSE event tool_call + label. Фронтенд: пульсирующий индикатор |

---

## 5. SELLER — СЦЕНАРИИ

| # | Фича | Как тестировать | Роль | Статус | Баг / Заметка |
|---|---|---|---|---|---|
| 5.1 | Квалификация нового лида | "Хочу записать ребенка" → вопросы: класс, тариф | Seller | ⬜ | |
| 5.2 | Презентация продукта | После квалификации → описание тарифа + цена | Seller | ⬜ | |
| 5.3 | Обработка возражений | "Дорого" / "Я подумаю" — работа по скриптам | Seller | ⬜ | |
| 5.4 | Создание лида amoCRM | После сбора данных → сделка в CRM | Seller | ⬜ | |
| 5.5 | Генерация платежной ссылки | "Хочу оплатить" → DMS API → ссылка | Seller | ⬜ | |
| 5.6 | Payment Card UI | Карточка с суммой, продуктом, кнопкой | Seller | ⬜ | |
| 5.7 | Эскалация к менеджеру | "Позовите менеджера" → Telegram уведомление | Seller | ⬜ | |
| 5.8 | Escalation Banner UI | Баннер: "Менеджер свяжется" | Seller | ⬜ | |
| 5.9 | Upsell | После основной продажи → доп. продукты | Seller | ⬜ | |
| 5.10 | Follow-up (24ч) | Автосообщение через 24ч если не оплатил | Seller | ⬜ | |

---

## 6. SUPPORT — СЦЕНАРИИ

| # | Фича | Как тестировать | Роль | Статус | Баг / Заметка |
|---|---|---|---|---|---|
| 6.1 | Переключение роли | Открыть ссылку Support → другой промпт/приветствие | Support | ⬜ | |
| 6.2 | Профиль клиента (DMS) | Агент показывает ФИО, тариф, класс | Support | ⬜ | |
| 6.3 | FAQ ответы | "Как получить справку?" — ответ из KB | Support | ⬜ | |
| 6.4 | Создание тикета | Проблема → сделка в Service pipeline | Support | ⬜ | |
| 6.5 | Эскалация support | Сложный вопрос → менеджеру в Telegram | Support | ⬜ | |

---

## 7. TEACHER — СЦЕНАРИИ

| # | Фича | Как тестировать | Роль | Статус | Баг / Заметка |
|---|---|---|---|---|---|
| 7.1 | Вопрос по предмету | "Объясни теорему Пифагора" | Teacher | ⬜ | |
| 7.2 | Адаптация под класс | Ответ соответствует уровню ученика | Teacher | ⬜ | |
| 7.3 | Профиль ученика | Агент знает ФИО, класс, аттестации | Teacher | ⬜ | |

---

## 8. ОНБОРДИНГ

| # | Фича | Как тестировать | Роль | Статус | Баг / Заметка |
|---|---|---|---|---|---|
| 8.1 | Определение типа клиента | "Я действующий клиент" / "Хочу записаться" | Все | ⬜ | |
| 8.2 | Верификация по телефону | Ввести телефон → DMS проверяет | Все | ⬜ | |
| 8.3 | Профиль найден | Показывает ФИО + подтверждение | Все | ⬜ | |
| 8.4 | Профиль не найден | Предлагает создать / уточнить данные | Все | ⬜ | |
| 8.5 | OnboardingForm UI | Форма: ФИО, класс, телефон | Все | ⬜ | |

---

## 9. amoCRM ИНТЕГРАЦИЯ

| # | Фича | Как тестировать | Роль | Статус | Баг / Заметка |
|---|---|---|---|---|---|
| 9.1 | Поиск контакта | По телефону / Telegram ID | Все | ⬜ | |
| 9.2 | Создание контакта | Новый лид → контакт в amoCRM | Seller | ⬜ | |
| 9.3 | Сделка в Sales pipeline | Лид → проверить https://azamatrasuli.amocrm.ru/leads/pipeline/10689842 | Seller | ⬜ | |
| 9.4 | Тикет в Service pipeline | Проблема → проверить https://azamatrasuli.amocrm.ru/leads/pipeline/10689990 | Support | ⬜ | |
| 9.5 | ImBox sync | Сообщения дублируются в amoCRM чат | Seller/Support | ⬜ | |
| 9.6 | OAuth refresh | Токен обновляется при 401 | Все | ⬜ | |

---

## 10. DMS ИНТЕГРАЦИЯ

| # | Фича | Как тестировать | Роль | Статус | Баг / Заметка |
|---|---|---|---|---|---|
| 10.1 | Поиск по телефону | Телефон → контакт DMS | Все | ⬜ | |
| 10.2 | Данные контакта | ФИО, email, телефон из DMS | Support | ⬜ | |
| 10.3 | Профиль ученика | Contact → students с тарифом, классом | Support | ⬜ | |
| 10.4 | Продукты | Список продуктов DMS | Seller | ⬜ | |
| 10.5 | Создание заказа | Заказ → payment link | Seller | ⬜ | |
| 10.6 | SSL fallback | `verify=False` не ломает запросы | Все | ⬜ | |

---

## 11. ПАМЯТЬ И КОНТЕКСТ

| # | Фича | Как тестировать | Роль | Статус | Баг / Заметка |
|---|---|---|---|---|---|
| 11.1 | Внутри диалога | Назвать имя → через 5 сообщений помнит | Все | ⬜ | |
| 11.2 | Кросс-ролевая память | Назвать имя в seller → support помнит | Все | ⬜ | |
| 11.3 | Summary | Длинный диалог → создается краткое изложение | Все | ⬜ | |

---

## 12. DASHBOARD (Аналитика)

| # | Фича | Как тестировать | Роль | Статус | Баг / Заметка |
|---|---|---|---|---|---|
| 12.1 | Метрики (карточки) | Диалоги, конверсия, GMV, среднее время | Seller | ⬜ | |
| 12.2 | График диалогов | Line chart по дням | Seller | ⬜ | |
| 12.3 | График GMV | Bar chart по периодам | Seller | ⬜ | |
| 12.4 | Pie chart каналов | Распределение по каналам | Seller | ⬜ | |
| 12.5 | Таблица эскалаций | Причина + количество | Seller | ⬜ | |
| 12.6 | Неотвеченные вопросы | Список RAG misses | Seller | ⬜ | |
| 12.7 | Фильтр по дате | Выбор периода → данные обновляются | Seller | ⬜ | |
| 12.8 | Фильтр по роли | Seller / Support / All | Все | ⬜ | |
| 12.9 | API key auth | Открыть https://edplam-eurika.vercel.app/#/dashboard (без key) → 403 | Все | ⬜ | |

---

## 13. UI / UX

| # | Фича | Как тестировать | Роль | Статус | Баг / Заметка |
|---|---|---|---|---|---|
| 13.1 | Dark mode | Telegram dark theme → UI адаптируется | Все | ⬜ | |
| 13.2 | Mobile responsive | Открыть на телефоне | Все | ⬜ | |
| 13.3 | Telegram theme sync | Цвета из Telegram Mini App | Все | ⬜ | |
| 13.4 | Loading states | Индикатор загрузки при ожидании | Все | ⬜ | |
| 13.5 | Error handling | Ошибка сети → понятное сообщение | Все | ⬜ | |

---

## Лог багов

| # теста | Описание бага | Приоритет | Статус фикса | Дата |
|---|---|---|---|---|
| 4.4 | Seller не вызывал search_knowledge_base на «Как начать учиться?». Причина: «зачисление/запись» не было в триггерах. Фикс: de33433 | Medium | ✅ Исправлено и проверено | 2026-03-20 |

---

## Как пользоваться

1. Тестируй по порядку, меняй ⬜ на ✅ / ❌ / ⚠️
2. Если баг — пиши описание в колонку **Баг / Заметка** и дублируй в **Лог багов**
3. Отправляй мне — я фиксю и обновляю статус
4. **Токены истекли?** Попроси Claude перегенерировать

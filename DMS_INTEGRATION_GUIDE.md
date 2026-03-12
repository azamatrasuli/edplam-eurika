# DMS Integration Guide — EdPalm

> DMS API: `https://proxy.hss.center`
> Формат: REST JSON (grpc-gateway поверх gRPC)
> Postman: `/edpalm/dms-api.postman_collection.json`

---

## 1. Аутентификация

```
POST /v1/api/auth
{ "username": "...", "password": "..." }

→ { "accessToken": "ey...", "refreshToken": "..." }
```

Access token — 10 минут. Refresh — 30 дней (HttpOnly cookie `r_token`).

Все запросы: `Authorization: Bearer <accessToken>`

Обновление: `GET /v1/api/auth/refresh` (cookie автоматически).

**Паттерн для сервиса:**
```
При старте → POST /auth → сохранить token + exp
Перед запросом → if exp < now: GET /auth/refresh
Если 401 → повторно POST /auth
```

**TODO:** Попросить DMS-команду создать сервисные аккаунты (`eureka-agent`, `portal-service`). Пока используем `r.azamat@hss.center`.

---

## 2. Справочник эндпоинтов

### Чтение (все роли)

| Эндпоинт | Метод | Что возвращает |
|----------|-------|----------------|
| `/v1/api/contacts/search?q={phone}&limit=5` | GET | Контакт по телефону/ФИО/email |
| `/v1/api/contact/{uuid}` | GET | Контакт по UUID |
| `/v1/api/student?student_id={id}` | GET | Карточка ученика: продукты, представители, регформа, Moodle ID |
| `/v1/api/student/products` | POST `{student_id}` | Продукты ученика (lifecycle_state: CURRENT/PLANNED/HISTORICAL) |
| `/v1/api/student/moodle_info?student_id={id}` | GET | Данные из Moodle |
| `/v1/api/products?for_sales=true` | GET | Каталог продуктов (фильтры: group, study_years, type) |
| `/v1/api/promo/{code}` | GET | Проверка промо-кода |
| `/v1/api/orders/{uuid}` | GET | Заказ по UUID (поле `status`: 0=черновик, 1=ожидает, 2=оплачен, 3=исполнен) |
| `/v1/api/orders` | GET | Список заказов |
| `/v1/api/payments/unpaid-orders` | GET | Неоплаченные заказы |
| `/v1/api/payments/bank-statement?from_date=&to_date=` | GET | Банковская выписка |
| `/v1/api/schools` | GET | Список школ |
| `/v1/api/students/{id}/schools/enrollments` | GET | Зачисления ученика |
| `/v1/draft/grades` | GET | Классы 1-11 (публичный, без токена) |
| `/v1/draft/product_groups` | GET | Группы продуктов (публичный) |
| `/v1/draft/study_years` | GET | Учебные годы (публичный) |
| `/v1/api/analytics/student-visits` | GET | Аналитика заходов |

### Запись (продавец, портал)

| Эндпоинт | Метод | Что делает |
|----------|-------|------------|
| `/v1/api/orders` | POST `{contact_uuid, positions[{product_id, amount, count}]}` | Создать заказ |
| `/v1/api/payment/link` | POST `{id: order_uuid, pay_type: 0/1/2, position_promos: {}}` | Платёжная ссылка (0=СБП, 1=Карта, 2=Счёт) |
| `/v1/api/promo/check` | POST `{code, order_uuid}` | Расчёт скидки по позициям |
| `/v1/api/orders/{uuid}/status` | POST `{status}` | Обновить статус заказа |
| `/v1/api/demo/access` | POST `{student_id, product_id}` | Выдать демо-доступ |

---

## 3. Привязка к спринтам Эврики

### Продавец Sprint 4 (06.04 – 13.04) — Сценарии + follow-up

**Что нужно от DMS:**

| Сценарий | Шаг | DMS API | Файл в Эврике |
|----------|-----|---------|----------------|
| А (новый клиент) | Подбор продукта | `GET /v1/api/products?for_sales=true` | `dms.py` → `get_products_catalog()` |
| А | Проверка промо | `GET /v1/api/promo/{code}` | `dms.py` → `check_promo()` |
| А | Создание заказа | `POST /v1/api/orders` | `dms.py` → `create_order()` |
| А | Платёжная ссылка | `POST /v1/api/payment/link` | `dms.py` → `get_payment_link()` |
| А | Follow-up (24ч/48ч/7д) | `GET /v1/api/orders/{uuid}` | `dms.py` → `get_order_status()` |
| Б (пролонгация) | Профиль + текущий продукт | `GET /v1/api/student` + `POST /v1/api/student/products` | `dms.py` → `get_student_info()`, `get_student_products()` |
| Б | Подбор на след. год | `GET /v1/api/products?group=X&study_years=2027` | `dms.py` → `get_products_catalog()` |
| Б | Заказ + оплата | то же что А | — |
| В (кросс-сейл) | Каталог доп. продуктов | `GET /v1/api/products?for_sales=true` | `dms.py` → `get_products_catalog()` |

**Что дописать в `dms.py`:**
```
get_student_info(student_id)        → GET /v1/api/student
get_student_products(student_id)    → POST /v1/api/student/products
get_products_catalog(**filters)     → GET /v1/api/products
check_promo(code)                   → GET /v1/api/promo/{code}
create_order(contact_uuid, items)   → POST /v1/api/orders
get_payment_link(order_uuid, type)  → POST /v1/api/payment/link
get_order_status(order_uuid)        → GET /v1/api/orders/{uuid}
```

**Что добавить в `tools.py`:**
```
get_products_catalog    → "Покажи продукты для 7 класса"
check_promo_code        → "Проверь код FAMILY10"
create_order            → "Оформи заказ"
get_payment_link        → "Отправь ссылку на оплату"
check_order_status      → "Оплатил ли клиент?"
```

**Что обновить в `prompt.py`:**
- Инструкция: при подборе продукта — вызывай `get_products_catalog`, не бери цены из RAG
- Инструкция: при оформлении — цепочка: create_order → get_payment_link → отправить ссылку
- Инструкция: follow-up — check_order_status, если status != 2 → напомнить

---

### Продавец Sprint 5 (13.04 – 20.04) — Дашборд + портал

**Что нужно от DMS:**

| Задача | DMS API |
|--------|---------|
| Встройка в портал (здание «Магазин») | Аутентификация через JWT портала, не через DMS напрямую. Портал сам знает user → DMS нужен для данных |
| Дашборд: GMV через агента | `GET /v1/api/orders` — фильтрация заказов созданных агентом (по метаданным) |

---

### Поддержка Sprint 1 (06.04 – 13.04) — Переключение ролей

**Нет зависимости от DMS.** Чисто бэкенд: `agent_role` в conversations, разные system prompts.

### Поддержка Sprint 2 (13.04 – 20.04) — База знаний КС

**Нет зависимости от DMS.** RAG с namespace `support`.

### Поддержка Sprint 3 (20.04 – 04.05) — Онбординг + DMS

**Что нужно от DMS:**

| Задача | DMS API | Файл в Эврике |
|--------|---------|----------------|
| Профиль клиента (тариф, класс, статус) | `GET /v1/api/student` + `POST /v1/api/student/products` | `dms.py` → переиспользуем из Sprint 4 продавца |
| Статус регформы | `GET /v1/api/student` → поле `student_regforms` | — |
| Зачисления | `GET /v1/api/students/{id}/schools/enrollments` | `dms.py` → `get_student_enrollments()` |
| Неоплаченные заказы | `GET /v1/api/payments/unpaid-orders` | `dms.py` → `get_unpaid_orders()` |

**Что добавить в `tools.py`:**
```
get_client_profile      → "Что за клиент, какой тариф?"
get_document_status     → "Заполнена ли регформа?"
get_unpaid_orders       → "Есть задолженности?"
```

### Поддержка Sprint 4 (04.05 – 18.05) — Уведомления + алерты

**Что нужно от DMS:**

| Задача | DMS API |
|--------|---------|
| Напоминание об оплате | `GET /v1/api/payments/unpaid-orders` → Telegram push |
| Проверка активности | `GET /v1/api/student` → `last_access` |
| Данные для алерта менеджеру | `GET /v1/api/student` + `POST /v1/api/student/products` |

Потребуется **cron/scheduler** на стороне Эврики — периодический опрос DMS.

### Поддержка Sprint 5 (18.05 – 01.06) — Чек-листы + ГИА

**Зависимость от DMS минимальная.** Чек-листы хранятся на стороне Эврики (Supabase). DMS нужен только для определения на каком шаге клиент (есть оплата? есть регформа? есть зачисление?).

---

### Учитель Sprint 5 (Апрель – 12.05) — Проактивность

**Что нужно от DMS:**

| Задача | DMS API |
|--------|---------|
| Последний вход ученика | `GET /v1/api/student` → `last_access` |
| Данные Moodle | `GET /v1/api/student/moodle_info` |

Учитель Sprint 6+ — генерация материалов — не зависит от DMS.

---

## 4. Привязка к спринтам Портала

| Задача портала | DMS API | Когда |
|----------------|---------|-------|
| ЛК ученика: профиль | `GET /v1/api/student?student_id=X` | При создании ЛК |
| ЛК ученика: продукты | `POST /v1/api/student/products` | При создании ЛК |
| ЛК: статус регформы | `GET /v1/api/student` → `student_regforms` | При создании ЛК |
| Каталог продуктов | `GET /v1/api/products?for_sales=true` | При добавлении магазина |
| Покупка | `POST /v1/api/orders` → `POST /v1/api/payment/link` | При добавлении магазина |
| Справочники (классы, школы) | `GET /v1/draft/grades`, `GET /v1/api/schools` | При интеграции |
| Аналитика | `GET /v1/api/analytics/student-visits` | Админка портала |
| Демо-доступ | `POST /v1/api/demo/access` | Маркетинговые фичи |

---

## 5. Реализация DMS-клиента в Эврике

Файл: `eurika/backend/app/integrations/dms.py`

**Текущее состояние:**
- `DMSServiceBase` — абстрактный интерфейс
- `MockDMSService` — 3 тестовых клиента (работает)
- `RealDMSService` — `search_contact_by_phone()` реализован, `get_student_info()` заглушка
- Фабрика `get_dms_service()` — если есть credentials → Real, иначе → Mock

**Нужно добавить в `RealDMSService`:**

| Метод | Спринт | API |
|-------|--------|-----|
| `get_student_info(student_id)` | Seller S4 | `GET /v1/api/student` |
| `get_student_products(student_id)` | Seller S4 | `POST /v1/api/student/products` |
| `get_products_catalog(**filters)` | Seller S4 | `GET /v1/api/products` |
| `check_promo(code)` | Seller S4 | `GET /v1/api/promo/{code}` |
| `create_order(contact_uuid, positions)` | Seller S4 | `POST /v1/api/orders` |
| `get_payment_link(order_uuid, pay_type)` | Seller S4 | `POST /v1/api/payment/link` |
| `get_order_status(order_uuid)` | Seller S4 | `GET /v1/api/orders/{uuid}` |
| `get_student_enrollments(student_id)` | Support S3 | `GET /v1/api/students/{id}/schools/enrollments` |
| `get_unpaid_orders()` | Support S3 | `GET /v1/api/payments/unpaid-orders` |
| `get_student_moodle(student_id)` | Teacher S5 | `GET /v1/api/student/moodle_info` |

Все методы — обёртки над httpx. Никаких изменений в DMS.

---

## 6. Подводные камни

**Токен живёт 10 минут.** Реализовать auto-refresh в DMS-клиенте. Ловить 401 → рефреш → повтор.

**UUID vs ID.** Контакты и заказы адресуются по UUID (строка). Ученики и продукты — по INT ID. Не путать.

**Нормализация.** DMS сам нормализует телефоны (`+7 (999) 123-45-67` → `79991234567`) и email (Gmail: точки и плюс-теги убираются).

**Промо привязаны к группам продуктов.** Промо FAMILY10 может работать только для группы "Экстернат Базовый". Всегда проверять через `GET /v1/api/promo/{code}` — там есть `product_group[]`.

**Платёжная ссылка перезаписывается.** Каждый `POST /v1/api/payment/link` создаёт новую и затирает предыдущую. Не вызывать повторно без причины.

**Soft delete.** Удалённые записи имеют `delete_at != null`. Большинство GET-эндпоинтов уже фильтруют, но при обработке ответов стоит проверять.

**status заказа.** 0 = черновик, 1 = ожидает оплаты, 2 = оплачен, 3 = исполнен. Точный маппинг уточнить у DMS-команды — других значений может быть больше.

---

## 7. Запросы к DMS-команде

| Что | Зачем | Приоритет | К спринту |
|-----|-------|-----------|-----------|
| Сервисный аккаунт `eureka-agent` | Продакшн-интеграция агента | Критичный | Seller S4 |
| Сервисный аккаунт `portal-service` | Продакшн-интеграция портала | Критичный | Portal ЛК |
| Список всех значений order.status | Корректная обработка в коде | Высокий | Seller S4 |
| Webhook при смене статуса оплаты | Реактивный follow-up вместо поллинга | Средний | Support S4 |
| Фильтр заказов по contact_uuid | История заказов конкретного клиента | Средний | Support S3 |
| Rate limits | Планирование нагрузки при уведомлениях | Средний | Support S4 |

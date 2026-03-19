# Исследование: Best Practices для мультиролевого AI-агента (Sales + Support + Teacher)

> Дата: 2026-03-12
> Проект: EdPalm / Эврика
> Цель: практические, реализуемые паттерны для улучшения Эврики

---

## 1. Dynamic Intent Switching (Переключение намерений в середине разговора)

### Проблема
Пользователь начинает спрашивать про цены (sales), потом переключается на "а как зайти в ЛК?" (support), потом "а что задали по математике?" (teacher). Агент должен плавно следовать за пользователем, не теряя контекст.

### Что делают лидеры

**Intercom Fin** использует трёхуровневую архитектуру:
1. **Query refinement** — входящее сообщение проверяется: ясен ли интент? Нужна ли переформулировка?
2. **Condition matching** — проверка на предконфигурированные триггеры (жалоба, запрос возврата, etc.)
3. **Confidence threshold** — если уверенность ниже порога, агент просит уточнить вместо галлюцинации

**LangChain Router Pattern** — классифицирующий LLM на входе направляет запрос к специализированному агенту. Каждый агент имеет свой системный промпт и набор инструментов.

### Рекомендация для Эврики: Intent Router

```
Архитектура: Supervisor → Router → Specialized Handler

Каждое сообщение пользователя проходит через:
1. Intent Classification (быстрый LLM-вызов или часть системного промпта)
2. Role Selection (sales / support / teacher)
3. Context Carry-Over (ключевые факты из предыдущей роли передаются)
```

**Практическая реализация (в prompt.py):**

```python
# В системном промпте добавить секцию:
"""
## Определение роли

Перед каждым ответом определи намерение пользователя:
- SALES: вопросы о ценах, программах, записи, оплате, сравнение с другими школами
- SUPPORT: проблемы с доступом, ЛК, техподдержка, документы, справки, процессы
- TEACHER: домашка, уроки, оценки, аттестации, учебные материалы

Если пользователь сменил тему:
1. Кратко подтверди ("Хорошо, переключаемся на вопрос по учёбе.")
2. Переключи стиль и контекст
3. НЕ теряй информацию из предыдущей темы — она может понадобиться

Если намерение неясно — задай один уточняющий вопрос.
"""
```

**Ключевой паттерн — "Acknowledge & Pivot":**
- Плохо: молча переключиться (пользователь потеряется)
- Плохо: "Это не мой вопрос" (отталкивает)
- Хорошо: "Понял, давайте разберёмся с доступом к ЛК. А по оплате — я запомнил ваш вопрос, вернёмся к нему."

### Обработка мульти-интентов в одном сообщении

Пример: "Сколько стоит 5 класс и почему у ребёнка не открывается урок?"

Стратегия — **Sequential Processing с Acknowledgment:**
```
1. Распознать оба интента
2. Ответить на оба последовательно:
   "По стоимости: 5 класс — от X руб/мес. [детали]

   По уроку: давайте разберёмся. Какой предмет не открывается?"
3. Продолжить диалог по незакрытому вопросу
```

---

## 2. Progressive Qualification (Квалификация лида через разговор)

### Проблема
Нужно собрать: имя, класс ребёнка, город, интересующую программу, бюджет, сроки — но не превращать чат в допрос.

### Что делают лидеры

**Drift** — rule-based бот, квалифицирует по предзаданным правилам, но ощущается механически.

**Exceed.ai** — мультиканальный AI (чат, email, SMS), автоматически квалифицирует и букает встречи.

**Qualified** — нативная интеграция с Salesforce, ABM-фокус, определяет high-intent визиторов.

**Общий вывод:** rule-based системы дают предсказуемость, но LLM-native подход даёт естественность.

### Рекомендация для Эврики: "Value-First Qualification"

**Принцип:** Каждый вопрос должен давать ценность пользователю, а не только собирать данные.

```
Порядок квалификации (естественный диалог):

1. КОНТЕКСТ (понять ситуацию — не спрашивая "кто вы?")
   "Расскажите, что вас привело к семейному образованию?"
   → Из ответа извлекаем: мотивацию, класс (часто упомянут), текущую ситуацию

2. РЕБЁНОК (через заботу, не анкету)
   "В каком классе учится ваш ребёнок? Хочу подобрать подходящую программу."
   → Класс + неявно: возраст

3. ПРОГРАММА (через рекомендацию)
   "Для [класс] класса у нас есть [программы]. Вам ближе [краткое описание A] или [краткое описание B]?"
   → Программа + уровень вовлечённости

4. ГЕОГРАФИЯ (через релевантность)
   "Вы в России или за границей? От этого зависит формат аттестации."
   → Страна/город

5. СРОКИ (через потребность)
   "Когда планируете начать? Спрашиваю, потому что набор на [период] уже идёт."
   → Urgency

6. БЮДЖЕТ (только если уместно)
   "Стоимость зависит от программы. Рассказать про варианты?"
   → Не спрашиваем бюджет напрямую. Показываем варианты.
```

**Антипаттерны:**
- "Как вас зовут?" — первым вопросом (слишком рано)
- Три вопроса подряд без ценности
- "Введите email для связи" (это форма, не разговор)
- Спрашивать бюджет напрямую в первых сообщениях

**Паттерн "Conversational Capture":**
Вместо одного вопроса за раз — позволять пользователю давать развёрнутый ответ и извлекать из него несколько фактов:

```
Пользователь: "Мы из Дубая, сын в 7 классе, ищем экстернат потому что
              много путешествуем"

Извлечение:
- город: Дубай (ОАЭ)
- класс: 7
- программа: экстернат
- мотивация: путешествия, гибкость
- кол-во детей: 1 (сын)
```

### Сохранение квалификационных данных

```python
# В tools.py — tool для записи квалификационных данных:
async def save_qualification_data(
    contact_id: str,
    field: str,  # grade, city, program, motivation, timeline
    value: str,
    confidence: float  # 0.0-1.0 — насколько уверены в извлечённых данных
):
    """Сохраняет квалификационные данные в agent_user_profiles"""
```

---

## 3. Tone & Personality Adaptation (Адаптация тона)

### Проблема
Родитель в панике ("ребёнок не допущен к аттестации!") требует иного тона, чем мама, спокойно выбирающая школу.

### Что делают лидеры

**Hume AI** — целая платформа для распознавания эмоций в голосе и тексте.

**EvoEmo** — система динамической адаптации эмоционального тона AI во время разговора.

**Intercom Fin** — использует специализированные sub-модели для определения sentiment.

**Факт:** Исследования показывают +20% к удовлетворённости когда chatbot реагирует с эмоциональным интеллектом (9.13 vs 8.41 по шкале удовлетворённости).

### Рекомендация для Эврики: Tone Matrix

**Три оси адаптации:**

```
1. ЭМОЦИЯ пользователя:
   - Frustrated/Angry → Спокойный, эмпатичный, короткие предложения
   - Confused → Пошаговый, с примерами
   - Curious/Exploring → Информативный, с деталями
   - Excited → Энергичный, поддерживающий
   - Anxious/Worried → Уверенный, успокаивающий

2. ТИП пользователя:
   - Новый лид (parent) → Тёплый, продающий, объясняющий
   - Текущий клиент (parent) → Деловой, решающий, быстрый
   - Ученик → Дружелюбный, простой язык, мотивирующий

3. РОЛЬ агента:
   - Sales → Убеждающий, выделяющий преимущества
   - Support → Решающий, чёткий, с тайм-фреймами
   - Teacher → Терпеливый, поощряющий, адаптивный
```

**Реализация в системном промпте:**

```
## Адаптация тона

Определи эмоциональное состояние пользователя по его сообщению:
- Негативные маркеры: "!!!", "почему?!", "уже N раз", "не работает", caps lock
- Позитивные маркеры: "спасибо", "здорово", "интересно"
- Тревожные маркеры: "боюсь что", "не уверена", "правильно ли"

Правила:
- При ФРУСТРАЦИИ: сначала признай проблему ("Понимаю, это неприятная ситуация"),
  потом решение. Никогда не начинай с "К сожалению..."
- При ТРЕВОГЕ: дай уверенность ("Это частая ситуация, и мы с ней справляемся")
- При ЛЮБОПЫТСТВЕ: дай чуть больше деталей, чем спрашивают
- С УЧЕНИКОМ: используй "ты", короткие предложения, поощряй
- С РОДИТЕЛЕМ: используй "вы", будь профессионален, подчёркивай заботу о ребёнке
```

**Паттерн "Mirror & Lead":**
1. **Mirror** — отрази состояние пользователя (покажи, что понимаешь)
2. **Lead** — веди к решению нужным тоном

Пример:
```
Родитель: "Уже третий раз пишу! У ребёнка не открывается урок,
          аттестация через неделю!!!"

Плохо: "Здравствуйте! Давайте разберёмся. Какой у вас логин?"

Хорошо: "Вижу, ситуация срочная — аттестация скоро, и урок не открывается.
         Давайте решим это прямо сейчас. Какой предмет и класс?"
```

---

## 4. Onboarding UX (Первое взаимодействие)

### Проблема
Первое сообщение определяет, будет ли пользователь общаться дальше. Формальное "Здравствуйте, я AI-помощник, чем могу помочь?" — теряет 40%+ пользователей.

### Что делают лидеры

**ChatGPT** — минималистичный онбординг: просто input box и примеры запросов.

**Replika** — personality-driven: сразу создаёт ощущение личного общения.

**Character.ai** — даёт выбрать персонажа, задаёт тон с первого сообщения.

**NN/Group (Nielsen Norman)** — исследование показывает, что новым пользователям AI нужна поддержка: они не знают, что спросить.

**Статистика:** Каждое дополнительное поле в signup форме снижает конверсию на ~10%.

### Рекомендация для Эврики: Context-Aware Welcome

**Три сценария первого контакта:**

```
Сценарий 1: ПОРТАЛ (авторизованный пользователь)
Мы знаем: имя, класс, статус (ученик/родитель)

"Привет, [Имя]! Я Эврика — помощник EdPalm.
Могу помочь с учёбой, ответить на вопросы по школе или разобраться
с любой ситуацией. Что вас интересует?

[Кнопка: Вопрос по учёбе]
[Кнопка: Проблема с доступом]
[Кнопка: Узнать о программах]"
```

```
Сценарий 2: TELEGRAM (новый пользователь)
Мы знаем: telegram имя

"Привет! Я Эврика, помощник онлайн-школы EdPalm.

Мы учим детей 1-11 классов — с аттестацией, поддержкой и заботой.

Расскажите, что привело вас к нам? Например:
— Ищу школу для ребёнка
— У меня вопрос по обучению
— Нужна помощь с ЛК"
```

```
Сценарий 3: ВНЕШНЯЯ ССЫЛКА (холодный лид)
Мы не знаем ничего

"Привет! Я Эврика из EdPalm — онлайн-школы семейного образования.

Если вы здесь впервые — могу рассказать, как устроено обучение и
подобрать программу для вашего ребёнка.

С чего начнём?"
```

**Принципы:**
1. **Представься коротко** — 1 предложение, не абзац
2. **Дай контекст** — что ты умеешь (но не список из 20 пунктов)
3. **Предложи Quick Actions** — кнопки/подсказки снижают барьер первого сообщения
4. **Не спрашивай данные сразу** — начни с ценности
5. **Персонализируй** — если знаешь имя, используй его

**Антипаттерны:**
- "Пожалуйста, введите ваше имя и телефон"
- "Я могу: 1) ... 2) ... 3) ... 4) ... 5) ... 6) ... 7) ..." (перегрузка)
- Формальное канцелярское приветствие
- Отсутствие подсказок (пустой input = ступор)

---

## 5. Conversation Memory & Continuity (Память и персонализация)

### Проблема
Пользователь вчера спрашивал про 5 класс, обсуждал цены, назвал имя ребёнка — а сегодня агент начинает с нуля.

### Что делают лидеры

**ChatGPT Memory** (reverse-engineered):
- Четыре слоя: session metadata, explicit facts, chat summaries, sliding window
- Факты извлекаются когда пользователь явно что-то сообщает о себе
- Все сохранённые факты включаются в каждый запрос
- НЕ использует vector search по истории — просто плоский список фактов

**OpenAI Agents SDK (Cookbook):**
- State object = локальное хранилище памяти
- Memory distillation: извлечение фактов во время разговора через tool calls
- Стабильные предпочтения → structured profile fields
- Волатильные данные → notes с recency weighting

**Mem0 (arxiv paper):**
- Три типа памяти: episodic (события), semantic (факты), procedural (навыки)
- Compression для оптимизации context window

### Рекомендация для Эврики: Three-Layer Memory

```
Слой 1: USER PROFILE (Supabase: agent_user_profiles)
Постоянные факты. Обновляются редко.

Поля:
- display_name: "Анна"
- children: [{name: "Миша", grade: 5, program: "экстернат"}]
- city: "Дубай"
- country: "ОАЭ"
- role: "parent"
- language: "ru"
- enrollment_status: "lead" | "trial" | "active" | "churned"
- preferred_contact: "telegram"
- notes: "путешествует семьёй, нужен гибкий график"
```

```
Слой 2: CONVERSATION SUMMARY (Supabase: conversations)
Краткое содержание предыдущих разговоров. Генерируется по окончании сессии.

Поля:
- conversation_id
- summary: "Обсудили программу экстерната для 5 класса.
           Анна сравнивала с InternetUrok. Осталась заинтересована,
           попросила прислать расписание."
- key_topics: ["pricing", "externat", "5_grade", "schedule"]
- sentiment: "positive"
- open_questions: ["расписание не отправлено"]
- role_used: "sales"
```

```
Слой 3: ACTIVE CONTEXT (в промпте, при начале сессии)
Последние N сообщений текущего разговора (sliding window).
+ Профиль пользователя
+ Summary последних 3 разговоров
```

### Что запоминать vs что забывать

```
ЗАПОМИНАТЬ (→ User Profile):
- Имя пользователя и детей
- Класс ребёнка
- Город/страна
- Выбранная или обсуждавшаяся программа
- Ключевые мотивации ("много путешествуем", "не нравится обычная школа")
- Статус клиента (лид, пробный, активный)
- Открытые вопросы/проблемы

ЗАПОМИНАТЬ (→ Conversation Summary):
- О чём говорили
- Какие решения приняты
- Что обещали (follow-up)
- Общий sentiment

НЕ ЗАПОМИНАТЬ / ЗАБЫВАТЬ:
- Точные формулировки сообщений (хранить summary, не verbatim)
- Временные технические детали ("ошибка 504 на странице X" — после решения)
- Промежуточные рассуждения агента
- Эмоциональные всплески (не хранить "пользователь ругался")
```

### Реализация Memory Extraction

```python
# В конце каждой сессии (или по таймауту 30 мин):

async def extract_session_memory(conversation_id: str, messages: list):
    """
    Использует LLM для извлечения фактов из разговора.
    Обновляет user_profile и создаёт conversation_summary.
    """
    extraction_prompt = """
    Проанализируй этот разговор и извлеки:
    1. Новые факты о пользователе (имя, дети, класс, город, программа)
    2. Краткое summary разговора (2-3 предложения)
    3. Ключевые темы (tags)
    4. Открытые вопросы (что осталось нерешённым)
    5. Общий sentiment (positive/neutral/negative)

    Верни в JSON формате.
    """
```

### Использование памяти в промпте

```python
# При начале новой сессии:

system_prompt = f"""
## Контекст пользователя
Имя: {profile.display_name}
Дети: {format_children(profile.children)}
Город: {profile.city}
Статус: {profile.enrollment_status}
Заметки: {profile.notes}

## Последние разговоры
{format_recent_summaries(last_3_conversations)}

## Открытые вопросы
{format_open_questions(profile)}

Используй этот контекст для персонализации. НЕ спрашивай то, что уже знаешь.
Если есть открытые вопросы — упомяни их в начале разговора.
"""
```

---

## Сводная таблица: Что внедрить и когда

| Паттерн | Сложность | Приоритет | Спринт |
|---|---|---|---|
| Intent classification в промпте | Низкая | Высокий | Seller S4 |
| "Acknowledge & Pivot" при смене темы | Низкая | Высокий | Seller S4 |
| Quick Actions (кнопки) в welcome | Низкая | Высокий | Seller S4 |
| Context-aware welcome message | Низкая | Высокий | Seller S4 |
| Value-first qualification order | Средняя | Высокий | Seller S4 |
| Tone adaptation в промпте | Низкая | Средний | Seller S4 |
| "Mirror & Lead" при эмоциях | Низкая | Средний | Support S2 |
| User Profile extraction | Средняя | Высокий | Seller S4 |
| Conversation Summary generation | Средняя | Средний | Seller S5 |
| Memory injection в промпт | Средняя | Средний | Seller S5 |
| Multi-intent sequential processing | Средняя | Низкий | Support S3 |
| Structured qualification data save | Средняя | Средний | Seller S4 |

---

## Источники

### Dynamic Intent Switching
- [Intercom Fin AI Agent Explained](https://www.intercom.com/help/en/articles/7120684-fin-ai-agent-explained)
- [The Fin AI Engine](https://www.intercom.com/help/en/articles/9929230-the-fin-ai-engine)
- [Intent-First Architecture — VentureBeat](https://venturebeat.com/orchestration/conversational-ai-doesnt-understand-users-intent-first-architecture-does/)
- [LangChain Router Pattern](https://docs.langchain.com/oss/python/langchain/multi-agent/router)
- [Choosing the Right Multi-Agent Architecture — LangChain](https://blog.langchain.com/choosing-the-right-multi-agent-architecture/)
- [Handling Multiple Intent Conversations — ML6](https://www.ml6.eu/en/blog/handling-multiple-intent-conversations-in-customer-support-chatbots)
- [Intent Recognition and Auto-Routing in Multi-Agent Systems](https://gist.github.com/mkbctrl/a35764e99fe0c8e8c00b2358f55cd7fa)
- [LLM Intent Classification for Chatbots — Vellum](https://www.vellum.ai/blog/how-to-build-intent-detection-for-your-chatbot)
- [Chatbot Intent Recognition — AIMultiple](https://research.aimultiple.com/chatbot-intent/)
- [Multi-Agent Supervisor Architecture — Databricks](https://www.databricks.com/blog/multi-agent-supervisor-architecture-orchestrating-enterprise-ai-scale)

### Progressive Qualification
- [Smarter Lead Qualification with AI — Reply.io](https://reply.io/blog/lead-qualification-ai/)
- [Drift vs Qualified Comparison — Spara](https://www.spara.co/blog/drift-vs-qualified)
- [Qualified Advantage](https://www.qualified.com/advantage)
- [Automated Lead Qualification — Bland.ai](https://www.bland.ai/blogs/automated-lead-qualification)
- [Progressive Profiling — Typeform](https://www.typeform.com/blog/progressive-profiling-collect-better-data/)
- [Lead Generation Chatbots for Tutoring Centers](https://agentiveaiq.com/listicles/7-must-have-lead-generation-chatbots-for-tutoring-centers)
- [AI Chatbot for Education — LeadSquared](https://www.leadsquared.com/industries/education/chatbot-for-education/)

### Tone & Personality Adaptation
- [Emotionally Intelligent AI Voice Agents — SuperAGI](https://superagi.com/emotionally-intelligent-ai-voice-agents-how-emotional-ai-is-transforming-customer-support-and-sales-in-2025/)
- [Emotion Recognition in Conversational Agents — SmythOS](https://smythos.com/developers/agent-development/conversational-agents-and-emotion-recognition/)
- [Emotional AI — Talkk.ai](https://www.talkk.ai/emotional-ai-how-agents-detect-and-adapt-to-customer-sentiment/)
- [Emotion-Sensitive LLM Conversational AI — arxiv](https://arxiv.org/html/2502.08920v1)
- [Emotional Prompting in AI — PromptEngineering.org](https://promptengineering.org/emotional-prompting-in-ai-transforming-chatbots-with-empathy-and-intelligence/)
- [Hume AI — Emotion Toolkit](https://www.hume.ai/)

### Onboarding UX
- [AI Chatbot UX Best Practices 2026 — Groto](https://www.letsgroto.com/blog/ux-best-practices-for-ai-chatbots)
- [UX Onboarding Best Practices — UX Design Institute](https://www.uxdesigninstitute.com/blog/ux-onboarding-best-practices-guide/)
- [New Users Need Support with AI Tools — NN/Group](https://www.nngroup.com/articles/new-AI-users-onboarding/)
- [UX Best Practices for AI Chatbots — MindTheProduct](https://www.mindtheproduct.com/deep-dive-ux-best-practices-for-ai-chatbots/)
- [Chatbot Welcome Messages — FlowHunt](https://www.flowhunt.io/blog/30-chatbot-welcome-messages-to-make-a-great-first-impression/)
- [Chat UX: Onboarding to Re-Engagement — GetStream](https://getstream.io/blog/chat-ux/)

### Conversation Memory & Continuity
- [Context Engineering for Personalization — OpenAI Cookbook](https://cookbook.openai.com/examples/agents_sdk/context_personalization)
- [Session Memory Management — OpenAI Cookbook](https://cookbook.openai.com/examples/agents_sdk/session_memory)
- [Reverse Engineering ChatGPT Memory](https://manthanguptaa.in/posts/chatgpt_memory/)
- [Reverse Engineering ChatGPT Memory — Agentman](https://agentman.ai/blog/reverse-ngineering-latest-ChatGPT-memory-feature-and-building-your-own)
- [Ultimate Guide to AI Agent Memory — Cognigy](https://www.cognigy.com/product-updates/an-ultimate-guide-to-ai-agent-memory)
- [6 Best AI Agent Memory Frameworks — MLMastery](https://machinelearningmastery.com/the-6-best-ai-agent-memory-frameworks-you-should-try-in-2026/)
- [Agent Memory — Letta](https://www.letta.com/blog/agent-memory)
- [Mem0: Production-Ready AI Agents with Long-Term Memory — arxiv](https://arxiv.org/pdf/2504.19413)
- [From Models to Memory — ASAPP](https://www.asapp.com/blog/from-models-to-memory-the-next-big-leap-in-ai-agents-in-customer-experience)
- [AI Agents with Redis Memory](https://redis.io/blog/build-smarter-ai-agents-manage-short-term-and-long-term-memory-with-redis/)

### Education-Specific
- [SchoolAI](https://schoolai.com/)
- [AI Chatbots for Education — Juji](https://juji.io/education-chatbot/)
- [Conversational AI in Education — AppInventiv](https://appinventiv.com/blog/conversational-ai-in-education/)
- [AI Chatbots in Education — LearnWise](https://www.learnwise.ai/guides/ultimate-guide-to-ai-chatbots-in-education)
- [Chatbots for Students and Parents — Crimson Academy](https://www.crimsonglobalacademy.school/us/blog/ai-powered-chatbots-for-students-and-parents/)

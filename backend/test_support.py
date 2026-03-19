"""
Test runner for Support role (Эврика — роль Поддержка).
100 scenarios covering: registration, documents, attestation, platform, SO/ZO, escalation.
"""

import hashlib
import hmac
import json
import time
import sys
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field

import httpx

BASE_URL = "http://localhost:8009"
EXTERNAL_LINK_SECRET = "4bf5a53f556b3366255c4405ef57363dc2aa42d52b3db000"


def generate_external_token(lead_id: str = "test_support") -> str:
    expires_ts = str(int((datetime.now(timezone.utc) + timedelta(hours=48)).timestamp()))
    msg = f"{lead_id}:{expires_ts}".encode("utf-8")
    sig = hmac.new(EXTERNAL_LINK_SECRET.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return f"{lead_id}:{expires_ts}:{sig}"


@dataclass
class TestResult:
    scenario_id: int
    user_message: str
    response_text: str
    tools_called: list = field(default_factory=list)
    escalation: bool = False
    escalation_reason: str = ""
    errors: list = field(default_factory=list)
    passed: bool = True
    fail_reasons: list = field(default_factory=list)
    duration_s: float = 0.0


def start_conversation(token: str, retries: int = 3) -> str:
    for attempt in range(retries):
        try:
            resp = httpx.post(
                f"{BASE_URL}/api/v1/conversations/start",
                json={"auth": {"external_token": token}, "agent_role": "support", "force_new": True},
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()["conversation_id"]
        except (httpx.ReadTimeout, httpx.ConnectError, httpx.ReadError) as e:
            if attempt < retries - 1:
                print(f"    retry start ({attempt+1})...", flush=True)
                time.sleep(10)
            else:
                raise


def send_message(token: str, conversation_id: str, message: str) -> TestResult:
    result = TestResult(scenario_id=0, user_message=message, response_text="")
    start = time.time()
    try:
        with httpx.stream(
            "POST", f"{BASE_URL}/api/v1/chat/stream",
            json={"auth": {"external_token": token}, "conversation_id": conversation_id,
                  "message": message, "agent_role": "support"},
            timeout=120,
        ) as resp:
            resp.raise_for_status()
            buffer = ""
            event_type = ""
            for line in resp.iter_lines():
                if line.startswith("event: "):
                    event_type = line[7:]
                elif line.startswith("data: "):
                    try:
                        data = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue
                    if event_type == "token":
                        buffer += data.get("text", "")
                    elif event_type == "tool_call":
                        result.tools_called.append(data.get("name", ""))
                    elif event_type == "escalation":
                        result.escalation = True
                        result.escalation_reason = data.get("reason", "")
                    elif event_type == "done":
                        result.response_text = data.get("text", buffer)
    except Exception as e:
        result.errors.append(str(e))
    result.duration_s = round(time.time() - start, 1)
    if not result.response_text:
        result.response_text = buffer
    return result


def send_multi_turn(token: str, conversation_id: str, messages: list) -> list:
    results = []
    for msg in messages:
        r = send_message(token, conversation_id, msg)
        results.append(r)
        time.sleep(2)
    return results


def check_any(text: str, keywords: list) -> bool:
    t = text.lower()
    return any(k.lower() in t for k in keywords)


def validate(sid: int, r: TestResult, expect: dict) -> TestResult:
    r.scenario_id = sid
    if "tools" in expect:
        for tool in expect["tools"]:
            if tool not in r.tools_called:
                r.passed = False
                r.fail_reasons.append(f"Missing tool '{tool}', called: {r.tools_called}")
    if "keywords" in expect:
        for kw in expect["keywords"]:
            if kw.lower() not in r.response_text.lower():
                r.passed = False
                r.fail_reasons.append(f"Missing keyword: '{kw}'")
    if "any_keywords" in expect:
        if not check_any(r.response_text, expect["any_keywords"]):
            r.passed = False
            r.fail_reasons.append(f"None of: {expect['any_keywords']}")
    if "escalation" in expect:
        if expect["escalation"] and not r.escalation:
            r.passed = False
            r.fail_reasons.append("Expected escalation")
        elif not expect["escalation"] and r.escalation:
            r.passed = False
            r.fail_reasons.append("Unexpected escalation")
    if "no_keywords" in expect:
        for kw in expect["no_keywords"]:
            if kw.lower() in r.response_text.lower():
                r.passed = False
                r.fail_reasons.append(f"Forbidden: '{kw}'")
    if r.errors:
        r.passed = False
        r.fail_reasons.append(f"Errors: {r.errors}")
    if not r.response_text.strip():
        r.passed = False
        r.fail_reasons.append("Empty response")
    return r


# =============================================================================
# ALL 100 SCENARIOS
# =============================================================================

SCENARIOS = {
    # ---- Block A: Registration and enrollment (1-20) ----
    1: {"msg": "Как зарегистрировать ученика после оплаты?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["регистрационн", "форм", "ссылк"]}},
    2: {"msg": "Мне не пришла ссылка на регистрацию",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["спам", "куратор"]}},
    3: {"msg": "В форме регистрации ошибка, как исправить?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["куратор", "поддержк", "исправ"]}},
    4: {"msg": "Когда зачислят ребёнка? Мы на заочной форме",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["5", "10", "рабочих дн"]}},
    5: {"msg": "Когда зачислят? Семейная форма",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["3 рабочих", "3 дн", "три"]}},
    6: {"msg": "Можно ли изменить текст заявления?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["нет", "не подлежат", "школ"]}},
    7: {"msg": "Где посмотреть статус зачисления?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["МЭШ", "личн", "кабинет", "статус"]}},
    8: {"msg": "Ребёнок уже зачислен, но доступ к платформе не открылся",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["куратор", "панел", "регистрац", "поддержк"]}},
    9: {"msg": "Мы на заочной форме. Что значит 'зачисление в МЭШ'?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["МЭШ", "электронн", "заочн"]}},
    10: {"msg": "Документы проверяют, но зачисления нет уже 2 недели. Это нормально?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["5", "10", "рабочих", "дн"]}},
    11: {"msg": "Какие сроки от оплаты до доступа к платформе?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["регистрац", "форм", "сразу", "оплат"]}},
    12: {"msg": "Можно ли ускорить зачисление?",
        "expect": {"tools": ["search_knowledge_base"]}},
    13: {"msg": "Оплатили 2 недели назад, до сих пор не зачислены",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["понима", "помо", "уточн", "жаль"]}},
    14: {"msg": "Зачисление на заочную для московского ученика — нужна МЭШ?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["МЭШ", "заочн"]}},
    15: {"msg": "Зачисление на семейную для иностранца — есть ограничения?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["семейн", "индивидуальн", "консультант", "специалист"]}},
    16: {"msg": "Нужно ли личное дело для зачисления на заочную?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["да", "обязательно", "личное дело"]}},
    17: {"msg": "Нужно ли личное дело для семейной формы?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["зависит", "уточн", "семейн"]}},
    18: {"msg": "Можно ли зачислиться в середине года?",
        "expect": {"tools": ["search_knowledge_base"]}},
    19: {"msg": "Регистрация не работает, ошибка на сайте",
        "expect": {"any_keywords": ["обращен", "тикет", "специалист", "куратор", "зафиксир", "помо"]}},
    20: {"msg": "Можно ли посмотреть платформу до покупки?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["гостев", "7 дней", "бесплатн", "продаж"]}},

    # ---- Block B: Documents (21-35) ----
    21: {"msg": "Какие документы нужны для поступления?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["свидетельство", "СНИЛС", "паспорт"]}},
    22: {"msg": "Куда отправлять оригиналы документов?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["Мясницк", "почт", "525"]}},
    23: {"msg": "Можно ли привезти документы в школу лично?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["нет", "не принимает", "централизован"]}},
    24: {"msg": "Отправил документы неделю назад, ответа нет",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["трекинг", "почт", "каждый день", "забираем", "получен"]}},
    25: {"msg": "Где взять бланк заявления на отчисление?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["поддержк", "PDF", "отправ"]}},
    26: {"msg": "Мои документы не приняли, что делать?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["исправ", "загруз", "заново", "письм"]}},
    27: {"msg": "Сколько времени занимает обработка документов?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["15 рабочих", "15 дн"]}},
    28: {"msg": "Потеряли свидетельство о рождении, как быть?",
        "expect": {"any_keywords": ["специалист", "уточн", "обращен", "помо"]}},
    29: {"msg": "Как получить справку об обучении на заочной форме?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["МЭШ", "электронн"]}},
    30: {"msg": "Как получить справку об обучении на семейной форме?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["личн", "кабинет", "Мои справки"]}},
    31: {"msg": "Нужна справка для военкомата",
        "expect": {"any_keywords": ["справк", "обращен", "тикет", "специалист", "запрос"]}},
    32: {"msg": "Нужна справка для получения визы",
        "expect": {"any_keywords": ["справк", "обращен", "тикет", "специалист", "запрос"]}},
    33: {"msg": "Где скачать заявление на зачисление?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["бланк", "система", "индивидуальн", "специалист", "поддержк"]}},
    34: {"msg": "Нужно ли нотариальное заверение документов?",
        "expect": {"tools": ["search_knowledge_base"]}},
    35: {"msg": "Документы из другой страны — нужен перевод?",
        "expect": {"tools": ["search_knowledge_base"]}},

    # ---- Block C: Attestation and grades (36-55) ----
    36: {"msg": "Сколько попыток на аттестацию?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["2 попытк", "две попытк", "третью", "2"]}},
    37: {"msg": "Ребёнок не сдал с первого раза, что делать?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["втор", "попытк", "бесплатн"]}},
    38: {"msg": "Обе попытки не сдал, что теперь?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["третью", "3-", "платн"]}},
    39: {"msg": "В тесте ошибка, что делать?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["претензи", "завершите", "кнопк"]}},
    40: {"msg": "Как итоговая оценка считается?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["среднее", "арифметическ", "двух"]}},
    41: {"msg": "Как подготовиться к аттестации?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["платформ", "учебн", "ФГОС", "тренаж"]}},
    42: {"msg": "Нужна ли камера при сдаче тестов?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["нет", "без камеры", "не нужн", "не требу"]}},
    43: {"msg": "Тесты ограничены по времени?",
        "expect": {"tools": ["search_knowledge_base"]}},
    44: {"msg": "Можно ли сдавать с телефона?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["рекомендуется", "компьютер", "некорректно"]}},
    45: {"msg": "Пробные тесты есть?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["тренаж", "тренировочн", "не ограничен", "безлимитн"]}},
    46: {"msg": "До какого числа нужно сдать аттестацию? 8 класс, семейная форма, Базовый",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["31 мая", "май"]}},
    47: {"msg": "До какого числа сдать аттестацию? 9 класс, СО, тариф Классный",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["15 апрел", "апрел"]}},
    48: {"msg": "До какого числа сдать аттестацию? 11 класс, СО, Базовый",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["15 октябр", "октябр"]}},
    49: {"msg": "Заочная форма, 5 класс — дедлайны по модулям?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["ноябр", "декабр", "апрел", "модул"]}},
    50: {"msg": "Как записаться на ОГЭ?",
        "expect": {"tools": ["search_knowledge_base"]}},
    51: {"msg": "Как записаться на ЕГЭ?",
        "expect": {"tools": ["search_knowledge_base"]}},
    52: {"msg": "Можно ли засчитать спортивную секцию как физ-ру?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["семейн", "заочн"]}},
    53: {"msg": "Музыкальная школа идёт в зачёт?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["справк", "печат", "семейн"]}},
    54: {"msg": "Можно ли получить карту Москвёнок?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["нет", "очн"]}},
    55: {"msg": "По каким учебникам готовиться к аттестации?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["ФГОС", "Просвещени"]}},

    # ---- Block D: Platform (56-70) ----
    56: {"msg": "Где найти тренажёр по предметам?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["Мои предметы", "Мои аттестации", "тренаж"]}},
    57: {"msg": "Не вижу учебные панели в личном кабинете",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["регистрационн", "куратор", "зачислен"]}},
    58: {"msg": "Прошли первый модуль, а второй закрыт",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["пройден", "дата", "полностью", "срок"]}},
    59: {"msg": "Куратор не отвечает третий день",
        "expect": {"escalation": True}},
    60: {"msg": "Ошибка при загрузке домашнего задания",
        "expect": {"any_keywords": ["обращен", "тикет", "специалист", "зафиксир", "помо"]}},
    61: {"msg": "Не вижу свои оценки в ЛК",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["оценк", "журнал", "раздел", "Мои оценки"]}},
    62: {"msg": "Как перейти на другой тариф в середине года?",
        "expect": {"any_keywords": ["уточн", "специалист", "менеджер", "помо"]}},
    63: {"msg": "Хочу добавить второго ребёнка на аккаунт",
        "expect": {"any_keywords": ["специалист", "обращен", "помо", "поддержк"]}},
    64: {"msg": "Где найти учебные материалы?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["платформ", "личн", "кабинет", "материал"]}},
    65: {"msg": "Можно посмотреть платформу до покупки?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["гостев", "7 дней", "бесплатн", "продаж"]}},
    66: {"msg": "Все модули пройдены на заочной. Что дальше?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["оценки", "журнал", "автоматически"]}},
    67: {"msg": "Все модули пройдены на семейной. Что дальше?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["Завершить класс", "справк"]}},
    68: {"msg": "Можно вернуться к материалам после окончания класса?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["Архив", "сохран"]}},
    69: {"msg": "Что нужно для занятий? Какое оборудование?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["компьютер", "планшет", "интернет"]}},
    70: {"msg": "Как связаться с тьютором?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["куратор", "поддержк", "специалист", "тьютор"]}},

    # ---- Block E: SO vs ZO, geography (71-85) ----
    71: {"msg": "В чём разница семейной и заочной формы?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["контингент", "школ", "семейн", "заочн"]}},
    72: {"msg": "Что такое семейное обучение?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["родител", "ответственност", "свободн"]}},
    73: {"msg": "Что такое заочное обучение?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["числится", "школ", "журнал"]}},
    74: {"msg": "Не получается записаться на ЗО в этом году",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["семейн", "следующ"]}},
    75: {"msg": "Хочу перейти с СО на ЗО",
        "expect": {"any_keywords": ["специалист", "менеджер", "уточн", "помо"]}},
    76: {"msg": "Хочу перейти с ЗО на СО",
        "expect": {"any_keywords": ["специалист", "менеджер", "уточн", "помо"]}},
    77: {"msg": "Как открепиться от школы на семейной форме?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["заявлен", "10 рабочих", "форм"]}},
    78: {"msg": "Как открепиться от школы на заочной форме?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["куратор", "заявлен", "отчислен"]}},
    79: {"msg": "Мы переезжаем за границу, можно продолжить учёбу?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["семейн", "интернет", "да"]}},
    80: {"msg": "Мы живём за границей, можно учиться?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["да", "семейн", "интернет"]}},
    81: {"msg": "Временная регистрация в Москве подходит для ЗО?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["регистрац", "Москв"]}},
    82: {"msg": "Можно ли учиться на ЗО без московской прописки?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["нет", "регистрац", "Москв", "невозможно", "необходим"]}},
    83: {"msg": "Ребёнок на СО, хотим параллельно в обычную школу — можно?",
        "expect": {"tools": ["search_knowledge_base"]}},
    84: {"msg": "Можно ли вернуться в обычную школу после экстерната?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["да", "аттестат", "можно"]}},
    85: {"msg": "Есть двойки. Можно на заочную форму?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["нет", "невозможно", "неудовлетворит"]}},

    # ---- Block F: Escalation and negative (86-100) ----
    86: {"msg": "Мы иностранные граждане. Можно ли учиться?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["индивидуальн", "консультант", "специалист"]}},
    87: {"msg": "Мы не из Москвы. Какие варианты?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["вариант", "форм"]}},
    88: {"msg": "Как должна выглядеть справка из секции для зачёта?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["печат", "учреждени", "форм"]}},
    89: {"msg": "Можно привезти или забрать документы самостоятельно?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["нет", "не принимает", "централизован"]}},
    90: {"msg": "Где взять бланки заявлений?",
        "expect": {"tools": ["search_knowledge_base"], "any_keywords": ["поддержк", "специалист", "индивидуальн"]}},
    91: {"msg": "Хочу поговорить с живым человеком",
        "expect": {"escalation": True, "tools": ["escalate_to_manager"]}},
    92: {"msg": "Позовите руководителя",
        "expect": {"escalation": True, "tools": ["escalate_to_manager"]}},
    93: {"msg": "Ничего не работает, я в ярости!!!",
        "expect": {"escalation": True, "any_keywords": ["понима", "жаль", "специалист", "менеджер"]}},
    94: {"msg": "Хочу вернуть деньги",
        "expect": {"escalation": True, "tools": ["escalate_to_manager"]}},
    95: {"msg": "Оплатила неправильный тариф, как поменять?",
        "expect": {"any_keywords": ["специалист", "менеджер", "помо", "обращен"]}},
    96: {"msg": "Куратор нагрубил мне",
        "expect": {"escalation": True, "any_keywords": ["понима", "извин", "сожале", "жаль"]}},
    97: {"msg": "Вы не выполняете свои обязательства",
        "expect": {"escalation": True, "any_keywords": ["понима", "жаль", "специалист", "менеджер"]}},
    98: {"msg": "Буду писать в прокуратуру",
        "expect": {"escalation": True, "any_keywords": ["понима", "жаль", "специалист", "менеджер"]}},
    99: {"msg": "Уже третий раз обращаюсь, никто не помогает",
        "expect": {"escalation": True, "any_keywords": ["понима", "жаль", "извин", "сожале"]}},
}

MULTI_TURN_100 = [
    "У меня проблема с аттестацией",
    "Не могу сдать уже месяц",
    "Хватит, дайте мне человека!",
]


def run_scenarios(ids: list, label: str) -> list:
    results = []
    print(f"\n{'='*60}", flush=True)
    print(f"  {label} — {len(ids)} сценариев", flush=True)
    print(f"{'='*60}", flush=True)
    for sid in ids:
        if sid not in SCENARIOS:
            continue
        sc = SCENARIOS[sid]
        try:
            token = generate_external_token(f"t_{sid}")
            conv_id = start_conversation(token)
            r = send_message(token, conv_id, sc["msg"])
            r = validate(sid, r, sc["expect"])
            results.append(r)
            icon = "✅" if r.passed else "❌"
            print(f"  {icon} #{sid} ({r.duration_s}s) tools={r.tools_called} esc={r.escalation}", flush=True)
            if not r.passed:
                for f in r.fail_reasons:
                    print(f"     ⚠ {f}", flush=True)
                print(f"     Resp: {r.response_text[:180]}", flush=True)
        except Exception as e:
            print(f"  ❌ #{sid} ERROR: {e}", flush=True)
            results.append(TestResult(scenario_id=sid, user_message=sc["msg"], response_text="",
                                      errors=[str(e)], passed=False, fail_reasons=[str(e)]))
        time.sleep(5)
    return results


def run_multi_turn():
    print(f"\n{'='*60}", flush=True)
    print(f"  MULTI-TURN #100", flush=True)
    print(f"{'='*60}", flush=True)
    results = []
    try:
        token = generate_external_token("mt100_final")
        conv_id = start_conversation(token)
        mt = send_multi_turn(token, conv_id, MULTI_TURN_100)
        for i, r in enumerate(mt):
            r.scenario_id = 100
            print(f"  Turn {i+1}: tools={r.tools_called} esc={r.escalation} ({r.duration_s}s)", flush=True)
            print(f"    {r.response_text[:120]}", flush=True)
        if "search_knowledge_base" not in mt[0].tools_called:
            mt[0].passed = False
            mt[0].fail_reasons.append("Turn 1: no KB search")
        if not mt[-1].escalation:
            mt[-1].passed = False
            mt[-1].fail_reasons.append("Turn 3: no escalation")
        ok = all(r.passed for r in mt)
        print(f"  {'✅' if ok else '❌'} Multi-turn #100 {'PASS' if ok else 'FAIL'}", flush=True)
        results.extend(mt)
    except Exception as e:
        print(f"  ❌ ERROR: {e}", flush=True)
        results.append(TestResult(scenario_id=100, user_message="multi-turn", response_text="",
                                  errors=[str(e)], passed=False, fail_reasons=[str(e)]))
    return results


def print_summary(all_results: list):
    passed = sum(1 for r in all_results if r.passed)
    failed = sum(1 for r in all_results if not r.passed)
    total = len(all_results)
    print(f"\n{'='*60}", flush=True)
    print(f"  ИТОГО: {total} тестов | ✅ {passed} PASS | ❌ {failed} FAIL", flush=True)
    print(f"{'='*60}", flush=True)
    if failed > 0:
        print(f"\n  ПРОВАЛЕННЫЕ:", flush=True)
        for r in all_results:
            if not r.passed:
                print(f"  #{r.scenario_id}: {r.user_message[:60]}", flush=True)
                for f in r.fail_reasons:
                    print(f"    ⚠ {f}", flush=True)
    tools = {}
    for r in all_results:
        for t in r.tools_called:
            tools[t] = tools.get(t, 0) + 1
    print(f"\n  Инструменты: {tools}", flush=True)
    esc = sum(1 for r in all_results if r.escalation)
    print(f"  Эскалации: {esc}/{total}", flush=True)
    avg = sum(r.duration_s for r in all_results) / max(total, 1)
    print(f"  Среднее время: {avg:.1f}s", flush=True)


def main():
    batch = sys.argv[1] if len(sys.argv) > 1 else "all"
    batches = {
        "A": (list(range(1, 21)), "Block A: Регистрация (1-20)"),
        "B": (list(range(21, 36)), "Block B: Документы (21-35)"),
        "C": (list(range(36, 56)), "Block C: Аттестация (36-55)"),
        "D": (list(range(56, 71)), "Block D: Платформа (56-70)"),
        "E": (list(range(71, 86)), "Block E: СО/ЗО (71-85)"),
        "F": (list(range(86, 100)), "Block F: Эскалации (86-99)"),
        "100": ([], "Multi-turn #100"),
    }
    all_results = []
    if batch == "all":
        for key in ["A", "B", "C", "D", "E", "F"]:
            ids, label = batches[key]
            all_results.extend(run_scenarios(ids, label))
        all_results.extend(run_multi_turn())
    elif batch in batches:
        if batch == "100":
            all_results.extend(run_multi_turn())
        else:
            ids, label = batches[batch]
            all_results.extend(run_scenarios(ids, label))
    else:
        # Run specific scenario IDs: e.g. "4,5,24"
        ids = [int(x) for x in batch.split(",")]
        all_results.extend(run_scenarios(ids, f"Custom: {ids}"))
    print_summary(all_results)


if __name__ == "__main__":
    main()

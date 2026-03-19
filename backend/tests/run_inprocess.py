#!/usr/bin/env python3
"""
In-process test runner using FastAPI TestClient.
No running server needed — bypasses port contention.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time

# Set test-compatible env vars before any app imports
os.environ.setdefault("EXTERNAL_LINK_SECRET", "4bf5a53f556b3366255c4405ef57363dc2aa42d52b3db000")
os.environ.setdefault("PORTAL_JWT_SECRET", "test_portal")
os.environ.setdefault("SESSION_SIGNING_SECRET", "test_session")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", os.environ.get("TELEGRAM_BOT_TOKEN", "test"))

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

SECRET = os.environ["EXTERNAL_LINK_SECRET"]
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "..", "test_results")


def make_token(lead_id: str) -> str:
    exp = str(int(time.time()) + 3600)
    payload = f"{lead_id}:{exp}".encode("utf-8")
    sign = hmac.new(SECRET.encode(), payload, hashlib.sha256).hexdigest()
    return f"{lead_id}:{exp}:{sign}"


def parse_sse(text: str) -> dict:
    """Parse SSE text, return structured result."""
    response_text = ""
    tool_calls = []
    suggestions = []
    escalation = None
    payment = None

    for line in text.split("\n"):
        if line.startswith("event: "):
            event_type = line[7:].strip()
        elif line.startswith("data: "):
            try:
                data = json.loads(line[6:])
            except json.JSONDecodeError:
                continue

            if event_type == "token":
                response_text += data.get("text", "")
            elif event_type == "tool_call":
                tool_calls.append(data.get("name", ""))
            elif event_type == "suggestions":
                suggestions = data.get("chips", [])
            elif event_type == "escalation":
                escalation = data
            elif event_type == "payment_card":
                payment = data
            elif event_type == "done" and not response_text:
                response_text = data.get("text", "")

    return {
        "text": response_text,
        "tools": tool_calls,
        "suggestions": suggestions,
        "escalation": escalation,
        "payment": payment,
        "is_fallback": "техническая пауза" in response_text.lower() if response_text else not response_text,
    }


def run_dialogue(scenario_id: int, name: str, messages: list[str]) -> dict:
    """Run a full multi-turn dialogue using TestClient."""
    lead_id = f"qual-{scenario_id}-{int(time.time())}"
    token = make_token(lead_id)
    auth = {"external_token": token}

    # Start conversation
    r = client.post("/api/v1/conversations/start", json={"auth": auth, "agent_role": "sales"})
    if r.status_code != 200:
        return {"scenario_id": scenario_id, "name": name, "status": "ERROR",
                "error": f"Start failed: {r.status_code}", "turns": []}

    conv_id = r.json()["conversation_id"]
    turns = []

    for msg in messages:
        r = client.post("/api/v1/chat/stream", json={
            "auth": auth,
            "message": msg,
            "conversation_id": conv_id,
            "agent_role": "sales",
        })

        if r.status_code != 200:
            turns.append({"user": msg, "agent": "", "tools": [], "is_fallback": True,
                          "error": f"HTTP {r.status_code}"})
            continue

        parsed = parse_sse(r.text)
        turns.append({
            "user": msg,
            "agent": parsed["text"][:500],
            "tools": parsed["tools"],
            "suggestions": parsed["suggestions"],
            "is_fallback": parsed["is_fallback"],
            "escalation": parsed["escalation"],
            "payment": parsed["payment"],
        })

        time.sleep(2)  # Small delay between turns

    valid = sum(1 for t in turns if not t.get("is_fallback"))
    all_tools = []
    for t in turns:
        all_tools.extend(t.get("tools", []))

    return {
        "scenario_id": scenario_id,
        "name": name,
        "conversation_id": conv_id,
        "status": "OK" if valid == len(turns) else ("PARTIAL" if valid > 0 else "FAIL"),
        "valid_turns": valid,
        "total_turns": len(turns),
        "all_tools": all_tools,
        "had_escalation": any(t.get("escalation") for t in turns),
        "had_payment": any(t.get("payment") for t in turns),
        "turns": turns,
    }


# All 100 scenarios
SCENARIOS = [
    # Block A: Classic parent (1-20)
    (1, "Parent 2nd+tutor→Классный70K", ["Добрый день", "Сын во 2 классе", "Нужно с тьютором", "Сколько стоит?"]),
    (2, "Parent 5th self→Базовый19.5K", ["Здравствуйте, хочу узнать про обучение", "Дочь в 5 классе", "Самостоятельное обучение подходит", "Как записаться?"]),
    (3, "Parent 9th OGE→Выпускник", ["Привет! У меня ребёнок в 9 классе, нужна подготовка к ОГЭ", "Какие варианты для выпускников?", "Сколько стоит?"]),
    (4, "Parent 11th EGE→Выпускник", ["Добрый день, 11 класс, ЕГЭ", "Что есть для подготовки?", "Какие цены?"]),
    (5, "Parent 3rd Moscow→Заочный1₽", ["Здравствуйте, мы в Москве", "3 класс", "Есть ли бесплатное обучение?", "Прописка московская"]),
    (6, "Parent 4th экстернат→Базовый", ["Хотим экстернат", "4 класс", "Хотим гибкий график", "Без живых уроков"]),
    (7, "Parent 10th+расценки→Классный", ["Мне нужна информация о ценах", "10 класс", "Нужны живые уроки и поддержка"]),
    (8, "Parent 1st recommended→Классный70K", ["Добрый день, нам порекомендовали вашу школу", "У нас 1 класс", "Хотим полное сопровождение"]),
    (9, "Bullying 8th→Классный85K+empathy", ["Здравствуйте, у ребёнка проблемы в школе", "8 класс", "Буллинг, хотим уйти", "Что-то с поддержкой"]),
    (10, "Kazakhstan 6th→Базовый", ["Мы за границей, Казахстан", "6 класс", "Самостоятельно может", "Нужен аттестат РФ"]),
    (11, "Dubai 5th→Классный+Dubai", ["Мы в Дубае", "5 класс", "Хотим с живыми уроками"]),
    (12, "6yo→1st Классный70K", ["Ребёнку 6 лет, идёт в 1 класс", "Хотим сразу на семейное", "С тьютором"]),
    (13, "Two kids 3+7", ["У нас двое детей", "3 и 7 класс", "Хотим обоих на семейное", "Нужен индивидуальный подход"]),
    (14, "Sportsman 6th→Базовый", ["Ребёнок — спортсмен, тренировки каждый день", "6 класс", "Нужен свободный график"]),
    (15, "ADHD 4th→Персональный+esc", ["У ребёнка СДВГ", "4 класс", "Нужна адаптированная программа", "Что можете предложить?"]),
    (16, "Trial→7days", ["Хочу попробовать перед покупкой", "5 класс", "Есть ли пробный период?"]),
    (17, "Corporate→escalate", ["Я представляю компанию, хотим для сотрудников", "Корпоративные условия есть?"]),
    (18, "Summer 5th→Летний19.5K", ["Хотим попробовать на лето", "5 класс", "Сдать предметы до осени"]),
    (19, "Transfer SO 8th", ["Ребёнок уже на СО", "8 класс", "Хотим сменить школу на вашу"]),
    (20, "Guardians 3rd→docs", ["Опекуны, оформляем ребёнка", "3 класс", "Документы с опекой", "Нужно полное сопровождение"]),
    # Block B: Teenager (21-35)
    (21, "Teen 9th informal→Выпускник", ["хай, я в 9 классе", "хочу на семейное", "чё по ценам?"]),
    (22, "Teen 10th self→варианты", ["прив) мне 16, 10 класс", "хочу сам записаться", "какие варианты?"]),
    (23, "Teen OGE minimal→Выпускник", ["п", "мне огэ надо сдать", "норм подготовка?"]),
    (24, "Teen 8th detailed", ["Привет, мне 14 лет", "Хочу уйти из школы", "Родители согласны", "8 класс, что есть?"]),
    (25, "Teen gamer→Базовый", ["хай, я хочу свободный график", "мне 15, 9 класс", "чтобы на тренировки успевать"]),
    (26, "Teen EGE 11th→Классный", ["мне егэ сдавать", "11 класс", "хочу с подготовкой", "сколько стоит классный?"]),
    (27, "Teen 10th Базовый", ["привет, можно самому записаться?", "10 класс", "хочу базовый, без уроков"]),
    (28, "Teen English", ["hello, i'm in 10th grade", "can I study in English?"]),
    (29, "Teen Dubai 9th OGE", ["хай, я из Дубая", "9 класс", "нужна подготовка к ОГЭ на русском"]),
    (30, "Teen 11th Персональный", ["я в 11 классе", "хочу персональный", "что входит?", "сколько стоит?"]),
    (31, "Teen attestation Q", ["слышал у вас без камер тесты", "правда?", "круто, а для 10 класса что есть?"]),
    (32, "Teen transfer", ["хочу перейти к вам", "сейчас в обычной школе", "9 класс", "что нужно сделать?"]),
    (33, "Teen 8th self-research", ["мне 14, 8 класс", "родители не против", "хочу сам разобраться с программами"]),
    (34, "Teen skip grade", ["можно ли перейти через класс?", "мне 15, сейчас в 9", "хочу сразу в 11"]),
    (35, "Teen schedule", ["у вас можно учиться когда хочешь?", "8 класс", "а экзамены когда?"]),
    # Block C: Non-standard (36-55)
    (36, "Foreigner Turkey", ["Мы иностранцы, живём в Турции", "Ребёнку 10 лет", "Хотим российское образование"]),
    (37, "Director company", ["Я директор компании", "Хочу организовать обучение для детей сотрудников", "10 детей, разные классы"]),
    (38, "Grandmother", ["Я бабушка, внуку 10 лет", "3 класс", "Родители работают, хочу помочь"]),
    (39, "Large family 4 kids", ["Мы многодетная семья, 4 детей", "1, 4, 7, 10 класс"]),
    (40, "Disabled→Персональный+esc", ["Ребёнок-инвалид", "Нужна адаптированная программа", "6 класс"]),
    (41, "Teacher researching", ["Я сам учитель, хочу понять вашу программу", "Может порекомендую ученикам"]),
    (42, "Ukraine 5th", ["Мы переехали из Украины", "Ребёнок в 5 классе", "Документов минимум"]),
    (43, "Intl school 8th", ["Ребёнок учился в международной школе", "Нужен перевод в российскую систему", "8 класс"]),
    (44, "Single father", ["Я один воспитываю дочь", "Она в 6 классе", "Нужна помощь с обучением", "Хочу чтобы кто-то поддержал"]),
    (45, "Matcapital", ["Можно ли оплатить маткапиталом?", "4 класс", "Базовый подойдёт"]),
    (46, "Tax deduction", ["А налоговый вычет можно?", "5 класс Классный", "Как оформить?"]),
    (47, "Installment", ["Рассрочка есть?", "7 класс Классный", "На сколько месяцев?"]),
    (48, "Wrong tariff name", ["Хочу Премиум тариф", "5 класс", "С живыми уроками"]),
    (49, "Knows nothing", ["Я ничего не понимаю в этом, помогите", "У меня ребёнок, надо учить", "4 класс"]),
    (50, "Knows everything→pay", ["Базовый Весь Год для 3 класса, 19500, как оплатить?"]),
    (51, "Belarus 7th", ["Мы из Беларуси", "7 класс", "Хотим российский аттестат"]),
    (52, "Homeschooler 9th", ["Ребёнок на хоумскулинге уже 3 года", "9 класс", "Нужна только аттестация"]),
    (53, "Temp reg Moscow→Заочный", ["Временная регистрация в Москве", "5 класс", "Можно ли Заочный?"]),
    (54, "Topic switch", ["Хочу Классный", "А кстати, физкультура есть?", "Ну ладно, так 5 класс Классный"]),
    (55, "Religious", ["У вас светское образование?", "Мы верующая семья", "4 класс", "Есть ли какие-то ограничения?"]),
    # Block D: Full sales cycle (56-75)
    (56, "Full Basic 5th", ["5 класс", "Базовый", "Сколько?", "Мария Иванова, +79161234567", "Оплачиваем"]),
    (57, "Full matcapital", ["5 класс", "ОГЭ", "Выпускник Базовый", "Оплата маткапиталом", "Иван Петров, +79991112233"]),
    (58, "Quick Basic 5th", ["5 класс, Базовый", "Сколько? 19,500?", "Давайте, Ольга +79161112233"]),
    (59, "Персональный 7th→esc", ["Хотим Персональный для 7 класса", "Расскажите подробнее", "Да, хотим", "Как оплатить?"]),
    (60, "Заочный 4th Moscow", ["Заочный для 4 класса", "Мы в Москве", "Прописка московская", "Как записаться?"]),
    (61, "11th Классный+install", ["11 класс", "Нужна максимальная подготовка к ЕГЭ", "Классный Выпускник", "Рассрочка есть?", "Давайте, Сергей +79001112233"]),
    (62, "Классный 3rd full", ["Хочу Классный для 3 класса", "Расскажите что входит", "Сколько стоит?", "Как оплатить?"]),
    (63, "Compare tariffs", ["Чем Базовый отличается от Классного?", "5 класс", "А Классный что включает?", "Пожалуй Классный"]),
    (64, "Two kids 3+8", ["Двое детей — 3 и 8 класс", "Обоим нужно", "Для младшего Классный, для старшего Базовый"]),
    (65, "Классный 1st details", ["1 класс Классный", "Что входит?", "Сколько?", "70 000 за год?"]),
    (66, "Objection expensive→down", ["5 класс", "Дорого", "Что подешевле?", "Базовый подойдёт", "Оплачиваем, Анна +79161234567"]),
    (67, "Pause→followup", ["Привет", "7 класс", "Мне нужно подумать"]),
    (68, "Existing→support", ["Мы уже клиенты", "Нужна помощь с платформой"]),
    (69, "Rejection", ["5 класс", "Нет, нам не подходит", "Спасибо, до свидания"]),
    (70, "Discount→escalate", ["9 класс", "Выпускник", "А скидка будет?", "Без скидки не буду"]),
    (71, "Install 1st Классный", ["1 класс, Классный", "70 000?", "Есть рассрочка?", "4 платежа по 17 500? Отлично", "Оформляем, Елена +79161234567"]),
    (72, "Full 9th Выпускник", ["9 класс", "Нужна подготовка к ОГЭ", "Классный Выпускник", "Сколько?", "Давайте, Андрей +79031234567"]),
    (73, "Full Dubai 6th", ["Мы в ОАЭ", "6 класс", "Нужен двойной аттестат", "Как записаться?"]),
    (74, "Full Базовый 2nd", ["2 класс Базовый", "Сколько стоит?", "Оформляем, Наталья +79161234567"]),
    (75, "11th Персональный→esc", ["11 класс Персональный", "250 000?", "Дорого, но нужно", "Как оплатить?"]),
    # Block E: Qualification failures (76-90)
    (76, "NO phone first msg", ["Привет, расскажите об обучении"]),
    (77, "NO address Q", ["Добрый день, 5 класс", "Что есть для нас?"]),
    (78, "NO kids count Q", ["Здравствуйте, хочу узнать про вашу школу"]),
    (79, "Max 1 qual Q per msg", ["Добрый день", "4 класс"]),
    (80, "Answer first THEN ask", ["Сколько стоит Классный?", "5 класс"]),
    (81, "Dont re-ask grade", ["У меня ребёнок в 6 классе, какие варианты?"]),
    (82, "Use known name", ["Меня зовут Анна, ребёнок в 3 классе", "Какие тарифы?"]),
    (83, "Dont re-ask phone", ["Мой телефон +79161234567, ребёнок в 5 классе", "Хочу Базовый"]),
    (84, "Age→grade", ["Ребёнку 7 лет, идёт в школу в этом году"]),
    (85, "No 2+ Q in one msg", ["Привет", "Расскажите о школе"]),
    (86, "Unknown grade→ask", ["Хочу записать ребёнка", "Ему 12 лет"]),
    (87, "Already mentioned goal", ["Нужна подготовка к ОГЭ", "9 класс"]),
    (88, "Tone вы for parents", ["Здравствуйте, я мама ученика 5 класса"]),
    (89, "Tone ты for teens", ["хай, я в 10 классе"]),
    (90, "Off-topic redirect", ["Какая погода завтра?"]),
    # Block F: Suggestions & UX (91-100)
    (91, "Chips after tariffs", ["Расскажите про тарифы", "5 класс"]),
    (92, "Chips after payment", ["Как оплатить?", "Базовый 5 класс"]),
    (93, "Chips after greeting", ["Привет!"]),
    (94, "No chips after esc", ["Хочу поговорить с менеджером"]),
    (95, "Chips not repeat Q", ["Сколько стоит Классный 5 класс?"]),
    (96, "Chips contextual", ["У меня ребёнок в 7 классе, нужен тьютор"]),
    (97, "Max 3-4 chips", ["Расскажите про Классный для 5 класса"]),
    (98, "Chip value sendable", ["Что входит в Базовый?"]),
    (99, "Chips after payment_card", ["Хочу оплатить Базовый 5 класс", "Анна +79161234567"]),
    (100, "Chips after enrollment", ["Как записаться?", "3 класс", "Базовый"]),
]


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", type=str, help="e.g. 1,5,9,21")
    parser.add_argument("--block", type=str, help="A-F")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--output", type=str, default=os.path.join(RESULTS_DIR, "qual_inprocess.json"))
    args = parser.parse_args()

    block_ranges = {"A": (1, 20), "B": (21, 35), "C": (36, 55),
                    "D": (56, 75), "E": (76, 90), "F": (91, 100)}

    if args.ids:
        target_ids = set(int(x) for x in args.ids.split(","))
    elif args.block:
        s, e = block_ranges[args.block.upper()]
        target_ids = set(range(s, e + 1))
    elif args.all:
        target_ids = set(range(1, 101))
    else:
        target_ids = set(range(1, 101))

    # Load existing results
    os.makedirs(RESULTS_DIR, exist_ok=True)
    existing = []
    if os.path.exists(args.output):
        with open(args.output) as f:
            existing = json.load(f)

    done_ids = {r["scenario_id"] for r in existing if r.get("status") in ("OK",)}
    todo_ids = sorted(target_ids - done_ids)

    print(f"Queued: {len(todo_ids)} scenarios | Already done: {len(done_ids)}", flush=True)

    results = {r["scenario_id"]: r for r in existing}

    for sid, name, msgs in SCENARIOS:
        if sid not in todo_ids:
            continue

        print(f"\n[{sid}] {name} ({len(msgs)} msgs)...", flush=True)
        t0 = time.time()
        r = run_dialogue(sid, name, msgs)
        elapsed = int(time.time() - t0)
        r["elapsed_s"] = elapsed

        results[sid] = r
        status = r["status"]
        valid = r.get("valid_turns", 0)
        total = r.get("total_turns", 0)
        tools = r.get("all_tools", [])
        print(f"  [{status}] {valid}/{total} valid | tools: {tools} | {elapsed}s", flush=True)

        # Save after each
        sorted_results = sorted(results.values(), key=lambda x: x["scenario_id"])
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(sorted_results, f, ensure_ascii=False, indent=2)

        time.sleep(3)

    # Summary
    all_r = sorted(results.values(), key=lambda x: x["scenario_id"])
    ok = sum(1 for r in all_r if r.get("status") == "OK")
    partial = sum(1 for r in all_r if r.get("status") == "PARTIAL")
    fail = sum(1 for r in all_r if r.get("status") in ("FAIL", "ERROR"))
    print(f"\n{'='*60}", flush=True)
    print(f"DONE: {len(all_r)} | OK: {ok} | PARTIAL: {partial} | FAIL: {fail}", flush=True)
    print(f"Saved: {args.output}", flush=True)


if __name__ == "__main__":
    main()

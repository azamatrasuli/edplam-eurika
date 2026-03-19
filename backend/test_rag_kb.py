"""
RAG Quality Test Runner — verifies KB search accuracy after fixes.
Runs targeted scenarios with retry logic.
"""
import hashlib
import hmac
import json
import sys
import time
from dataclasses import dataclass, field

import httpx

BASE_URL = "http://localhost:8009/api/v1"
EXTERNAL_LINK_SECRET = "4bf5a53f556b3366255c4405ef57363dc2aa42d52b3db000"
TIMEOUT = 120.0
FALLBACK_MARKER = "Секунду, есть техническая пауза"
MAX_RETRIES = 2
RETRY_DELAY = 8


@dataclass
class TestResult:
    scenario_id: int
    question: str
    expected: str
    actual_response: str = ""
    tools_called: list[str] = field(default_factory=list)
    kb_searched: bool = False
    verdict: str = ""
    notes: str = ""


def generate_external_token(lead_id: str = "rag-kb-test") -> str:
    expires_ts = str(int(time.time()) + 48 * 3600)
    msg = f"{lead_id}:{expires_ts}".encode("utf-8")
    signature = hmac.new(EXTERNAL_LINK_SECRET.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return f"{lead_id}:{expires_ts}:{signature}"


def start_conversation(token: str, role: str = "sales") -> str:
    resp = httpx.post(f"{BASE_URL}/conversations/start",
                      json={"auth": {"external_token": token}, "agent_role": role, "force_new": True},
                      timeout=TIMEOUT)
    resp.raise_for_status()
    return resp.json()["conversation_id"]


def send_message_sse(token: str, conversation_id: str, message: str, role: str = "sales") -> tuple[str, list[str]]:
    full_text = ""
    tools_called = []
    with httpx.stream("POST", f"{BASE_URL}/chat/stream",
                      json={"auth": {"external_token": token}, "conversation_id": conversation_id,
                            "message": message, "agent_role": role},
                      timeout=TIMEOUT) as resp:
        resp.raise_for_status()
        buffer = ""
        for chunk in resp.iter_text():
            buffer += chunk
            while "\n\n" in buffer:
                event_block, buffer = buffer.split("\n\n", 1)
                lines = event_block.strip().split("\n")
                event_type = event_data = ""
                for line in lines:
                    if line.startswith("event: "): event_type = line[7:]
                    elif line.startswith("data: "): event_data = line[6:]
                if not event_data: continue
                try: payload = json.loads(event_data)
                except json.JSONDecodeError: continue
                if event_type == "token": full_text += payload.get("text", "")
                elif event_type == "tool_call": tools_called.append(payload.get("name", ""))
                elif event_type == "done" and not full_text: full_text = payload.get("text", "")
    return full_text.strip(), tools_called


def check_number_in_response(response: str, number: str) -> bool:
    clean = response.replace(" ", "").replace("\u00a0", "").replace(",", "").replace(".", "")
    num = number.replace(" ", "").replace(",", "").replace(".", "")
    return num in clean


def check_contains(response: str, keywords: list[str]) -> tuple[bool, list[str]]:
    r = response.lower()
    missing = [kw for kw in keywords if kw.lower() not in r]
    return len(missing) == 0, missing


SCENARIOS = [
    # Prices
    {"id": 1, "q": "Сколько стоит Базовый для 1 класса?", "nums": ["12500"], "kw": [], "exp": "12500"},
    {"id": 2, "q": "Сколько стоит Базовый для 2 класса?", "nums": ["16500"], "kw": [], "exp": "16500"},
    {"id": 3, "q": "Сколько стоит Базовый для 8 класса?", "nums": ["24000"], "kw": [], "exp": "24000"},
    {"id": 4, "q": "Классный для 1-4 классов?", "nums": ["70000"], "kw": [], "exp": "70000"},
    {"id": 5, "q": "Классный для 5-7 классов?", "nums": ["80000"], "kw": [], "exp": "80000"},
    {"id": 6, "q": "Классный для 8 класса?", "nums": ["85000"], "kw": [], "exp": "85000"},
    {"id": 7, "q": "Выпускник Базовый с ГИА?", "nums": ["98900"], "kw": [], "exp": "98900"},
    {"id": 8, "q": "Выпускник Классный с ГИА?", "nums": ["125000"], "kw": [], "exp": "125000"},
    {"id": 9, "q": "Персональный тариф?", "nums": ["250000"], "kw": [], "exp": "250000"},
    {"id": 10, "q": "Заочный тариф?", "nums": ["1"], "kw": ["москв"], "exp": "1 руб, Москва"},
    # Company facts
    {"id": 11, "q": "Когда основана школа?", "nums": ["2017"], "kw": [], "exp": "2017"},
    {"id": 12, "q": "Кто основатель EdPalm?", "nums": [], "kw": ["гузель", "гурдус"], "exp": "Гузель Гурдус"},
    {"id": 13, "q": "Сколько учеников за всё время?", "nums": ["75000"], "kw": [], "exp": "75000+"},
    {"id": 14, "q": "Сколько выпускников с аттестатами?", "nums": ["8000"], "kw": [], "exp": "~8000"},
    {"id": 15, "q": "Какой рейтинг на Яндексе?", "nums": ["5"], "kw": [], "exp": "5.00"},
    {"id": 16, "q": "В скольких регионах работаете?", "nums": ["81"], "kw": [], "exp": "81"},
    {"id": 17, "q": "В скольких странах?", "nums": ["30"], "kw": [], "exp": "30"},
    {"id": 18, "q": "Есть филиал в ОАЭ?", "nums": [], "kw": ["dubai", "дубай", "оаэ"], "exp": "Dubai/ОАЭ"},
    {"id": 19, "q": "Какая награда у школы?", "nums": [], "kw": ["лучш"], "exp": "Лучшая школа 2024"},
    {"id": 20, "q": "Сколько медалистов?", "nums": [], "kw": ["трет"], "exp": "каждый третий"},
    # Attestation
    {"id": 21, "q": "Как проходит аттестация?", "nums": [], "kw": ["онлайн", "камер"], "exp": "онлайн без камеры"},
    {"id": 22, "q": "Сколько попыток?", "nums": ["2"], "kw": [], "exp": "2 попытки"},
    {"id": 23, "q": "Аттестат государственного образца?", "nums": [], "kw": ["государственн"], "exp": "да"},
    # Enrollment & payments
    {"id": 24, "q": "Можно вернуть деньги?", "nums": ["7"], "kw": [], "exp": "7 дней"},
    {"id": 25, "q": "Есть пробный период?", "nums": ["7"], "kw": ["бесплатн"], "exp": "7 дней бесплатно"},
    {"id": 26, "q": "Есть ли рассрочка?", "nums": [], "kw": ["сплит", "рассрочк"], "exp": "Яндекс Сплит"},
    {"id": 27, "q": "Можно оплатить материнским капиталом?", "nums": [], "kw": ["материнск"], "exp": "да"},
    # Education
    {"id": 28, "q": "Какие учебники используются?", "nums": [], "kw": ["просвещени"], "exp": "Просвещение"},
    {"id": 29, "q": "Есть мобильное приложение?", "nums": [], "kw": ["ios", "android"], "exp": "iOS/Android"},
    {"id": 30, "q": "Это законно учиться дома?", "nums": ["273"], "kw": [], "exp": "ФЗ-273"},
    # Hallucination traps
    {"id": 31, "q": "Назовите имена учителей", "nums": [], "kw": [], "exp": "НЕ придумывать", "trap": True},
    {"id": 32, "q": "Какой процент сдачи ЕГЭ?", "nums": [], "kw": [], "exp": "НЕ придумывать", "trap": True},
    {"id": 33, "q": "Какой курс доллара для Dubai?", "nums": [], "kw": [], "exp": "НЕ придумывать", "trap": True},
    {"id": 34, "q": "Есть скидка 20%?", "nums": [], "kw": ["менеджер", "уточн"], "exp": "к менеджеру"},
    {"id": 35, "q": "Расскажите про GHEC 2018", "nums": ["100", "35"], "kw": [], "exp": "100 спикеров, 35 стран"},
]


def evaluate(sc: dict, response: str, tools: list[str]) -> TestResult:
    r = TestResult(scenario_id=sc["id"], question=sc["q"], expected=sc["exp"],
                   actual_response=response, tools_called=tools,
                   kb_searched="search_knowledge_base" in tools)
    if not response:
        r.verdict = "ERROR"; r.notes = "Empty"; return r
    if sc.get("trap"):
        r.verdict = "MANUAL_CHECK"; r.notes = f"Len={len(response)}"; return r
    nums_ok = all(check_number_in_response(response, n) for n in sc.get("nums", []))
    kw_ok, missing_kw = check_contains(response, sc.get("kw", []))
    missing_nums = [n for n in sc.get("nums", []) if not check_number_in_response(response, n)]
    if nums_ok and kw_ok: r.verdict = "CORRECT"
    elif nums_ok or kw_ok: r.verdict = "INCOMPLETE"; r.notes = f"miss_nums={missing_nums} miss_kw={missing_kw}"
    else: r.verdict = "WRONG"; r.notes = f"miss_nums={missing_nums} miss_kw={missing_kw}"
    return r


def main():
    start_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    end_id = int(sys.argv[2]) if len(sys.argv) > 2 else 999
    scenarios = [s for s in SCENARIOS if start_id <= s["id"] <= end_id]
    print(f"Running {len(scenarios)} scenarios...")

    all_results = []
    token = generate_external_token(f"rag-kb-{int(time.time())}")

    for sc in scenarios:
        sid = sc["id"]
        print(f"  [{sid:3d}] {sc['q'][:55]}...", end=" ", flush=True)
        result = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                conv_id = start_conversation(token, "sales")
                response, tools = send_message_sse(token, conv_id, sc["q"], "sales")
                result = evaluate(sc, response, tools)
                if FALLBACK_MARKER in response and attempt < MAX_RETRIES:
                    print(f"(retry {attempt+1})...", end=" ", flush=True)
                    time.sleep(RETRY_DELAY); continue
                break
            except Exception as e:
                if attempt < MAX_RETRIES:
                    print(f"(err retry)...", end=" ", flush=True)
                    time.sleep(RETRY_DELAY); continue
                result = TestResult(scenario_id=sid, question=sc["q"], expected=sc["exp"],
                                    verdict="ERROR", notes=str(e)[:100])
                break
        print(f"→ {result.verdict}", flush=True)
        all_results.append(result)
        time.sleep(2)

    # Report
    verdicts = {}
    for r in all_results: verdicts[r.verdict] = verdicts.get(r.verdict, 0) + 1
    kb_count = sum(1 for r in all_results if r.kb_searched)

    print(f"\n{'='*70}\nRAG QUALITY REPORT\n{'='*70}")
    print(f"Total: {len(all_results)}")
    for v, c in sorted(verdicts.items()): print(f"  {v}: {c}")
    print(f"search_knowledge_base called: {kb_count}/{len(all_results)}")

    print("\n--- ISSUES ---")
    for r in all_results:
        if r.verdict not in ("CORRECT",):
            preview = r.actual_response[:150].replace("\n", " ") if r.actual_response else "(empty)"
            print(f"\n[{r.scenario_id}] {r.verdict} | KB={r.kb_searched} | Tools={r.tools_called}")
            print(f"  Q: {r.question}")
            print(f"  Expected: {r.expected}")
            print(f"  Got: {preview}")
            if r.notes: print(f"  Notes: {r.notes}")

    # Save JSON
    data = [{"id": r.scenario_id, "q": r.question, "exp": r.expected,
             "resp": r.actual_response[:300], "tools": r.tools_called, "kb": r.kb_searched,
             "verdict": r.verdict, "notes": r.notes} for r in all_results]
    path = "test_results/rag_kb_results.json"
    import os; os.makedirs("test_results", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f: json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\nSaved to {path}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
Support Sprint 4 — 30-case test runner.

Verifies:
  - search_knowledge_base called on content questions
  - auto-tags written to conversations.tags
  - collect_nps + tag_conversation tool calls
  - escalate_to_manager on negative messages
  - get_client_profile on phone mention
  - notifications scheduled (payment_reminder, document_reminder)
  - multi-turn NPS flow
  - multi-turn tagging flow

Run:
  cd eurika/backend
  PYTHONPATH=. python tests/run_support_s4.py [--ids 1,5,10] [--all]
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
from typing import Any

os.environ.setdefault("EXTERNAL_LINK_SECRET", "4bf5a53f556b3366255c4405ef57363dc2aa42d52b3db000")
os.environ.setdefault("PORTAL_JWT_SECRET", "test_portal")
os.environ.setdefault("SESSION_SIGNING_SECRET", "test_session")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", os.environ.get("TELEGRAM_BOT_TOKEN", "test"))

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient
from app.main import app
from app.db.pool import init_pool
from app.db.repository import ConversationRepository

# Ensure DB pool is available for get_db_state() calls that happen outside requests
init_pool()

client = TestClient(app)
SECRET = os.environ["EXTERNAL_LINK_SECRET"]
RESULTS_DIR = os.path.join(os.path.dirname(__file__), "..", "test_results")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_token(lead_id: str) -> str:
    exp = str(int(time.time()) + 3600)
    payload = f"{lead_id}:{exp}".encode()
    sign = hmac.new(SECRET.encode(), payload, hashlib.sha256).hexdigest()
    return f"{lead_id}:{exp}:{sign}"


def parse_sse(text: str) -> dict:
    event_type = ""
    response_text = ""
    tool_calls: list[str] = []
    suggestions: list[str] = []
    escalation = None

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
            elif event_type == "done" and not response_text:
                response_text = data.get("text", "")

    return {
        "text": response_text,
        "tools": tool_calls,
        "suggestions": suggestions,
        "escalation": escalation,
        "is_fallback": "техническая пауза" in response_text.lower() if response_text else not response_text,
    }


def get_db_state(conv_id: str) -> dict:
    """Read conversation state from DB after the scenario."""
    from app.db.pool import get_connection
    try:
        with get_connection() as conn:
            if conn is None:
                return {"tags": [], "nps": None, "notifications": [], "db_error": "no connection"}
            with conn.cursor() as cur:
                # Tags (dict_row → access by column name)
                cur.execute("SELECT tags FROM conversations WHERE id = %s", (conv_id,))
                row = cur.fetchone()
                tags = list(row["tags"]) if row and row.get("tags") else []

                # NPS
                cur.execute(
                    "SELECT rating, comment FROM agent_nps_ratings WHERE conversation_id = %s LIMIT 1",
                    (conv_id,),
                )
                nps_row = cur.fetchone()
                nps = {"rating": nps_row["rating"], "comment": nps_row["comment"]} if nps_row else None

                # Notifications linked to this conversation
                cur.execute(
                    "SELECT notification_type, status FROM agent_notifications "
                    "WHERE conversation_id = %s ORDER BY created_at",
                    (conv_id,),
                )
                notifications = [{"type": r["notification_type"], "status": r["status"]} for r in cur.fetchall()]

        return {"tags": tags, "nps": nps, "notifications": notifications}
    except Exception as e:
        return {"tags": [], "nps": None, "notifications": [], "db_error": str(e)}


def run_scenario(
    sid: int,
    name: str,
    messages: list[str | list[str]],  # str = single turn, list = [user_msg, ...] sequence
    *,
    expect_tools: list[str] | None = None,
    expect_tags: list[str] | None = None,
    expect_nps: bool = False,
    expect_escalation: bool = False,
    notes: str = "",
) -> dict:
    """Run a multi-turn support chat and check assertions."""
    lead_id = f"supp-s4-{sid}-{int(time.time())}"
    token = make_token(lead_id)
    auth = {"external_token": token}

    # Start conversation
    r = client.post("/api/v1/conversations/start", json={
        "auth": auth, "agent_role": "support",
    })
    if r.status_code != 200:
        return _fail(sid, name, f"Start failed: {r.status_code} {r.text[:200]}")

    conv_id = r.json()["conversation_id"]
    turns = []
    all_tools: list[str] = []

    for msg in messages:
        r = client.post("/api/v1/chat/stream", json={
            "auth": auth,
            "message": msg,
            "conversation_id": conv_id,
            "agent_role": "support",
        })
        if r.status_code != 200:
            turns.append({"user": msg, "agent": "", "tools": [], "is_fallback": True,
                          "error": f"HTTP {r.status_code}"})
            continue

        parsed = parse_sse(r.text)
        turns.append({
            "user": msg,
            "agent": parsed["text"][:600],
            "tools": parsed["tools"],
            "escalation": parsed["escalation"],
            "is_fallback": parsed["is_fallback"],
        })
        all_tools.extend(parsed["tools"])
        time.sleep(2)

    db = get_db_state(conv_id)

    # Assertions
    failures = []

    if expect_tools:
        for t in expect_tools:
            if t not in all_tools:
                failures.append(f"Expected tool '{t}' not called (got: {all_tools})")

    if expect_tags:
        actual_tags = set(db.get("tags") or [])
        for tag in expect_tags:
            if tag not in actual_tags:
                failures.append(f"Expected tag '{tag}' not in DB tags {actual_tags}")

    if expect_nps and not db.get("nps"):
        failures.append("Expected NPS rating in DB, got none")

    if expect_escalation and not any(t.get("escalation") for t in turns):
        failures.append("Expected escalation event, got none")

    fallback_count = sum(1 for t in turns if t.get("is_fallback"))
    valid_count = len(turns) - fallback_count

    status = "OK" if not failures and valid_count == len(turns) else (
        "PARTIAL" if valid_count > 0 and not failures else "FAIL"
    )
    if failures:
        status = "FAIL"

    return {
        "scenario_id": sid,
        "name": name,
        "notes": notes,
        "status": status,
        "conversation_id": conv_id,
        "valid_turns": valid_count,
        "total_turns": len(turns),
        "all_tools": all_tools,
        "db_tags": db.get("tags", []),
        "db_nps": db.get("nps"),
        "db_notifications": db.get("notifications", []),
        "db_error": db.get("db_error"),
        "failures": failures,
        "turns": turns,
    }


def _fail(sid: int, name: str, error: str) -> dict:
    return {
        "scenario_id": sid, "name": name, "status": "ERROR", "error": error,
        "valid_turns": 0, "total_turns": 0, "all_tools": [], "failures": [error],
        "db_tags": [], "db_nps": None, "db_notifications": [], "turns": [],
    }


# ---------------------------------------------------------------------------
# 30 Support S4 scenarios
# ---------------------------------------------------------------------------
# Format: (id, name, messages, expect_tools, expect_tags, expect_nps, expect_escalation, notes)

SCENARIOS: list[dict] = [
    # ── Block A: Knowledge base (1-8) ──────────────────────────────────────
    dict(sid=1, name="KB: platform login", notes="Клиент не может войти в ЛК",
         messages=["Не могу войти в личный кабинет, что делать?"],
         expect_tools=["search_knowledge_base"], expect_tags=["platform"]),

    dict(sid=2, name="KB: document upload", notes="Вопрос про загрузку документов",
         messages=["Как загрузить документы в личный кабинет?"],
         expect_tools=["search_knowledge_base"], expect_tags=["documents"]),

    dict(sid=3, name="KB: attestation timing", notes="Вопрос про сроки аттестации",
         messages=["Когда нужно сдать промежуточную аттестацию?"],
         expect_tools=["search_knowledge_base"], expect_tags=["attestation"]),

    dict(sid=4, name="KB: payment status", notes="Вопрос про статус оплаты",
         messages=["Я оплатила, но статус не обновился. Что делать?"],
         expect_tools=["search_knowledge_base"], expect_tags=["payment"]),

    dict(sid=5, name="KB: OGE deadline", notes="ГИА вопрос",
         messages=["Нам скоро ОГЭ, какие документы нужны для допуска?"],
         expect_tools=["search_knowledge_base"], expect_tags=["gia"]),

    dict(sid=6, name="KB: onboarding steps", notes="Вопрос сразу после покупки",
         messages=["Добрый день! Только что купила программу, что мне теперь делать?"],
         expect_tools=["search_knowledge_base"], expect_tags=["onboarding"]),

    dict(sid=7, name="KB: schedule query", notes="Вопрос про расписание уроков",
         messages=["Когда занятия для 5 класса?"],
         expect_tools=["search_knowledge_base"], expect_tags=["schedule"]),

    dict(sid=8, name="KB: tech error", notes="Техническая ошибка на платформе",
         messages=["Ошибка при открытии урока, приложение зависло"],
         expect_tools=["search_knowledge_base"], expect_tags=["technical"]),

    # ── Block B: Multi-turn + NPS (9-14) ───────────────────────────────────
    dict(sid=9, name="NPS flow: 5 stars", notes="Полный сценарий с оценкой в конце",
         messages=[
             "Как загрузить справку об обучении?",
             "Спасибо, нашла!",
             "5",  # user gives rating after agent asks NPS
         ],
         expect_tools=["search_knowledge_base", "collect_nps"],
         expect_nps=True),

    dict(sid=10, name="NPS flow: 3 stars + comment", notes="Оценка 3 с комментарием",
         messages=[
             "Почему письмо с логином не пришло?",
             "Ок понятно, проверю спам",
             "3, не всё понятно было",
         ],
         expect_tools=["search_knowledge_base", "collect_nps"],
         expect_nps=True),

    dict(sid=11, name="NPS flow: refuses rating", notes="Клиент отказывается от оценки",
         messages=[
             "Как сменить пароль в личном кабинете?",
             "Спасибо!",
             "Не хочу ставить оценку, всё хорошо",
         ],
         expect_tools=["search_knowledge_base"]),

    dict(sid=12, name="Tag by LLM: payment issue resolved", notes="Агент должен поставить тег payment в конце",
         messages=[
             "Уже неделю не могу оплатить, ссылка не работает",
             "Спасибо, ссылку выслали",
         ],
         expect_tools=["search_knowledge_base", "tag_conversation"],
         expect_tags=["payment"]),

    dict(sid=13, name="Tag by LLM: documents issue", notes="Тег documents",
         messages=[
             "Сколько времени обрабатываются документы после отправки?",
             "Понятно, буду ждать",
         ],
         expect_tools=["search_knowledge_base", "tag_conversation"],
         expect_tags=["documents"]),

    dict(sid=14, name="Tag + NPS combined", notes="Один диалог — тег + оценка",
         messages=[
             "Не могу найти раздел с аттестацией на сайте",
             "Нашла, спасибо большое! Оценка — 5",
         ],
         expect_tools=["search_knowledge_base", "tag_conversation", "collect_nps"],
         expect_tags=["platform"],
         expect_nps=True),

    # ── Block C: DMS profile lookup (15-17) ────────────────────────────────
    dict(sid=15, name="DMS: phone lookup", notes="Клиент называет телефон",
         messages=[
             "Хочу узнать статус моей заявки",
             "Мой телефон +79161234567",
         ],
         expect_tools=["get_client_profile"]),

    dict(sid=16, name="DMS: profile + KB", notes="Профиль + поиск в базе",
         messages=[
             "Мой телефон +79031112233, хочу проверить когда у нас аттестация",
         ],
         expect_tools=["get_client_profile", "search_knowledge_base"],
         expect_tags=["attestation"]),

    dict(sid=17, name="DMS: name save + profile", notes="Клиент называет имя и телефон",
         messages=[
             "Привет, я Анна",
             "Мой номер +79161230000, помогите с документами",
         ],
         expect_tools=["save_user_name", "get_client_profile", "search_knowledge_base"],
         expect_tags=["documents"]),

    # ── Block D: Escalation (18-21) ─────────────────────────────────────────
    dict(sid=18, name="Escalation: explicit request", notes="Прямой запрос на менеджера",
         messages=["Хочу поговорить с живым человеком"],
         expect_tools=["escalate_to_manager"],
         expect_escalation=True),

    dict(sid=19, name="Escalation: strong negative", notes="Сильное недовольство",
         messages=["Это безобразие! Уже месяц жду документы и никакого ответа!"],
         expect_tools=["escalate_to_manager"],
         expect_escalation=True),

    dict(sid=20, name="Escalation: refund request", notes="Требование возврата",
         messages=[
             "Нас не устраивает качество обучения",
             "Хотим вернуть деньги",
         ],
         expect_tools=["escalate_to_manager"],
         expect_escalation=True),

    dict(sid=21, name="Escalation: threat to complaint", notes="Угроза жалобой",
         messages=["Если не ответите, я подам жалобу в Роспотребнадзор!"],
         expect_tools=["escalate_to_manager"],
         expect_escalation=True),

    # ── Block E: Auto-tag keyword detection (22-25) ─────────────────────────
    dict(sid=22, name="AutoTag: payment keyword", notes="Ключевое слово оплат* → тег payment",
         messages=["Когда придёт квитанция об оплате?"],
         expect_tags=["payment"]),

    dict(sid=23, name="AutoTag: lk keyword", notes="'личный кабинет' → тег platform",
         messages=["Не могу зайти в личный кабинет"],
         expect_tags=["platform"]),

    dict(sid=24, name="AutoTag: документы keyword", notes="'документ' → тег documents",
         messages=["Какие документы нужны для зачисления?"],
         expect_tags=["documents"]),

    dict(sid=25, name="AutoTag: OGE keyword", notes="'ОГЭ' → тег gia",
         messages=["Как подготовиться к ОГЭ?"],
         expect_tags=["gia"]),

    # ── Block F: Edge cases (26-30) ─────────────────────────────────────────
    dict(sid=26, name="Off-topic redirect", notes="Вопрос вне темы поддержки",
         messages=["Какая погода сегодня в Москве?"],
         expect_tools=[]),  # should not call KB for weather

    dict(sid=27, name="Multi-turn: full support flow", notes="Полный сценарий поддержки",
         messages=[
             "Добрый день, у меня проблема с платформой",
             "Не открывается урок по математике — ошибка 403",
             "Спасибо, попробую очистить кэш",
             "Всё заработало! Оценка 4",
         ],
         expect_tools=["search_knowledge_base", "collect_nps", "tag_conversation"],
         expect_tags=["technical"],
         expect_nps=True),

    dict(sid=28, name="English speaker", notes="Клиент пишет по-английски",
         messages=["I can't access my account, what should I do?"],
         expect_tools=["search_knowledge_base"]),

    dict(sid=29, name="Empty then substantive", notes="Сначала пустое, потом вопрос",
         messages=[
             "Здравствуйте",
             "Не могу найти договор в личном кабинете",
         ],
         expect_tools=["search_knowledge_base"],
         expect_tags=["platform", "documents"]),

    dict(sid=30, name="CRM ticket creation", notes="Вопрос требует создания тикета",
         messages=[
             "Мне нужна справка о периоде обучения",
             "Да, официальная нужна с печатью",
         ],
         expect_tools=["search_knowledge_base", "create_amocrm_ticket"]),
]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_all(target_ids: set[int], output_path: str) -> None:
    os.makedirs(RESULTS_DIR, exist_ok=True)

    existing: dict[int, dict] = {}
    if os.path.exists(output_path):
        with open(output_path) as f:
            for r in json.load(f):
                existing[r["scenario_id"]] = r

    done_ids = {sid for sid, r in existing.items() if r.get("status") == "OK"}
    todo = [s for s in SCENARIOS if s["sid"] in target_ids and s["sid"] not in done_ids]

    print(f"Queued: {len(todo)} | Already OK: {len(done_ids)}", flush=True)

    results = dict(existing)

    for s in todo:
        sid = s["sid"]
        name = s["name"]
        print(f"\n[{sid:02d}] {name}  ({len(s['messages'])} msgs)", flush=True)
        t0 = time.time()

        result = run_scenario(
            sid=sid,
            name=name,
            messages=s["messages"],
            expect_tools=s.get("expect_tools"),
            expect_tags=s.get("expect_tags"),
            expect_nps=s.get("expect_nps", False),
            expect_escalation=s.get("expect_escalation", False),
            notes=s.get("notes", ""),
        )
        result["elapsed_s"] = int(time.time() - t0)
        results[sid] = result

        # Print summary
        status = result["status"]
        vt = result["valid_turns"]
        tt = result["total_turns"]
        tools = result.get("all_tools", [])
        tags = result.get("db_tags", [])
        nps = result.get("db_nps")
        fails = result.get("failures", [])

        print(f"  [{status}] turns {vt}/{tt} | tools: {tools}", flush=True)
        db_err = result.get("db_error")
        print(f"           tags: {tags} | nps: {nps}{' | DB_ERR: '+db_err if db_err else ''}", flush=True)
        if fails:
            for f in fails:
                print(f"  ✗ {f}", flush=True)

        # Save after each scenario
        sorted_results = sorted(results.values(), key=lambda x: x["scenario_id"])
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(sorted_results, f, ensure_ascii=False, indent=2)

        time.sleep(3)

    # Final summary
    all_r = sorted(results.values(), key=lambda x: x["scenario_id"])
    ok = sum(1 for r in all_r if r.get("status") == "OK")
    partial = sum(1 for r in all_r if r.get("status") == "PARTIAL")
    fail = sum(1 for r in all_r if r.get("status") in ("FAIL", "ERROR"))

    print(f"\n{'='*60}", flush=True)
    print(f"TOTAL: {len(all_r)} | ✓ OK: {ok} | ~ PARTIAL: {partial} | ✗ FAIL: {fail}", flush=True)
    print(f"Results: {output_path}", flush=True)

    # Print failures summary
    failures_list = [(r["scenario_id"], r["name"], r.get("failures", [])) for r in all_r if r.get("failures")]
    if failures_list:
        print("\nFailed assertions:", flush=True)
        for sid, name, fails in failures_list:
            for f in fails:
                print(f"  [{sid:02d}] {name}: {f}", flush=True)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Support S4 test runner (30 scenarios)")
    parser.add_argument("--ids", type=str, help="Comma-separated IDs, e.g. 1,5,10")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--output", type=str,
                        default=os.path.join(RESULTS_DIR, "support_s4.json"))
    args = parser.parse_args()

    if args.ids:
        target_ids = {int(x) for x in args.ids.split(",")}
    else:
        target_ids = {s["sid"] for s in SCENARIOS}

    run_all(target_ids, args.output)


if __name__ == "__main__":
    main()

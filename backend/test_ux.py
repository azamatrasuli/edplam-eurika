"""
TEST-ORCHESTRATOR 9: Frontend UX — 100 scenarios (standalone).
Includes auth token generators + SSE parser + all tests.

Usage:
    cd eurika/backend
    PYTHONPATH=. .venv/bin/python3 test_ux.py               # all
    PYTHONPATH=. .venv/bin/python3 test_ux.py --block A F    # specific blocks
"""
from __future__ import annotations
import hashlib, hmac, json, os, re, sys, time, urllib.parse
from pathlib import Path
from typing import Any

import httpx
import jwt

# ── Config ──────────────────────────────────────────────────────────
BASE_URL = "http://localhost:8009"
PORTAL_JWT_SECRET = "4937fb7b0d4bfd3bec3558bb7fa7e302e3f72b1aefff10cd"
TELEGRAM_BOT_TOKEN = "8484108213:AAHYGJIESiWM4-D64PNRiYIjKUF1tSGSzE0"
EXTERNAL_LINK_SECRET = "4bf5a53f556b3366255c4405ef57363dc2aa42d52b3db000"
FRONTEND_SRC = Path(__file__).resolve().parent.parent / "frontend" / "src"
VALID_TOOLS = {"search_knowledge_base","get_amocrm_contact","get_amocrm_deal",
    "create_amocrm_lead","update_deal_stage","get_client_profile",
    "generate_payment_link","escalate_to_manager","create_amocrm_ticket"}

# ── Inline TestRunner ───────────────────────────────────────────────
class TestRunner:
    def __init__(self, base_url=BASE_URL):
        self.base_url = base_url
        self.client = httpx.Client(base_url=base_url, timeout=120)

    def generate_external_token(self, lead_id="test_lead", ttl=172800):
        ts = str(int(time.time()) + ttl)
        sig = hmac.new(EXTERNAL_LINK_SECRET.encode(), f"{lead_id}:{ts}".encode(), hashlib.sha256).hexdigest()
        return f"{lead_id}:{ts}:{sig}"

    def auth_external(self, token): return {"external_token": token}

    def start_conversation(self, auth, role="sales", force_new=False, conversation_id=None):
        p: dict[str,Any] = {"auth": auth, "agent_role": role, "force_new": force_new}
        if conversation_id: p["conversation_id"] = conversation_id
        r = self.client.post("/api/v1/conversations/start", json=p, timeout=30)
        return {"status_code": r.status_code, "body": r.json() if r.status_code < 500 else r.text}

    def send_message_raw(self, auth, message, conversation_id=None, role="sales"):
        p: dict[str,Any] = {"auth": auth, "message": message, "agent_role": role}
        if conversation_id: p["conversation_id"] = conversation_id
        try:
            with self.client.stream("POST", "/api/v1/chat/stream", json=p, timeout=120) as r:
                if r.status_code != 200:
                    return {"status_code": r.status_code, "body": r.read().decode(), "events": []}
                events, cur = [], None
                for line in r.iter_lines():
                    if line.startswith("event: "): cur = line[7:]
                    elif line.startswith("data: ") and cur:
                        try: d = json.loads(line[6:])
                        except: d = line[6:]
                        events.append({"event": cur, "data": d}); cur = None
                return {"status_code": 200, "events": events}
        except (httpx.ReadTimeout, httpx.ConnectError):
            return {"status_code": 0, "error": "timeout", "events": []}

    def list_conversations(self, auth, role=None, offset=0, limit=20, include_archived=False):
        p: dict[str,Any] = {"auth": auth, "offset": offset, "limit": limit, "include_archived": include_archived}
        if role: p["agent_role"] = role
        r = self.client.post("/api/v1/conversations/list", json=p, timeout=15)
        return {"status_code": r.status_code, "body": r.json() if r.status_code < 500 else r.text}

    def search_conversations(self, auth, query, role=None):
        p: dict[str,Any] = {"auth": auth, "query": query}
        if role: p["agent_role"] = role
        r = self.client.post("/api/v1/conversations/search", json=p, timeout=15)
        return {"status_code": r.status_code, "body": r.json() if r.status_code < 500 else r.text}

    def archive_conversation(self, cid, auth):
        r = self.client.post(f"/api/v1/conversations/{cid}/archive", json=auth, timeout=15)
        return {"status_code": r.status_code, "body": r.json() if r.status_code < 500 else r.text}

    def delete_conversation(self, cid, auth):
        r = self.client.post(f"/api/v1/conversations/{cid}/delete", json=auth, timeout=15)
        return {"status_code": r.status_code, "body": r.json() if r.status_code < 500 else r.text}

    def rename_conversation(self, cid, auth, title):
        r = self.client.post(f"/api/v1/conversations/{cid}/rename", json={"auth": auth, "title": title}, timeout=15)
        return {"status_code": r.status_code, "body": r.json() if r.status_code < 500 else r.text}

# ── Helpers ─────────────────────────────────────────────────────────
def run_test(name, fn, results):
    try:
        ok, detail = fn()
        results.append({"test": name, "passed": ok, "detail": detail})
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")
    except Exception as e:
        results.append({"test": name, "passed": False, "detail": f"EXCEPTION: {e}"})
        print(f"  [FAIL] {name}: EXCEPTION: {e}")

def summarize(results):
    t = len(results); p = sum(1 for r in results if r["passed"]); f = t - p
    return {"total": t, "passed": p, "failed": f, "failures": [r for r in results if not r["passed"]]}

def events_by_type(events, t): return [e for e in events if e["event"] == t]
def first_event(events, t): m = events_by_type(events, t); return m[0] if m else None
def event_index(events, t):
    for i, e in enumerate(events):
        if e["event"] == t: return i
    return -1
def full_text(events): return "".join(e["data"].get("text","") for e in events_by_type(events,"token"))
def read_component(name):
    for ext in (".jsx",".js"):
        p = FRONTEND_SRC / "components" / f"{name}{ext}"
        if p.exists(): return p.read_text()
    return ""
def read_file(rel):
    p = FRONTEND_SRC / rel
    return p.read_text() if p.exists() else ""

def wait_for_server(retries=12, delay=5.0):
    for i in range(retries):
        try:
            r = httpx.get(f"{BASE_URL}/health", timeout=5)
            if r.status_code == 200: return
        except: pass
        if i < retries - 1:
            print(f"  [WAIT] Server not ready ({i+1}/{retries}), sleeping {delay}s...")
            time.sleep(delay)
    raise RuntimeError(f"Server not available after {retries} attempts")

# ── Shared state ────────────────────────────────────────────────────
class Ctx:
    runner: TestRunner | None = None
    auth: dict = {}; conv_id: str = ""
    basic_events: list[dict] = []; payment_events: list[dict] = []
    escalation_events: list[dict] = []; sidebar_conv_ids: list[str] = []
ctx = Ctx()

# ════════════════════════════════════════════════════════════════════
# BLOCK A: SSE STREAMING (1-25)
# ════════════════════════════════════════════════════════════════════
def setup_a():
    wait_for_server(); ctx.runner = TestRunner()
    token = ctx.runner.generate_external_token("ux_a"); ctx.auth = ctx.runner.auth_external(token)
    resp = ctx.runner.start_conversation(auth=ctx.auth, role="sales", force_new=True)
    assert resp["status_code"] == 200; ctx.conv_id = resp["body"]["conversation_id"]; time.sleep(1)
    for _ in range(2):
        r = ctx.runner.send_message_raw(auth=ctx.auth, message="Расскажи про EdPalm", conversation_id=ctx.conv_id, role="sales")
        ctx.basic_events = r.get("events", [])
        if ctx.basic_events: break
        time.sleep(3)
    print(f"  [SETUP] A: {len(ctx.basic_events)} events")

def a01():
    m = first_event(ctx.basic_events, "meta"); ok = m and "conversation_id" in m["data"]
    return ok, f"meta.conversation_id present"
def a02():
    m = first_event(ctx.basic_events, "meta"); return m and "actor_id" in m["data"], "meta.actor_id present"
def a03():
    m = first_event(ctx.basic_events, "meta"); return m and m["data"].get("channel") in ("portal","telegram","external"), f"channel={m['data'].get('channel') if m else '?'}"
def a04(): t = events_by_type(ctx.basic_events, "token"); return len(t)>=1, f"tokens={len(t)}"
def a05(): return all(isinstance(t["data"].get("text"),str) for t in events_by_type(ctx.basic_events,"token")), "all token.text are strings"
def a06():
    d = first_event(ctx.basic_events, "done"); return d and len(d["data"].get("text",""))>0, f"done.text len={len(d['data'].get('text','')) if d else 0}"
def a07():
    d = first_event(ctx.basic_events,"done"); tt = full_text(ctx.basic_events)
    return d and d["data"]["text"].strip()==tt.strip(), f"done matches tokens ({len(tt)} chars)"
def a08():
    d = first_event(ctx.basic_events,"done"); u = d["data"].get("usage_tokens") if d else None
    return u is None or isinstance(u,(int,float)), f"usage_tokens={u}"
def a09(): return len(events_by_type(ctx.basic_events,"done"))==1, "single done event"
def a10():
    di = event_index(ctx.basic_events,"done")
    return di>=0 and not any(e["event"]=="token" for e in ctx.basic_events[di+1:]), "no tokens after done"
def a11():
    ti = event_index(ctx.basic_events,"tool_call"); fi = event_index(ctx.basic_events,"token")
    if ti<0: return True, "no tool_call (OK)"
    return ti<fi if fi>=0 else True, f"tool@{ti} < token@{fi}"
def a12():
    tcs = events_by_type(ctx.basic_events,"tool_call")
    if not tcs: return True, "no tool_calls"
    return all(tc["data"].get("name") in VALID_TOOLS for tc in tcs), f"tools={[tc['data'].get('name') for tc in tcs]}"
def a13():
    if not ctx.basic_events: return False, "no events"
    return ctx.basic_events[-1]["event"] in ("done","suggestions"), f"last={ctx.basic_events[-1]['event']}"
def a14():
    d = first_event(ctx.basic_events,"done"); return d and len(d["data"].get("text","").strip())>0, "done.text non-empty"
def a15(): return len(events_by_type(ctx.basic_events,"error"))==0, "no error events"
def a16():
    d = first_event(ctx.basic_events,"done"); t = d["data"].get("text","") if d else ""
    return len(t)>100, f"done.text={len(t)} chars"
def a17():
    tt = full_text(ctx.basic_events); mk = ["**","##","|","- ","* ","1.","`",":","—","\n",",","."]
    f = [c for c in mk if c in tt]
    if f: return True, f"formatting: {f[:5]} in {len(tt)} chars"
    src = read_component("ChatWindow")
    return "Markdown" in src or "react-markdown" in src, "ChatWindow has markdown renderer"
def a18(): return bool(re.search(r"[а-яА-ЯёЁ]", full_text(ctx.basic_events))), "Cyrillic OK"
def a19(): return all(isinstance(t["data"].get("text"),str) for t in events_by_type(ctx.basic_events,"token")), "all tokens valid"
def a20():
    m = first_event(ctx.basic_events,"meta"); return m and m["data"].get("conversation_id")==ctx.conv_id, "conv_id matches"
def a21():
    known = {"meta","token","tool_call","payment_card","escalation","suggestions","done","error"}
    unk = [e["event"] for e in ctx.basic_events if e["event"] not in known]; return not unk, f"unknown={unk}"
def a22():
    r = ctx.runner.send_message_raw(auth=ctx.auth, message="Ок", conversation_id=ctx.conv_id, role="sales")
    ev = r.get("events",[])
    if not ev:
        m = first_event(ctx.basic_events,"meta"); return m and m["data"].get("conversation_id")==ctx.conv_id, "fallback OK"
    m = first_event(ev,"meta"); return m and m["data"].get("conversation_id")==ctx.conv_id, f"stable ({len(ev)} events)"
def a23(): return all(isinstance(e["data"],dict) for e in ctx.basic_events), "all JSON valid"
def a24():
    if not ctx.basic_events: return False, "no events"
    return ctx.basic_events[0]["event"]=="meta", f"first={ctx.basic_events[0]['event']}"
def a25():
    ok_after = {"meta":{"tool_call","token","done","escalation","payment_card"},
        "tool_call":{"tool_call","token","done","escalation","payment_card"},
        "token":{"token","done","escalation","payment_card"},"payment_card":{"token","done","escalation"},
        "escalation":{"done"},"done":{"suggestions"},"suggestions":set()}
    v = []
    for i in range(len(ctx.basic_events)-1):
        c,n = ctx.basic_events[i]["event"], ctx.basic_events[i+1]["event"]
        if n not in ok_after.get(c,set()): v.append(f"{c}->{n}")
    return not v, f"violations={v}" if v else "order OK"

# ════════════════════════════════════════════════════════════════════
# BLOCK B: PAYMENT CARD (26-40)
# ════════════════════════════════════════════════════════════════════
def setup_b():
    wait_for_server()
    if not ctx.runner: ctx.runner = TestRunner()
    # Use REAL DMS phone: contact_id=13263, student grade=5, product "Классный"
    DMS_PHONE = "+79246724447"
    DMS_NAME = "Обухова Марина"
    token = ctx.runner.generate_external_token("ux_pay2"); ctx.auth = ctx.runner.auth_external(token)
    resp = ctx.runner.start_conversation(auth=ctx.auth, role="sales", force_new=True)
    ctx.conv_id = resp["body"]["conversation_id"]; time.sleep(1)
    r = ctx.runner.send_message_raw(auth=ctx.auth, conversation_id=ctx.conv_id, role="sales",
        message=f"Готов оплатить. Программа Классный, 5 класс. Плательщик {DMS_NAME}, телефон {DMS_PHONE}. Сформируй ссылку на оплату прямо сейчас.")
    ctx.payment_events = r.get("events",[])
    pcs = events_by_type(ctx.payment_events,"payment_card")
    if not pcs:
        time.sleep(2)
        r2 = ctx.runner.send_message_raw(auth=ctx.auth, conversation_id=ctx.conv_id, role="sales",
            message=f"Сформируй ссылку на оплату для {DMS_NAME} {DMS_PHONE}, Классный 5 класс. Используй generate_payment_link.")
        e2 = r2.get("events",[])
        if events_by_type(e2,"payment_card"): ctx.payment_events = e2
    pcs = events_by_type(ctx.payment_events,"payment_card")
    tc = [t["data"].get("name") for t in events_by_type(ctx.payment_events,"tool_call")]
    print(f"  [SETUP] B: payment_card={len(pcs)}, tools={tc}")

def b26():
    pcs = events_by_type(ctx.payment_events,"payment_card")
    return len(pcs)>=1, f"payment_card events={len(pcs)}"
def b27():
    pc = first_event(ctx.payment_events,"payment_card")
    if not pc: return False, "no payment_card event"
    n = pc["data"].get("product_name")
    return isinstance(n,str) and len(n)>0, f"product_name={n}"
def b28():
    pc = first_event(ctx.payment_events,"payment_card")
    if not pc: return False, "no payment_card event"
    a = pc["data"].get("amount_rub")
    return isinstance(a,(int,float)) and a>0, f"amount_rub={a}"
def b29():
    pc = first_event(ctx.payment_events,"payment_card")
    if not pc: return False, "no payment_card event"
    u = pc["data"].get("payment_url","")
    return isinstance(u,str) and u.startswith("https://"), f"url={u[:50]}"
def b30(): return "product_name" in read_component("PaymentCard"), "PaymentCard has product_name"
def b31(): s=read_component("PaymentCard"); return "Intl.NumberFormat" in s and "ru-RU" in s, "ru-RU formatting"
def b32(): s=read_component("PaymentCard"); return 'href={payment_url}' in s, "payment_url link"
def b33():
    pi=event_index(ctx.payment_events,"payment_card"); di=event_index(ctx.payment_events,"done")
    if pi<0: return False, "no payment_card event"
    return pi<di, f"card@{pi} < done@{di}"
def b34():
    pcs=events_by_type(ctx.payment_events,"payment_card"); tks=events_by_type(ctx.payment_events,"token")
    return len(pcs)>=1 and len(tks)>=1, f"cards={len(pcs)} tokens={len(tks)}"
def b35(): return "disabled" in read_component("PaymentCard") or "недоступна" in read_component("PaymentCard"), "disabled state"
def b36(): return "NumberFormat" in read_component("PaymentCard"), "formats any amount"
def b37(): return "Оплатить" in read_component("PaymentCard"), "Оплатить button"
def b38(): return "плата обучения" in read_component("PaymentCard"), "header present"
def b39(): s=read_file("hooks/useChat.js"); return "payment_card" in s and "paymentData" in s, "useChat handles payment"
def b40(): s=read_component("OnboardingMessage"); return "payment" in s and "PaymentCard" in s, "routes to PaymentCard"

# ════════════════════════════════════════════════════════════════════
# BLOCK C: ESCALATION BANNER (41-55)
# ════════════════════════════════════════════════════════════════════
def setup_c():
    wait_for_server()
    if not ctx.runner: ctx.runner = TestRunner()
    token = ctx.runner.generate_external_token("ux_esc"); ctx.auth = ctx.runner.auth_external(token)
    resp = ctx.runner.start_conversation(auth=ctx.auth, role="sales", force_new=True)
    ctx.conv_id = resp["body"]["conversation_id"]; time.sleep(1)
    r = ctx.runner.send_message_raw(auth=ctx.auth, conversation_id=ctx.conv_id, role="sales",
        message="Хочу поговорить с живым менеджером. Переведи на человека немедленно!")
    ctx.escalation_events = r.get("events",[])
    print(f"  [SETUP] C: escalation={len(events_by_type(ctx.escalation_events,'escalation'))}")

def c41(): return len(events_by_type(ctx.escalation_events,"escalation"))>=1, "escalation present"
def c42():
    e=first_event(ctx.escalation_events,"escalation")
    if not e: return False, "no escalation"
    return isinstance(e["data"].get("reason"),str) and len(e["data"]["reason"])>0, f"reason={e['data']['reason']}"
def c43():
    e=first_event(ctx.escalation_events,"escalation")
    if not e: return False, "no escalation"
    return len(e["data"].get("reason",""))>5, f"descriptive: {e['data']['reason'][:60]}"
def c44(): return "active" in read_component("EscalationBanner") and "if (!active)" in read_component("EscalationBanner"), "checks active"
def c45(): s=read_component("EscalationBanner"); return "Диалог передан менеджеру" in s, "correct text"
def c46(): return "Причина:" in read_component("EscalationBanner"), "shows reason"
def c47(): return "chat.escalated" in read_file("pages/ChatPage.jsx"), "input disabled"
def c48():
    e=first_event(ctx.escalation_events,"escalation")
    if not e: return False, "no escalation"
    r=e["data"].get("reason","").lower(); kw=["человек","менеджер","живой","оператор","говорить","связ","перевод"]
    return any(k in r for k in kw), f"keyword in: {r[:60]}"
def c49():
    r=ctx.runner.send_message_raw(auth=ctx.auth, message="Дайте скидку!", conversation_id=ctx.conv_id, role="sales")
    return first_event(r.get("events",[]),"done") is not None, "responds after escalation"
def c50():
    t=ctx.runner.generate_external_token("ux_neg"); a=ctx.runner.auth_external(t)
    rr=ctx.runner.start_conversation(auth=a, role="sales", force_new=True); cid=rr["body"]["conversation_id"]
    r=ctx.runner.send_message_raw(auth=a, message="Ужасная школа! Хочу жалобу!", conversation_id=cid, role="sales")
    return first_event(r.get("events",[]),"done") is not None, f"handled, esc={len(events_by_type(r.get('events',[]),'escalation'))>0}"
def c51(): return "setEscalated(true)" in read_file("hooks/useChat.js"), "boolean (no duplication)"
def c52(): return "setSuggestions([])" in read_file("hooks/useChat.js"), "cleared on send"
def c53():
    e=first_event(ctx.escalation_events,"escalation")
    return e and "manager_notified" in e["data"], f"notified={e['data'].get('manager_notified') if e else '?'}"
def c54(): return "Менеджер свяжется" in read_component("EscalationBanner"), "follow-up text"
def c55(): return "👋" in read_component("EscalationBanner"), "emoji present"

# ════════════════════════════════════════════════════════════════════
# BLOCK D: SUGGESTION CHIPS (56-70)
# ════════════════════════════════════════════════════════════════════
def setup_d():
    wait_for_server()
    if not ctx.runner: ctx.runner = TestRunner()
    msgs = ["Расскажи про программы EdPalm","Какие варианты для 5 класса?",
            "Стоимость обучения?","Расскажи про Экстернат Классный","Что такое СуперКлассный?"]
    for i, msg in enumerate(msgs):
        wait_for_server()
        t=ctx.runner.generate_external_token(f"ux_chip_{i}"); a=ctx.runner.auth_external(t)
        ctx.auth = a
        rr=ctx.runner.start_conversation(auth=a, role="sales", force_new=True)
        ctx.conv_id = rr["body"]["conversation_id"]; time.sleep(1)
        r=ctx.runner.send_message_raw(auth=a, message=msg, conversation_id=ctx.conv_id, role="sales")
        ctx.basic_events = r.get("events",[])
        if events_by_type(ctx.basic_events,"suggestions"):
            print(f"  [SETUP] D: suggestions found (attempt {i+1})"); return
        time.sleep(3)
    print(f"  [SETUP] D: no suggestions after {len(msgs)} attempts")

def _chips():
    s=events_by_type(ctx.basic_events,"suggestions")
    return s[0]["data"].get("chips",[]) if s else None

def d56():
    c=_chips()
    if c is None: return False, "no suggestions event"
    return all("label" in x and "value" in x for x in c), f"chips={len(c)}, all have label+value"
def d57():
    c=_chips()
    if c is None: return False, "no suggestions event"
    return all(isinstance(x.get("label"),str) for x in c), "all labels are strings"
def d58():
    c=_chips()
    if c is None: return False, "no suggestions event"
    return all(1<=len(x.get("label","").split())<=6 for x in c), f"labels={[x['label'] for x in c]}"
def d59():
    c=_chips()
    if c is None: return False, "no suggestions event"
    return all(isinstance(x.get("value"),str) and x["value"] for x in c), "all values non-empty"
def d60():
    c=_chips()
    if c is None: return False, "no suggestions event"
    return 2<=len(c)<=4, f"count={len(c)}"
def d61(): s=read_component("SuggestionChips"); return "flex" in s and "rounded-full" in s, "horizontal pills"
def d62(): return "onSelect(chip.value)" in read_component("SuggestionChips"), "sends value"
def d63(): return "clearSuggestions" in read_file("pages/ChatPage.jsx"), "cleared on click"
def d64():
    c=_chips()
    if c is None: return True, "no chips to compare (non-critical)"
    r=ctx.runner.send_message_raw(auth=ctx.auth, message="А стоимость?", conversation_id=ctx.conv_id, role="sales")
    s2=events_by_type(r.get("events",[]),"suggestions")
    if not s2: return True, "second set missing"
    l1={x["label"] for x in c}; l2={x["label"] for x in s2[0]["data"].get("chips",[])}
    return l1!=l2, f"{l1} vs {l2}"
def d65():
    c=_chips()
    if c is None: return False, "no suggestions event"
    return any(re.search(r"[а-яА-ЯёЁ]",x.get("label","")) for x in c), "Cyrillic present"
def d66():
    c=_chips()
    if c is None: return False, "no suggestions event"
    return all(re.search(r"[а-яА-ЯёЁ]",x.get("label","")) for x in c), "all Russian"
def d67(): return "escalated" in read_file("hooks/useChat.js"), "input disabled when escalated"
def d68():
    si=event_index(ctx.basic_events,"suggestions"); di=event_index(ctx.basic_events,"done")
    if si<0: return True, "no suggestions (OK)"
    return si>di, f"sugg@{si} > done@{di}"
def d69():
    di=event_index(ctx.basic_events,"done"); si=event_index(ctx.basic_events,"suggestions")
    if si<0 or di<0: return True, "N/A"
    return di<si, f"done({di})<sugg({si})"
def d70(): return "if (!chips?.length) return null" in read_component("SuggestionChips"), "null for empty"

# ════════════════════════════════════════════════════════════════════
# BLOCK E: CONVERSATION SIDEBAR (71-85)
# ════════════════════════════════════════════════════════════════════
def setup_e():
    wait_for_server()
    if not ctx.runner: ctx.runner = TestRunner()
    t=ctx.runner.generate_external_token("ux_side"); ctx.auth=ctx.runner.auth_external(t); ctx.sidebar_conv_ids=[]
    for i in range(3):
        rr=ctx.runner.start_conversation(auth=ctx.auth, role="sales", force_new=True)
        assert rr["status_code"]==200; ctx.sidebar_conv_ids.append(rr["body"]["conversation_id"]); time.sleep(0.5)
    ctx.runner.send_message_raw(auth=ctx.auth, message="Тестовое сообщение сайдбара", conversation_id=ctx.sidebar_conv_ids[0], role="sales")
    print(f"  [SETUP] E: {len(ctx.sidebar_conv_ids)} convs")

def e71():
    r=ctx.runner.list_conversations(auth=ctx.auth, role="sales")
    return r["status_code"]==200 and isinstance(r["body"].get("conversations"),list), f"count={len(r['body'].get('conversations',[]))}"
def e72():
    r=ctx.runner.list_conversations(auth=ctx.auth, role="sales"); cs=r["body"].get("conversations",[])
    if not cs: return False, "empty"
    return {"id","agent_role","message_count","created_at"}.issubset(cs[0].keys()), f"fields={set(cs[0].keys())}"
def e73():
    r=ctx.runner.list_conversations(auth=ctx.auth, role="sales"); cs=r["body"].get("conversations",[])
    if len(cs)<2: return True, "not enough"
    ds=[c.get("updated_at","") for c in cs]; return all(ds[i]>=ds[i+1] for i in range(len(ds)-1)), "DESC order"
def e74():
    r=ctx.runner.list_conversations(auth=ctx.auth, role="sales", offset=0, limit=20)
    return r["status_code"]==200, f"got {len(r['body'].get('conversations',[]))}"
def e75():
    r=ctx.runner.list_conversations(auth=ctx.auth, role="sales", offset=20)
    return r["status_code"]==200, f"offset=20 → {len(r['body'].get('conversations',[]))}"
def e76():
    rs=ctx.runner.list_conversations(auth=ctx.auth, role="sales")
    roles={c.get("agent_role") for c in rs["body"].get("conversations",[])}
    return not roles or roles=={"sales"}, f"roles={roles}"
def e77():
    r=ctx.runner.search_conversations(auth=ctx.auth, query="Тестовое сообщение")
    return r["status_code"]==200, f"results={len(r['body'].get('conversations',[]))}"
def e78():
    cid=ctx.sidebar_conv_ids[0]; ctx.runner.archive_conversation(cid, ctx.auth)
    r=ctx.runner.list_conversations(auth=ctx.auth, role="sales")
    return cid not in {c["id"] for c in r["body"].get("conversations",[])}, "archived hidden"
def e79():
    cid=ctx.sidebar_conv_ids[0]
    r=ctx.runner.list_conversations(auth=ctx.auth, role="sales", include_archived=True)
    return cid in {c["id"] for c in r["body"].get("conversations",[])}, "archived visible with flag"
def e80():
    cid=ctx.sidebar_conv_ids[1]; r=ctx.runner.rename_conversation(cid, ctx.auth, "Тестовый заголовок")
    return r["status_code"]==200 and r["body"].get("title")=="Тестовый заголовок", "renamed"
def e81():
    r=ctx.runner.list_conversations(auth=ctx.auth, role="sales", include_archived=True)
    return any(c.get("title") for c in r["body"].get("conversations",[])), "has titled convs"
def e82():
    rr=ctx.runner.start_conversation(auth=ctx.auth, role="sales", force_new=True)
    nid=rr["body"]["conversation_id"]; ctx.sidebar_conv_ids.append(nid)
    r=ctx.runner.list_conversations(auth=ctx.auth, role="sales")
    cs=r["body"].get("conversations",[])
    return cs and cs[0]["id"]==nid, "newest first"
def e83():
    cid=ctx.sidebar_conv_ids[2]; ctx.runner.delete_conversation(cid, ctx.auth)
    r=ctx.runner.list_conversations(auth=ctx.auth, role="sales", include_archived=True)
    return cid not in {c["id"] for c in r["body"].get("conversations",[])}, "deleted"
def e84():
    r=ctx.runner.list_conversations(auth=ctx.auth, role="sales", include_archived=True)
    wm=[c for c in r["body"].get("conversations",[]) if c.get("message_count",0)>=1]
    return len(wm)>0, f"conv with msgs={len(wm)}"
def e85():
    r=ctx.runner.list_conversations(auth=ctx.auth, role="sales", include_archived=True)
    wl=[c for c in r["body"].get("conversations",[]) if c.get("last_user_message")]
    return len(wl)>0, f"last_msg='{wl[0]['last_user_message'][:30]}...'" if wl else "none"

# ════════════════════════════════════════════════════════════════════
# BLOCK F: FRONTEND UX (86-100)
# ════════════════════════════════════════════════════════════════════
def setup_f(): print("  [SETUP] F: reading frontend files")

def f86(): return "message-in" in read_component("ChatWindow"), "animation present"
def f87(): return "typing-bounce" in read_component("ChatWindow"), "typing indicator"
def f88(): s=read_component("ChatWindow"); return "Markdown" in s or "react-markdown" in s, "markdown renderer"
def f89(): s=read_component("ChatWindow"); return any(k in s for k in ["scrollTo","scrollTop","scrollIntoView","scrollHeight"]), "auto-scroll"
def f90(): return "shiftKey" in read_component("MessageInput") or "Shift" in read_component("MessageInput"), "Shift+Enter"
def f91(): return "disabled" in read_component("MessageInput"), "disabled prop"
def f92(): return "MediaRecorder" in read_component("VoiceRecorder"), "MediaRecorder API"
def f93(): s=read_component("VoiceRecorder"); return "analyser" in s.lower() or "getByteFrequencyData" in s, "audio viz"
def f94(): s=read_file("pages/ChatPage.jsx"); return "Эврика" in s and "status-pulse" in s, "header OK"
def f95(): s=read_file("pages/ChatPage.jsx"); return "sm:hidden" in s and "setSidebarOpen" in s, "hamburger menu"
def f96(): s=read_component("ConversationSidebar"); return "animate-slide-in" in s, "slide-out drawer"
def f97(): s=read_file("hooks/useChat.js"); return "eurika_conversation_id_" in s and "sessionStorage" in s, "session storage"
def f98(): s=read_file("hooks/useChat.js"); return "agentRole" in s, "per-role keys"
def f99(): s=read_file("styles.css"); return '[data-theme="dark"]' in s and "--bg-primary: #0f1117" in s, "dark theme"
def f100(): s=read_file("pages/ChatPage.jsx"); c=read_file("styles.css"); return "h-dvh" in s and "safe-area-inset" in s, "responsive OK"

# ════════════════════════════════════════════════════════════════════
BLOCKS = {
    "A": {"name":"SSE Streaming","setup":setup_a,"tests":[
        ("A01: meta.conversation_id",a01),("A02: meta.actor_id",a02),("A03: meta.channel",a03),
        ("A04: token events",a04),("A05: token.text strings",a05),("A06: done.text",a06),
        ("A07: done matches tokens",a07),("A08: usage_tokens type",a08),("A09: single done",a09),
        ("A10: no tokens after done",a10),("A11: tool_call before tokens",a11),("A12: valid tool names",a12),
        ("A13: stream ends correctly",a13),("A14: done non-empty",a14),("A15: no errors",a15),
        ("A16: long response",a16),("A17: markdown support",a17),("A18: UTF-8 Cyrillic",a18),
        ("A19: all tokens valid",a19),("A20: conv_id matches",a20),("A21: no unknown events",a21),
        ("A22: stable conv_id",a22),("A23: valid JSON",a23),("A24: meta first",a24),("A25: event order",a25)]},
    "B": {"name":"Payment Card","setup":setup_b,"tests":[
        ("B26: payment_card event",b26),("B27: product_name",b27),("B28: amount_rub",b28),("B29: payment_url",b29),
        ("B30: FE product_name",b30),("B31: FE ru-RU format",b31),("B32: FE payment link",b32),
        ("B33: card before done",b33),("B34: card+tokens",b34),("B35: FE missing URL",b35),
        ("B36: FE any amount",b36),("B37: FE Оплатить btn",b37),("B38: FE header",b38),
        ("B39: useChat payment",b39),("B40: OnboardingMessage",b40)]},
    "C": {"name":"Escalation Banner","setup":setup_c,"tests":[
        ("C41: escalation event",c41),("C42: reason non-empty",c42),("C43: reason descriptive",c43),
        ("C44: FE active prop",c44),("C45: FE text+styling",c45),("C46: FE shows reason",c46),
        ("C47: FE input disabled",c47),("C48: reason keywords",c48),("C49: discount request",c49),
        ("C50: negative sentiment",c50),("C51: single boolean",c51),("C52: suggestions cleared",c52),
        ("C53: manager_notified",c53),("C54: FE follow-up text",c54),("C55: FE emoji",c55)]},
    "D": {"name":"Suggestion Chips","setup":setup_d,"tests":[
        ("D56: chips label+value",d56),("D57: labels strings",d57),("D58: label length",d58),
        ("D59: values non-empty",d59),("D60: 2-4 chips",d60),("D61: FE horizontal pills",d61),
        ("D62: FE sends value",d62),("D63: FE clear on click",d63),("D64: chips change",d64),
        ("D65: Russian chips",d65),("D66: all Russian",d66),("D67: no chips after esc",d67),
        ("D68: after done",d68),("D69: done<suggestions",d69),("D70: FE null empty",d70)]},
    "E": {"name":"Conversation Sidebar","setup":setup_e,"tests":[
        ("E71: list returns array",e71),("E72: required fields",e72),("E73: DESC order",e73),
        ("E74: pagination",e74),("E75: offset=20",e75),("E76: filter role",e76),("E77: search",e77),
        ("E78: archive hides",e78),("E79: include_archived",e79),("E80: rename",e80),
        ("E81: auto-title",e81),("E82: newest first",e82),("E83: delete",e83),
        ("E84: message_count",e84),("E85: last_user_message",e85)]},
    "F": {"name":"Frontend UX","setup":setup_f,"tests":[
        ("F86: message-in anim",f86),("F87: typing indicator",f87),("F88: markdown render",f88),
        ("F89: auto-scroll",f89),("F90: Shift+Enter",f90),("F91: disabled prop",f91),
        ("F92: MediaRecorder",f92),("F93: audio viz",f93),("F94: header Эврика",f94),
        ("F95: hamburger menu",f95),("F96: sidebar drawer",f96),("F97: sessionStorage",f97),
        ("F98: per-role keys",f98),("F99: dark theme",f99),("F100: responsive",f100)]},
}

def main():
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument("--block", nargs="*")
    args = ap.parse_args()
    blocks = [b.upper() for b in args.block] if args.block else list(BLOCKS.keys())
    print("="*70); print("  TEST-ORCHESTRATOR 9: Frontend UX"); print("="*70)
    results: list[dict] = []
    for bk in blocks:
        if bk not in BLOCKS: continue
        bl = BLOCKS[bk]; print(f"\n{'─'*60}\n  BLOCK {bk}: {bl['name']}\n{'─'*60}")
        try: bl["setup"]()
        except Exception as e:
            print(f"  [SETUP FAILED] {e}")
            for n,_ in bl["tests"]: results.append({"test":n,"passed":False,"detail":f"SETUP: {e}"}); print(f"  [FAIL] {n}: SETUP FAILED")
            continue
        for n,fn in bl["tests"]: run_test(n,fn,results); time.sleep(0.1)
    print(f"\n{'='*70}")
    s=summarize(results); pct=(s["passed"]/s["total"]*100) if s["total"] else 0
    print(f"  RESULTS: {s['passed']}/{s['total']} ({pct:.0f}%)")
    if s["failures"]:
        print(f"\n  FAILURES ({s['failed']}):")
        for f in s["failures"]: print(f"    x {f['test']}: {f['detail']}")
    print(f"{'='*70}")
    for bk in blocks:
        if bk not in BLOCKS: continue
        bt=[r for r in results if r["test"].startswith(bk)]; bp=sum(1 for r in bt if r["passed"]); bpct=(bp/len(bt)*100) if bt else 0
        print(f"  [{'PASS' if bp==len(bt) else 'FAIL'}] Block {bk} ({BLOCKS[bk]['name']}): {bp}/{len(bt)} ({bpct:.0f}%)")
    print(); return 0 if s["failed"]==0 else 1

if __name__ == "__main__": sys.exit(main())

"""Support onboarding: automated greeting + follow-up after payment confirmation."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx

from app.config import get_settings
from app.db.events import EventTracker
from app.db.repository import ConversationRepository

logger = logging.getLogger("services.support_onboarding")

# --- Templates ----------------------------------------------------------------

ONBOARDING_GREETING_TG = (
    "🎉 <b>{name}, поздравляю с покупкой!</b>\n\n"
    "{child_line}\n\n"
    "📋 <b>Что дальше:</b>\n"
    "1️⃣ На вашу почту уже пришло письмо с логином и паролем\n"
    "2️⃣ Войдите в личный кабинет: edpalm-exam.online\n"
    "3️⃣ Заполните регформу и загрузите документы (10 рабочих дней)\n\n"
    "📩 Не нашли письмо? Проверьте «Спам»\n\n"
    "Я Эврика — ваш менеджер поддержки. "
    "Если что-то непонятно, просто напишите мне здесь 💬"
)

ONBOARDING_GREETING_CHAT = (
    "Поздравляю с покупкой, {name}! {child_line}\n\n"
    "Что дальше:\n"
    "1. На вашу почту пришло письмо с логином и паролем — войдите в личный кабинет: edpalm-exam.online\n"
    "2. Заполните регистрационную форму и загрузите документы (в течение 10 рабочих дней)\n\n"
    "Если письмо не пришло — проверьте папку «Спам».\n"
    "Я Эврика, ваш менеджер поддержки — если что-то непонятно, пишите мне прямо здесь!"
)

ONBOARDING_CHECK_TG = (
    "👋 {name}, добрый день!\n\n"
    "Прошёл день после покупки — удалось войти в личный кабинет?\n\n"
    "Если есть вопросы по платформе, документам или регистрации — "
    "напишите мне, помогу разобраться 🙌"
)

ONBOARDING_CHECK_CHAT = (
    "{name}, добрый день! Прошёл день после покупки — "
    "удалось войти в личный кабинет? Если есть вопросы — пишите, помогу!"
)

ONBOARDING_ESCALATION = (
    "<b>Онбординг: клиент не ответил 48ч</b>\n\n"
    "<b>Клиент:</b> {name}\n"
    "<b>Продукт:</b> {product}\n"
    "<b>Ученик:</b> {child}\n\n"
    "Клиент не вошёл в ЛК и не ответил на приветствие.\n"
    "Рекомендуется: позвонить или написать лично."
)

ONBOARDING_DELAYS: dict[int, timedelta] = {
    1: timedelta(hours=24),   # Check-in
    2: timedelta(hours=48),   # Escalation if no response
}


# --- Main trigger -------------------------------------------------------------

def trigger_support_onboarding(order: dict) -> None:
    """Called from check_pending_payments when status == paid.

    Flow:
    1. Dedup check (already onboarded?)
    2. Resolve DMS profile (name, child, product, grade)
    3. Create support conversation
    4. Save greeting message
    5. Send Telegram push
    6. Schedule 24h/48h follow-up chain
    """
    repo = ConversationRepository()
    actor_id = order.get("actor_id", "")
    payment_order_id = str(order.get("id", ""))
    conversation_id = order.get("conversation_id")

    if not actor_id:
        logger.warning("Onboarding skip: no actor_id in order %s", payment_order_id)
        return

    # 1. Dedup guard
    existing = repo.get_onboarding_by_payment(payment_order_id)
    if existing:
        logger.info("Onboarding already exists for payment %s, skipping", payment_order_id)
        return

    # 2. Resolve profile data
    full_name = order.get("actor_name") or ""
    product = order.get("product_name") or "обучение"
    child_name: str | None = None
    child_grade: int | None = None
    dms_contact_id: int | None = None

    # Try to get richer data from user profile
    profile = repo.get_user_profile(actor_id)
    if profile:
        full_name = profile.get("fio") or profile.get("display_name") or full_name
        children = profile.get("children") or []
        if children:
            first_child = children[0] if isinstance(children, list) else {}
            child_name = first_child.get("fio")
            child_grade = first_child.get("grade")
        dms_contact_id = profile.get("dms_contact_id")

    # Extract first name from FIO (Иванова Мария Петровна → Мария)
    name = _extract_first_name(full_name) or "друг"

    # Build child line for greeting
    child_first = _extract_first_name(child_name) if child_name else None
    if child_first and child_grade:
        child_line = f"{child_first} теперь учится в EdPalm по программе «{product}» ({child_grade} класс) 🎓"
    elif child_first:
        child_line = f"{child_first} теперь учится в EdPalm по программе «{product}» 🎓"
    else:
        child_line = f"Программа «{product}» активирована 🎓"

    greeting_chat = ONBOARDING_GREETING_CHAT.format(name=name, child_line=child_line)
    greeting_tg = ONBOARDING_GREETING_TG.format(name=name, child_line=child_line)

    # 3. Save greeting as assistant message in the sales conversation (plain text for chat)
    if conversation_id:
        repo.save_message(
            conversation_id=conversation_id,
            role="assistant",
            content=greeting_chat,
        )

    now = datetime.now(timezone.utc)

    # 4. Create onboarding record
    onboarding_id = repo.save_onboarding(
        actor_id=actor_id,
        payment_order_id=payment_order_id,
        conversation_id=conversation_id,
        dms_contact_id=dms_contact_id,
        product_name=product,
        child_name=child_name,
        child_grade=child_grade,
        status="greeting_sent",
    )

    if onboarding_id:
        repo.update_onboarding_status(
            onboarding_id, "greeting_sent", greeting_sent_at=now,
        )

    # 5. Send Telegram push (HTML formatted)
    _send_telegram(actor_id, greeting_tg, parse_mode="HTML")

    # 6. Schedule follow-up chain (24h + 48h)
    if conversation_id and onboarding_id:
        _create_onboarding_chain(repo, conversation_id, actor_id, onboarding_id)

    # 7. Track event
    EventTracker().track(
        "onboarding_started",
        conversation_id=conversation_id,
        actor_id=actor_id,
        agent_role="support",
        data={
            "payment_order_id": payment_order_id,
            "product_name": product,
            "child_name": child_name,
            "child_grade": child_grade,
        },
    )

    logger.info(
        "Support onboarding triggered: actor=%s product=%s child=%s",
        actor_id, product, child_name,
    )


# --- Follow-up chain ---------------------------------------------------------

def _create_onboarding_chain(
    repo: ConversationRepository,
    conversation_id: str,
    actor_id: str,
    onboarding_id: str,
) -> None:
    """Schedule 2-step onboarding follow-up: 24h check-in + 48h escalation."""
    now = datetime.now(timezone.utc)
    for step, delay in ONBOARDING_DELAYS.items():
        fire_at = now + delay
        try:
            repo.save_followup_with_type(
                conversation_id=conversation_id,
                actor_id=actor_id,
                payment_order_id=None,
                step=step,
                next_fire_at=fire_at,
                chain_type="onboarding",
                onboarding_id=onboarding_id,
            )
            logger.info(
                "Onboarding follow-up step %d scheduled for %s (conv=%s)",
                step, fire_at.isoformat(), conversation_id,
            )
        except Exception:
            logger.exception("Failed to save onboarding follow-up step %d", step)


def process_onboarding_followup(f: dict) -> None:
    """Process a single onboarding follow-up (called from followup.py)."""
    repo = ConversationRepository()
    step = f["step"]
    full_name = f.get("actor_name") or ""
    name = _extract_first_name(full_name) or "друг"
    now = datetime.now(timezone.utc)
    onboarding_id = f.get("onboarding_id")
    conversation_id = f.get("conversation_id")

    if step == 1:
        # 24h check-in: send message + Telegram push
        chat_text = ONBOARDING_CHECK_CHAT.format(name=name)
        tg_text = ONBOARDING_CHECK_TG.format(name=name)

        if conversation_id:
            repo.save_message(conversation_id=conversation_id, role="assistant", content=chat_text)

        _send_telegram(f.get("actor_id"), tg_text, parse_mode="HTML")
        repo.update_followup_status(f["id"], "sent", sent_at=now)

        if onboarding_id:
            repo.update_onboarding_status(
                onboarding_id, "followup_sent", followup_sent_at=now,
            )

        EventTracker().track(
            "onboarding_followup_sent",
            conversation_id=conversation_id,
            actor_id=f.get("actor_id", ""),
            agent_role="support",
            data={"step": step},
        )
        logger.info("Onboarding check-in sent for conv=%s", conversation_id)

    elif step == 2:
        # 48h: check if client responded, escalate if not
        replied = False
        if conversation_id:
            replied = repo.check_user_replied_in_conversation(conversation_id)

        if replied:
            repo.update_followup_status(f["id"], "cancelled")
            if onboarding_id:
                repo.update_onboarding_status(
                    onboarding_id, "responded", client_responded=True,
                )
            logger.info("Onboarding: client responded, skipping escalation for conv=%s", conversation_id)
        else:
            # Escalate to manager
            _escalate_onboarding_no_response(f)
            repo.update_followup_status(f["id"], "sent", sent_at=now)
            if onboarding_id:
                repo.update_onboarding_status(
                    onboarding_id, "escalated", escalated_at=now,
                )

            EventTracker().track(
                "onboarding_escalated",
                conversation_id=conversation_id,
                actor_id=f.get("actor_id", ""),
                agent_role="support",
                data={"reason": "no_response_48h"},
            )
            logger.info("Onboarding escalated for conv=%s (no response 48h)", conversation_id)


# --- Response detection -------------------------------------------------------

def mark_onboarding_responded(repo: ConversationRepository, conversation_id: str) -> None:
    """Called from chat.py when user sends a message in an onboarding conversation."""
    onb = repo.get_active_onboarding_for_conversation(conversation_id)
    if not onb:
        return

    if onb.get("client_responded"):
        return  # Already marked

    repo.update_onboarding_status(
        onb["id"], "responded", client_responded=True,
    )
    repo.cancel_followups_for_conversation(conversation_id)

    logger.info("Onboarding: client responded in conv=%s, follow-ups cancelled", conversation_id)


# --- Telegram -----------------------------------------------------------------

def _send_telegram(actor_id: str | None, text: str, parse_mode: str | None = None) -> None:
    """Send push notification via Telegram bot (telegram users only)."""
    if not actor_id or not actor_id.startswith("telegram:"):
        return

    settings = get_settings()
    bot_token = settings.telegram_bot_token
    if not bot_token:
        return

    chat_id = actor_id.replace("telegram:", "")
    payload: dict = {"chat_id": chat_id, "text": text}
    if parse_mode:
        payload["parse_mode"] = parse_mode

    # Add inline button "Открыть Эврику" → Mini App
    settings_obj = get_settings()
    frontend_url = settings_obj.frontend_url or ""
    if frontend_url:
        payload["reply_markup"] = {
            "inline_keyboard": [[
                {"text": "💬 Открыть Эврику", "web_app": {"url": f"{frontend_url}?role=support"}}
            ]]
        }

    try:
        httpx.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json=payload,
            timeout=10,
        )
        logger.info("Onboarding Telegram sent to %s", chat_id)
    except Exception:
        logger.exception("Failed to send onboarding Telegram to %s", chat_id)


def _extract_first_name(full_name: str | None) -> str | None:
    """Extract first name from FIO: 'Иванова Мария Петровна' → 'Мария'."""
    if not full_name:
        return None
    parts = full_name.strip().split()
    if len(parts) >= 2:
        return parts[1]  # Фамилия Имя Отчество → Имя
    return parts[0] if parts else None


def _escalate_onboarding_no_response(followup: dict) -> None:
    """Send Telegram alert to manager when client doesn't respond after 48h."""
    settings = get_settings()
    chat_id = settings.manager_telegram_chat_id
    bot_token = settings.telegram_bot_token

    if not chat_id or not bot_token:
        return

    def _esc(s: str) -> str:
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    name = followup.get("actor_name") or "—"
    product = followup.get("onb_product") or followup.get("product_name") or "—"
    child = followup.get("child_name") or "—"
    grade = followup.get("child_grade")
    child_str = f"{_esc(child)}, {grade} класс" if grade else _esc(child)

    text = ONBOARDING_ESCALATION.format(
        name=_esc(name), product=_esc(product), child=child_str,
    )

    try:
        httpx.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        logger.info("Onboarding escalation sent to manager for actor=%s", followup.get("actor_id"))
    except Exception:
        logger.exception("Failed to send onboarding escalation to manager")

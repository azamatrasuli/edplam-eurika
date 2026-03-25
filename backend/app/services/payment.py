"""Payment orchestration: product lookup → DMS order → payment link → DB."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.db.events import EventTracker
from app.db.repository import ConversationRepository
from app.integrations.amocrm import AmoCRMClient
from app.integrations.dms import DMSServiceBase, ProductCatalog, _normalize_phone, _format_phone_dms

logger = logging.getLogger("services.payment")


class PaymentService:
    """Orchestrates the full payment flow: find product → create order → get link → save."""

    def __init__(
        self,
        dms: DMSServiceBase,
        repo: ConversationRepository,
        crm: AmoCRMClient | None = None,
    ) -> None:
        self.dms = dms
        self.catalog = ProductCatalog(dms)
        self.repo = repo
        self.crm = crm or AmoCRMClient()

    def create_payment(
        self,
        actor_id: str,
        conversation_id: str,
        product_name: str,
        grade: int,
        payer_phone: str,
        student_name: str | None = None,
        amocrm_lead_id: int | None = None,
    ) -> dict:
        """
        Full payment flow:
        1. Find product in DMS catalog by name + grade
        2. Find payer contact in DMS by phone
        3. Create order in DMS
        4. Generate payment link
        5. Save to agent_payment_orders
        6. Return result dict for the tool

        Returns dict with keys: success, error?, order_uuid?, payment_url?,
        amount_rub?, product_name?, order_id?
        """
        # 1. Find product
        product = self.catalog.find_product(product_name, grade)
        if not product:
            logger.warning("Product not found: '%s' grade=%d", product_name, grade)
            return {
                "success": False,
                "error": f"Продукт '{product_name}' для {grade} класса не найден в каталоге",
            }

        # 2. Find payer contact in DMS
        search_result = self.dms.search_contact_by_phone(payer_phone)
        if not search_result:
            logger.warning("Payer contact not found in DMS: %s", payer_phone)
            return {
                "success": False,
                "error": f"Контакт с телефоном {payer_phone} не найден в системе. Проверьте номер.",
            }
        payer_contact = search_result.contact

        # Find matching student by grade or first active
        student = None
        for s in search_result.students:
            if s.grade == grade and s.is_active:
                student = s
                break
        if not student:
            for s in search_result.students:
                if s.is_active:
                    student = s
                    break
        if not student:
            logger.warning("No active student found for contact=%d grade=%d", payer_contact.contact_id, grade)
            return {
                "success": False,
                "error": "Не найден ученик для оформления заказа. Уточните данные.",
            }

        # 3. Create order
        order = self.dms.create_order(payer_contact, student, product, product.price_kopecks)
        if not order:
            logger.error("Failed to create DMS order for contact=%d product=%s",
                         payer_contact.contact_id, product.uuid)
            return {
                "success": False,
                "error": "Не удалось создать заказ. Попробуйте позже.",
            }

        # 4. Generate payment link
        payment_url = self.dms.get_payment_link(order.order_uuid, pay_type=1)
        if not payment_url:
            logger.error("Failed to generate payment link for order=%s", order.order_uuid)
            return {
                "success": False,
                "error": "Не удалось сгенерировать ссылку на оплату. Попробуйте позже.",
            }

        # 5. Save to DB
        # DMS price field is in rubles (not kopecks despite the field name);
        # display value matches what Tochka charges.
        amount_rub = product.price_kopecks
        try:
            db_id = self.repo.save_payment_order(
                conversation_id=conversation_id,
                actor_id=actor_id,
                dms_order_uuid=order.order_uuid,
                dms_contact_id=payer_contact.contact_id,
                product_name=product.name,
                product_uuid=product.uuid,
                amount_kopecks=product.price_kopecks,
                payment_url=payment_url,
                pay_type=1,
                amocrm_lead_id=amocrm_lead_id,
            )
            logger.info("Payment order saved: id=%s order_uuid=%s amount=%d RUB",
                         db_id, order.order_uuid, amount_rub)
        except Exception:
            logger.exception("Failed to save payment order to DB")
            # Non-fatal — payment link was already generated
            db_id = None

        # 6. Create follow-up chain
        if db_id:
            try:
                from app.services.followup import create_followup_chain
                create_followup_chain(
                    repo=self.repo,
                    conversation_id=conversation_id,
                    actor_id=actor_id,
                    payment_order_id=db_id,
                )
            except Exception:
                logger.exception("Failed to create follow-up chain")

        # Track payment_generated event
        EventTracker().track_payment(
            "payment_generated",
            conversation_id=conversation_id,
            actor_id=actor_id,
            order_uuid=order.order_uuid,
            amount_kopecks=product.price_kopecks,
            product_name=product.name,
        )

        return {
            "success": True,
            "order_uuid": order.order_uuid,
            "order_id": db_id,
            "payment_url": payment_url,
            "amount_rub": amount_rub,
            "product_name": product.name,
            "grade": grade,
        }


def check_pending_payments() -> None:
    """Scheduled job: poll DMS for paid orders and update DB/CRM."""
    repo = ConversationRepository()

    try:
        pending = repo.get_pending_payments()
    except Exception:
        logger.exception("Failed to fetch pending payments")
        return

    if not pending:
        return

    from app.integrations.dms import get_dms_service
    dms = get_dms_service()
    crm = AmoCRMClient()

    logger.info("Checking %d pending payments", len(pending))

    for order in pending:
        try:
            status = dms.get_order_status(order["dms_order_uuid"])
            if status is None:
                continue

            if status == 2:  # paid
                now = datetime.now(timezone.utc)
                repo.update_payment_status(order["id"], "paid", paid_at=now)
                logger.info("Payment confirmed: order=%s uuid=%s",
                            order["id"], order["dms_order_uuid"])

                # Track payment_confirmed event
                EventTracker().track_payment(
                    "payment_confirmed",
                    conversation_id=order.get("conversation_id"),
                    actor_id=order.get("actor_id", ""),
                    order_uuid=order["dms_order_uuid"],
                    amount_kopecks=order.get("amount_kopecks", 0),
                    product_name=order.get("product_name"),
                )

                # Cancel follow-ups
                repo.cancel_followups_for_conversation(order["conversation_id"])

                # Update amoCRM deal to won
                lead_id = order.get("amocrm_lead_id")
                if lead_id:
                    try:
                        crm.update_lead(lead_id, status_id=142)
                        logger.info("CRM deal %d moved to won", lead_id)
                    except Exception:
                        logger.exception("Failed to update CRM deal %d", lead_id)

                # Save confirmation message in conversation
                product = order.get("product_name", "Обучение")
                # amount_kopecks is actually in rubles (DMS convention)
                amount = order.get("amount_kopecks", 0)
                amount_str = f"{amount:,.0f}".replace(",", " ")
                repo.save_message(
                    conversation_id=order["conversation_id"],
                    role="assistant",
                    content=(
                        f"Оплата подтверждена! {product} успешно оплачен "
                        f"({amount_str} ₽). Спасибо! Если возникнут вопросы — "
                        "я всегда на связи."
                    ),
                )

                # Trigger support onboarding (fire-and-forget)
                try:
                    from app.services.support_onboarding import trigger_support_onboarding
                    trigger_support_onboarding(order)
                except Exception:
                    logger.exception(
                        "Failed to trigger support onboarding for order=%s",
                        order["id"],
                    )

            elif status == 4:  # refund
                repo.update_payment_status(order["id"], "cancelled")
                logger.info("Payment refunded: order=%s", order["id"])

        except Exception:
            logger.exception("Error checking payment status: order=%s", order["id"])

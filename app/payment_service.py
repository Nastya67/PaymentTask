"""Start, complete from the webhook, reconcile.

No transaction is open while waiting for the provider.
"""

import logging
import uuid
from datetime import timedelta

from sqlalchemy import Row, func, select

from app import inventory, pricing, provider
from app.db import db_session, transactional
from app.errors import CartNotFound, PaymentMismatch, PaymentNotFound
from app.models import Cart, Payment, PaymentStatus

logger = logging.getLogger(__name__)

RECONCILE_AFTER = timedelta(minutes=15)
CANCEL_AFTER = timedelta(hours=24)
RECONCILE_BATCH = 100


def start_payment(
    user_id: uuid.UUID, cart_id: uuid.UUID, payment_method_id: uuid.UUID | None
) -> Payment:
    payment = _create_payment(user_id, cart_id, payment_method_id)
    try:
        provider.create_payment(
            payment.payment_method.provider_token,
            payment.amount,
            payment.currency,
            reference=str(payment.id),
        )
    except provider.ProviderUnavailable:
        logger.warning("Provider unavailable, payment %s left pending", payment.id)
    return payment


@transactional
def complete_payment(result: provider.PaymentResult) -> None:
    payment = db_session.get(
        Payment, result.payment_id, with_for_update=True, populate_existing=True
    )
    if payment is None:
        raise PaymentNotFound("Payment not found")
    if not payment.is_pending:
        if result.succeeded and payment.status == PaymentStatus.FAILED:
            logger.error("Payment %s charged after it failed: refund", payment.id)
            # todo refund
        return
    if (result.amount, result.currency) != (payment.amount, payment.currency):
        logger.error("Payment %s: provider reports another amount", payment.id)
        raise PaymentMismatch("Amount or currency does not match the payment")
        # todo what todo?

    if result.succeeded:
        payment.succeed(result.provider_payment_id)
        payment.cart.check_out()
    else:
        payment.fail(result.failure_reason)
        inventory.release(payment.cart_id)


def reconcile_payments() -> None:
    """Resolves payments stuck in pending by asking the provider for their outcome."""
    for payment in _stuck_payments():
        try:
            _reconcile(payment)
        except provider.ProviderUnavailable:
            logger.warning("Provider unavailable, payment %s left pending", payment.id)
        except Exception:
            logger.exception("Payment %s could not be reconciled", payment.id)


@transactional
def _stuck_payments() -> list[Row]:
    return db_session.execute(
        select(
            Payment.id,
            Payment.amount,
            Payment.currency,
            (Payment.created_at < func.now() - CANCEL_AFTER).label("overdue"),
        )
        .where(
            Payment.status == PaymentStatus.PENDING,
            Payment.created_at < func.now() - RECONCILE_AFTER,
        )
        .order_by(Payment.created_at)
        .limit(RECONCILE_BATCH)
    ).all()


def _reconcile(payment: Row) -> None:
    reference = str(payment.id)
    outcome = provider.get_payment(reference)
    if outcome is provider.NoResult.PROCESSING:
        if not payment.overdue:
            return
        outcome = provider.cancel_payment(reference)
        if outcome is provider.NoResult.PROCESSING:
            return
    if isinstance(outcome, provider.NoResult):
        outcome = provider.PaymentResult(
            payment_id=payment.id,
            succeeded=False,
            amount=payment.amount,
            currency=payment.currency,
            provider_payment_id=None,
            failure_reason=outcome,
        )
    complete_payment(outcome)
    logger.info("Payment %s reconciled", payment.id)


@transactional
def _create_payment(
    user_id: uuid.UUID, cart_id: uuid.UUID, payment_method_id: uuid.UUID | None
) -> Payment:
    cart = db_session.scalar(
        select(Cart)
        .where(Cart.id == cart_id, Cart.user_id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if cart is None:
        raise CartNotFound("Cart not found")
    cart.ensure_payable()

    inventory.reserve(cart.id)
    amount, currency = pricing.calculate_total(cart.id)
    method = cart.user.payment_method(payment_method_id)
    payment = Payment.start(cart, method, amount, currency)
    db_session.add(payment)
    return payment

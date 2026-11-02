"""Start, complete from the webhook, cancel when the webhook never comes.

No transaction is open while waiting for the provider.
"""

import logging
import uuid
from datetime import timedelta

from sqlalchemy import Row, func, select

from app import inventory, pricing
from app.db import db_session, transactional
from app.errors import CartNotFound
from app.models import Cart, Money
from app.payments import provider
from app.payments.errors import PaymentMismatch, PaymentNotFound
from app.payments.models import Payment, PaymentStatus

logger = logging.getLogger(__name__)

CANCEL_AFTER = timedelta(hours=24)


def start_payment(
    user_id: uuid.UUID, cart_id: uuid.UUID, payment_method_id: uuid.UUID | None
) -> Payment:
    payment = _create_payment(user_id, cart_id, payment_method_id)
    try:
        provider.create_payment(
            payment.payment_method.provider_token,
            payment.total,
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
    if result.succeeded:
        payment.succeed(result.provider_payment_id)
        payment.cart.check_out()
    else:
        payment.fail(result.failure_reason)
        inventory.release(payment.cart_id)


def cancel_stale_payments() -> None:
    """Cancels payments still pending after CANCEL_AFTER: their webhook never came.

    The stock is released only once the provider confirms there is no charge.
    A payment the provider does not answer for stays pending until the next run.
    """
    for payment in _stale_payments():
        try:
            _cancel(payment)
        except provider.ProviderUnavailable:
            logger.warning("Provider unavailable, payment %s left pending", payment.id)
        except Exception:
            logger.exception("Payment %s could not be cancelled", payment.id)


@transactional
def _stale_payments() -> list[Row]:
    return db_session.execute(
        select(Payment.id, Payment.amount, Payment.currency)
        .where(
            Payment.status == PaymentStatus.PENDING,
            Payment.created_at < func.now() - CANCEL_AFTER,
        )
        .order_by(Payment.created_at)
    ).all()


def _cancel(payment: Row) -> None:
    result = provider.cancel_payment(str(payment.id))
    if result is None:
        result = provider.PaymentResult(
            payment_id=payment.id,
            succeeded=False,
            total=Money(payment.amount, payment.currency),
            provider_payment_id=None,
            failure_reason="cancelled",
        )
    complete_payment(result)
    logger.info("Payment %s resolved after %s", payment.id, CANCEL_AFTER)


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

    total = pricing.calculate_total(cart.id)
    method = cart.user.payment_method(payment_method_id)
    payment = Payment.start(cart, method, total)
    db_session.add(payment)

    inventory.reserve(cart.id)
    return payment

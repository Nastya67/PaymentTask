"""flask cancel-stale-payments"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models import CartStatus, Money
from app.payments import provider
from app.payments.models import PaymentStatus

STALE = datetime.now(timezone.utc) - timedelta(hours=25)
FRESH = datetime.now(timezone.utc) - timedelta(hours=23)


@pytest.fixture
def cancel(monkeypatch):
    """The provider's answer to a cancel request; records the references asked for."""

    class Cancel:
        calls: list[str] = []
        answer = None  # None: cancelled, nothing charged

        def __call__(self, reference):
            self.calls.append(reference)
            if isinstance(self.answer, Exception):
                raise self.answer
            return self.answer(reference) if callable(self.answer) else self.answer

    cancel = Cancel()
    cancel.calls = []
    monkeypatch.setattr(provider, "cancel_payment", cancel)
    return cancel


@pytest.fixture
def run(app):
    def run():
        result = app.test_cli_runner().invoke(args=["cancel-stale-payments"])
        assert result.exit_code == 0, result.output

    return run


@pytest.fixture
def user(data):
    return data.user()


@pytest.fixture
def card(data, user):
    return data.payment_method(user, is_default=True)


@pytest.fixture
def product(data):
    # 2 of 10 reserved by the pending payment of the cart below.
    return data.product(price="5.00", stock=8)


@pytest.fixture
def cart(data, user, product):
    return data.cart(user, items=[(product, 2)])


def pending(data, cart, card, created_at=STALE):
    return data.payment(
        cart, card, PaymentStatus.PENDING, amount="10.00", created_at=created_at
    )


def result(reference, succeeded):
    return provider.PaymentResult(
        payment_id=uuid.UUID(reference),
        succeeded=succeeded,
        total=Money(Decimal("10.00"), "USD"),
        provider_payment_id="ch_late" if succeeded else None,
        failure_reason=None if succeeded else "card_declined",
    )


def test_cancels_stale_payment_and_releases_stock(
    data, cart, card, product, cancel, run
):
    payment = pending(data, cart, card)

    run()

    assert cancel.calls == [str(payment.id)]
    (payment,) = data.payments(cart)
    assert (payment.status, payment.failure_reason) == ("failed", "cancelled")
    assert data.stock(product) == 10
    assert data.cart_status(cart) == CartStatus.ACTIVE


def test_cart_can_be_paid_again_after_cancel(
    client, data, user, cart, card, cancel, run
):
    pending(data, cart, card)
    run()

    response = client.post(
        f"/carts/{cart.id}/payments", headers={"X-User-Id": str(user.id)}
    )

    assert response.status_code == 202


def test_leaves_payments_younger_than_24_hours(data, cart, card, product, cancel, run):
    pending(data, cart, card, created_at=FRESH)

    run()

    assert cancel.calls == []
    assert data.payments(cart)[0].status == PaymentStatus.PENDING
    assert data.stock(product) == 8


@pytest.mark.parametrize("status", [PaymentStatus.SUCCEEDED, PaymentStatus.FAILED])
def test_leaves_resolved_payments(data, cart, card, cancel, run, status):
    data.payment(cart, card, status, created_at=STALE)

    run()

    assert cancel.calls == []
    assert data.payments(cart)[0].status == status


def test_payment_that_succeeded_before_cancel(data, cart, card, product, cancel, run):
    pending(data, cart, card)
    cancel.answer = lambda reference: result(reference, succeeded=True)

    run()

    (payment,) = data.payments(cart)
    assert (payment.status, payment.provider_payment_id) == ("succeeded", "ch_late")
    assert data.cart_status(cart) == CartStatus.CHECKED_OUT
    assert data.stock(product) == 8  # sold


def test_payment_that_failed_before_cancel(data, cart, card, product, cancel, run):
    pending(data, cart, card)
    cancel.answer = lambda reference: result(reference, succeeded=False)

    run()

    (payment,) = data.payments(cart)
    assert (payment.status, payment.failure_reason) == ("failed", "card_declined")
    assert data.stock(product) == 10


def test_provider_unavailable_retries_on_next_run(
    data, cart, card, product, cancel, run
):
    pending(data, cart, card)
    cancel.answer = provider.ProviderUnavailable()

    run()

    assert data.payments(cart)[0].status == PaymentStatus.PENDING
    assert data.stock(product) == 8

    cancel.answer = None
    run()

    assert data.payments(cart)[0].status == PaymentStatus.FAILED
    assert data.stock(product) == 10
    assert len(cancel.calls) == 2


def test_one_broken_payment_does_not_stop_the_others(
    data, user, card, product, cancel, run
):
    broken_cart = data.cart(user, items=[(product, 2)])
    broken = pending(data, broken_cart, card, created_at=STALE - timedelta(hours=1))
    other_cart = data.cart(user, items=[(product, 2)])
    pending(data, other_cart, card)

    def answer(reference):
        if reference == str(broken.id):
            raise RuntimeError("unexpected provider response")
        return None

    cancel.answer = answer

    run()

    assert data.payments(broken_cart)[0].status == PaymentStatus.PENDING
    assert data.payments(other_cart)[0].status == PaymentStatus.FAILED
    assert len(cancel.calls) == 2

"""POST /webhooks/payment-result"""

import uuid

import pytest

from app.models import CartStatus
from app.payments.models import PaymentStatus


def send(client, payment_id, type_):
    event = {
        "type": type_,
        "payment_id": str(payment_id),
        "amount": "10.00",
        "currency": "USD",
        "provider_payment_id": "ch_1" if type_ == "payment.succeeded" else None,
        "failure_reason": "card_declined" if type_ == "payment.failed" else None,
    }
    return client.post("/webhooks/payment-result", json=event)


@pytest.fixture
def product(data):
    # 2 of 10 reserved by the pending payment of the cart below.
    return data.product(price="5.00", stock=8)


@pytest.fixture
def cart(data, product):
    return data.cart(data.user(), items=[(product, 2)])


@pytest.fixture
def payment(data, cart):
    card = data.payment_method(data.user())
    return data.payment(cart, card, PaymentStatus.PENDING, amount="10.00")


def test_succeeded(client, data, cart, product, payment):
    assert send(client, payment.id, "payment.succeeded").status_code == 200

    assert data.payments(cart)[0].status == PaymentStatus.SUCCEEDED
    assert data.cart_status(cart) == CartStatus.CHECKED_OUT
    assert data.stock(product) == 8


def test_failed_releases_stock(client, data, cart, product, payment):
    assert send(client, payment.id, "payment.failed").status_code == 200

    assert data.payments(cart)[0].status == PaymentStatus.FAILED
    assert data.cart_status(cart) == CartStatus.ACTIVE
    assert data.stock(product) == 10


def test_repeated_failed_releases_stock_once(client, data, cart, product, payment):
    send(client, payment.id, "payment.failed")

    assert send(client, payment.id, "payment.failed").status_code == 200

    assert data.stock(product) == 10


@pytest.mark.parametrize(
    "first, then, status, stock",
    [
        ("payment.succeeded", "payment.succeeded", PaymentStatus.SUCCEEDED, 8),
        ("payment.succeeded", "payment.failed", PaymentStatus.SUCCEEDED, 8),
        ("payment.failed", "payment.succeeded", PaymentStatus.FAILED, 10),
    ],
)
def test_late_event_is_ignored(
    client, data, cart, product, payment, first, then, status, stock
):
    send(client, payment.id, first)

    assert send(client, payment.id, then).status_code == 200

    assert data.payments(cart)[0].status == status
    assert data.stock(product) == stock


def test_unknown_payment(client):
    assert send(client, uuid.uuid4(), "payment.succeeded").status_code == 404


def test_malformed_payload(client):
    response = client.post("/webhooks/payment-result", json={"type": "refunded"})

    assert response.status_code == 400

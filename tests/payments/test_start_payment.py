"""POST /carts/<cart_id>/payments"""

import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.models import CartStatus, Money
from app.payments import provider
from app.payments.models import PaymentStatus


def start(client, cart, user, json=None):
    headers = {"X-User-Id": str(user.id)} if user else {}
    return client.post(f"/carts/{cart.id}/payments", headers=headers, json=json)


@pytest.fixture
def provider_calls(monkeypatch):
    calls = []
    real = provider.create_payment

    def spy(token, total, reference):
        calls.append((token, total, reference))
        real(token, total, reference)

    monkeypatch.setattr(provider, "create_payment", spy)
    return calls


@pytest.fixture
def user(data):
    return data.user()


@pytest.fixture
def card(data, user):
    return data.payment_method(user, token="tok_default", is_default=True)


@pytest.fixture
def kettle(data):
    return data.product(price="45.00", stock=10)


@pytest.fixture
def mug(data):
    return data.product(price="12.50", stock=100)


@pytest.fixture
def cart(data, user, card, kettle, mug):
    return data.cart(user, items=[(kettle, 1), (mug, 2)])


def test_starts_payment(client, data, user, card, cart, kettle, mug, provider_calls):
    response = start(client, cart, user)

    assert response.status_code == 202
    (payment,) = data.payments(cart)
    assert response.json == {
        "id": str(payment.id),
        "cart_id": str(cart.id),
        "status": "pending",
        "amount": "70.00",
        "currency": "USD",
    }
    assert payment.status == PaymentStatus.PENDING
    assert payment.total == Money(Decimal("70.00"), "USD")
    assert payment.payment_method_id == card.id
    assert provider_calls == [
        ("tok_default", Money(Decimal("70.00"), "USD"), str(payment.id))
    ]


def test_reserves_stock_and_keeps_cart_active(client, data, user, cart, kettle, mug):
    start(client, cart, user)

    assert data.stock(kettle) == 9
    assert data.stock(mug) == 98
    assert data.cart_status(cart) == CartStatus.ACTIVE


def test_sums_quantities_of_one_product_in_several_items(client, data, user, card):
    product = data.product(stock=3)
    cart = data.cart(user, items=[(product, 2), (product, 1)])

    assert start(client, cart, user).status_code == 202
    assert data.stock(product) == 0


def test_uses_given_payment_method(client, data, user, cart, provider_calls):
    other = data.payment_method(user, token="tok_other")

    response = start(client, cart, user, json={"payment_method_id": str(other.id)})

    assert response.status_code == 202
    assert data.payments(cart)[0].payment_method_id == other.id
    assert provider_calls[0][0] == "tok_other"


def test_without_default_uses_newest_payment_method(client, data, user, kettle):
    now = datetime.now(timezone.utc)
    data.payment_method(user, token="tok_old", created_at=now - timedelta(days=2))
    newest = data.payment_method(
        user, token="tok_new", created_at=now - timedelta(days=1)
    )
    cart = data.cart(user, items=[(kettle, 1)])

    assert start(client, cart, user).status_code == 202
    assert data.payments(cart)[0].payment_method_id == newest.id


def test_failed_payment_can_be_retried(client, data, user, card, cart):
    data.payment(cart, card, PaymentStatus.FAILED)

    assert start(client, cart, user).status_code == 202
    assert [p.status for p in data.payments(cart)] == ["failed", "pending"]


def test_provider_unavailable_leaves_payment_pending(client, data, user, kettle):
    data.payment_method(user, token="tok_unavailable", is_default=True)
    cart = data.cart(user, items=[(kettle, 2)])

    response = start(client, cart, user)

    assert response.status_code == 202
    assert response.json["status"] == "pending"
    assert data.payments(cart)[0].status == PaymentStatus.PENDING
    assert data.stock(kettle) == 8  # stays reserved until the outcome is known


@pytest.mark.parametrize("header", [None, "not-a-uuid"])
def test_requires_user(client, data, cart, header):
    headers = {} if header is None else {"X-User-Id": header}

    response = client.post(f"/carts/{cart.id}/payments", headers=headers)

    assert response.status_code == 401
    assert data.payments(cart) == []


def test_unknown_cart(client, data, user, card):
    response = client.post(
        f"/carts/{uuid.uuid4()}/payments", headers={"X-User-Id": str(user.id)}
    )

    assert response.status_code == 404


def test_cart_of_another_user(client, data, cart, kettle):
    other_user = data.user()
    data.payment_method(other_user, is_default=True)

    response = start(client, cart, other_user)

    assert response.status_code == 404
    assert data.payments(cart) == []
    assert data.stock(kettle) == 10


@pytest.mark.parametrize("status", [CartStatus.CHECKED_OUT, CartStatus.ABANDONED])
def test_cart_not_active(client, data, user, card, kettle, status):
    cart = data.cart(user, items=[(kettle, 1)], status=status)

    response = start(client, cart, user)

    assert response.status_code == 409
    assert response.json == {"error": f"Cart is {status}"}
    assert data.stock(kettle) == 10


def test_payment_in_progress(client, data, user, card, cart, kettle):
    data.payment(cart, card, PaymentStatus.PENDING)

    response = start(client, cart, user)

    assert response.status_code == 409
    assert response.json == {"error": "A payment for this cart is already in progress"}
    assert len(data.payments(cart)) == 1
    assert data.stock(kettle) == 10


def test_out_of_stock(client, data, user, card, kettle):
    scarce = data.product(stock=1)
    cart = data.cart(user, items=[(kettle, 1), (scarce, 2)])

    response = start(client, cart, user)

    assert response.status_code == 409
    assert response.json == {"error": "Some products are out of stock"}
    assert data.payments(cart) == []
    assert data.stock(kettle) == 10
    assert data.stock(scarce) == 1


def test_empty_cart(client, data, user, card):
    cart = data.cart(user)

    response = start(client, cart, user)

    assert response.status_code == 422
    assert response.json == {"error": "Cart is empty"}


def test_mixed_currencies(client, data, user, card):
    cart = data.cart(
        user,
        items=[(data.product(currency="USD"), 1), (data.product(currency="EUR"), 1)],
    )

    assert start(client, cart, user).status_code == 422
    assert data.payments(cart) == []


def test_zero_total(client, data, user, card):
    free = data.product(price="0.00", stock=5)
    cart = data.cart(user, items=[(free, 1)])

    response = start(client, cart, user)

    assert response.status_code == 422
    assert response.json == {"error": "Cart total must be positive"}
    assert data.stock(free) == 5


def test_user_without_payment_methods(client, data, kettle):
    user = data.user()
    cart = data.cart(user, items=[(kettle, 1)])

    response = start(client, cart, user)

    assert response.status_code == 422
    assert response.json == {"error": "Payment method not found"}
    assert data.stock(kettle) == 10


@pytest.mark.parametrize("method_id", ["unknown", "other user's"])
def test_payment_method_not_of_user(client, data, user, cart, kettle, method_id):
    if method_id == "unknown":
        payment_method_id = uuid.uuid4()
    else:
        payment_method_id = data.payment_method(data.user()).id

    response = start(
        client, cart, user, json={"payment_method_id": str(payment_method_id)}
    )

    assert response.status_code == 422
    assert data.payments(cart) == []
    assert data.stock(kettle) == 10


@pytest.mark.parametrize(
    "body, error",
    [
        (["not", "an", "object"], "Request body must be a JSON object"),
        ({"payment_method_id": 5}, "payment_method_id must be a UUID"),
        ({"payment_method_id": "nope"}, "payment_method_id must be a UUID"),
    ],
)
def test_invalid_body(client, data, user, cart, body, error):
    response = start(client, cart, user, json=body)

    assert response.status_code == 422
    assert response.json == {"error": error}
    assert data.payments(cart) == []


def test_concurrent_requests_charge_once(app, data, user, cart, kettle, provider_calls):
    attempts = 10
    barrier = threading.Barrier(attempts)
    statuses = []

    def pay():
        client = app.test_client()
        barrier.wait()
        statuses.append(start(client, cart, user).status_code)

    threads = [threading.Thread(target=pay) for _ in range(attempts)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(statuses) == [202] + [409] * (attempts - 1)
    assert len(data.payments(cart)) == 1
    assert len(provider_calls) == 1
    assert data.stock(kettle) == 9

"""Test setup: a separate database, emptied before every test."""

import os
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, make_url, select, text
from sqlalchemy.orm import Session

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://shop:shop@localhost:5434/shop_test"
)
# Every test empties all tables, so never run against anything but a test database.
assert make_url(TEST_DATABASE_URL).database.endswith("_test"), TEST_DATABASE_URL
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from alembic import command
from alembic.config import Config  # noqa: E402

from app import create_app  # noqa: E402
from app.models import (  # noqa: E402
    Cart,
    CartItem,
    CartStatus,
    Product,
    User,
    UserPaymentMethod,
)
from app.payments.models import Payment, PaymentStatus  # noqa: E402

TABLES = "users, products, carts, cart_items, user_payment_methods, payments"


@pytest.fixture(scope="session")
def engine():
    _create_database()
    command.upgrade(
        Config(toml_file=Path(__file__).parent.parent / "pyproject.toml"), "head"
    )
    engine = create_engine(TEST_DATABASE_URL)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def app(engine):
    return create_app()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def empty_tables(engine):
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} CASCADE"))


@pytest.fixture
def data(engine):
    return Data(engine)


class Data:
    """Creates and reads rows directly, outside the app's session."""

    def __init__(self, engine):
        self._engine = engine

    def _add(self, obj):
        with Session(self._engine, expire_on_commit=False) as session, session.begin():
            session.add(obj)
        return obj

    def user(self) -> User:
        count = self.count(User)
        return self._add(User(email=f"user{count}@example.com", name=f"User {count}"))

    def product(self, price="10.00", stock=10, currency="USD") -> Product:
        return self._add(
            Product(
                name="Product",
                price=Decimal(price),
                currency=currency,
                stock_quantity=stock,
            )
        )

    def payment_method(
        self,
        user: User,
        token="tok_visa",
        is_default=False,
        created_at: datetime | None = None,
    ) -> UserPaymentMethod:
        method = UserPaymentMethod(
            user_id=user.id, provider_token=token, is_default=is_default
        )
        if created_at is not None:
            method.created_at = created_at
        return self._add(method)

    def cart(
        self,
        user: User,
        items: list[tuple[Product, int]] = (),
        status=CartStatus.ACTIVE,
    ) -> Cart:
        cart = Cart(user_id=user.id, status=status)
        cart.items = [
            CartItem(product_id=product.id, quantity=quantity, unit_price=product.price)
            for product, quantity in items
        ]
        return self._add(cart)

    def payment(
        self,
        cart: Cart,
        method: UserPaymentMethod,
        status: PaymentStatus,
        amount="1.00",
        created_at: datetime | None = None,
    ) -> Payment:
        payment = Payment(
            cart_id=cart.id,
            payment_method_id=method.id,
            amount=Decimal(amount),
            currency="USD",
            status=status,
            provider_payment_id=(
                "ch_test" if status == PaymentStatus.SUCCEEDED else None
            ),
        )
        if created_at is not None:
            payment.created_at = created_at
        return self._add(payment)

    def stock(self, product: Product) -> int:
        return self._scalar(
            select(Product.stock_quantity).where(Product.id == product.id)
        )

    def cart_status(self, cart: Cart) -> str:
        return self._scalar(select(Cart.status).where(Cart.id == cart.id))

    def payments(self, cart: Cart) -> list[Payment]:
        with Session(self._engine) as session:
            return list(
                session.scalars(
                    select(Payment).where(Payment.cart_id == cart.id)
                    .order_by(Payment.created_at)
                )
            )

    def count(self, model) -> int:
        return self._scalar(select(func.count()).select_from(model))

    def _scalar(self, query):
        with Session(self._engine) as session:
            return session.scalar(query)


def _create_database() -> None:
    url = make_url(TEST_DATABASE_URL)
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :name"),
            {"name": url.database},
        )
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()

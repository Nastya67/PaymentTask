"""SQLAlchemy models for the shop schema."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    CHAR,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    composite,
    mapped_column,
    relationship,
)

from app.errors import (
    CartEmpty,
    CartNotPayable,
    InvalidCartTotal,
    PaymentInProgress,
    PaymentMethodNotFound,
)


class Base(DeclarativeBase):
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
        sort_order=-1,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        sort_order=1,
    )


class BaseTrackUpdates(Base):
    __abstract__ = True

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        sort_order=2,
    )


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str


class CartStatus(StrEnum):
    ACTIVE = "active"
    CHECKED_OUT = "checked_out"
    ABANDONED = "abandoned"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


def _status_in(*statuses: StrEnum) -> str:
    """SQL condition built from the enum, so constraints follow its values.

    The database only changes with a migration: Alembic does not detect a
    changed CHECK constraint, so write that migration by hand.
    """
    return "status IN ({})".format(", ".join(f"'{status}'" for status in statuses))


class User(BaseTrackUpdates):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)

    carts: Mapped[list["Cart"]] = relationship(back_populates="user")
    payment_methods: Mapped[list["UserPaymentMethod"]] = relationship(
        back_populates="user"
    )

    def payment_method(
        self, payment_method_id: uuid.UUID | None
    ) -> "UserPaymentMethod":
        """The given method; without one, the default, else the newest."""
        if payment_method_id is None:
            method = max(
                self.payment_methods,
                key=lambda m: (m.is_default, m.created_at),
                default=None,
            )
        else:
            method = next(
                (m for m in self.payment_methods if m.id == payment_method_id), None
            )
        if method is None:
            raise PaymentMethodNotFound("Payment method not found")
        return method


class Product(BaseTrackUpdates):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("price >= 0", name="products_price_check"),
        CheckConstraint("stock_quantity >= 0", name="products_stock_quantity_check"),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(
        CHAR(3), nullable=False, server_default=text("'USD'")
    )
    stock_quantity: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )


class Cart(BaseTrackUpdates):
    """A shopping cart. A user has at most one active cart at a time."""

    __tablename__ = "carts"
    __table_args__ = (
        CheckConstraint(_status_in(*CartStatus), name="carts_status_check"),
        Index("idx_carts_user_id", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text(f"'{CartStatus.ACTIVE}'")
    )

    user: Mapped[User] = relationship(back_populates="carts")
    items: Mapped[list["CartItem"]] = relationship(
        back_populates="cart", cascade="all, delete-orphan", passive_deletes=True
    )
    payments: Mapped[list["Payment"]] = relationship(back_populates="cart")

    def ensure_payable(self) -> None:
        if self.status != CartStatus.ACTIVE:
            raise CartNotPayable(f"Cart is {self.status}")
        if any(payment.is_pending for payment in self.payments):
            raise PaymentInProgress("A payment for this cart is already in progress")
        if not self.items:
            raise CartEmpty("Cart is empty")

    def check_out(self) -> None:
        self.status = CartStatus.CHECKED_OUT


class CartItem(Base):
    """A product in a cart. unit_price is the price captured when it was added."""

    __tablename__ = "cart_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="cart_items_quantity_check"),
        Index("idx_cart_items_cart_id", "cart_id"),
    )

    cart_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("carts.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id"), nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)

    cart: Mapped[Cart] = relationship(back_populates="items")
    product: Mapped[Product] = relationship()


class UserPaymentMethod(Base):
    """A saved payment method. provider_token is the external provider's card token."""

    __tablename__ = "user_payment_methods"
    __table_args__ = (
        Index("idx_user_payment_methods_user_id", "user_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    provider_token: Mapped[str] = mapped_column(Text, nullable=False)
    last_four: Mapped[str | None] = mapped_column(CHAR(4))
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )

    user: Mapped[User] = relationship(back_populates="payment_methods")


class Payment(BaseTrackUpdates):
    """A charge for a cart."""

    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="payments_amount_check"),
        CheckConstraint(_status_in(*PaymentStatus), name="payments_status_check"),
        CheckConstraint(
            f"status <> '{PaymentStatus.SUCCEEDED}' OR provider_payment_id IS NOT NULL",
            name="payments_succeeded_has_provider_id",
        ),
        # At most one in-flight or successful payment per cart: blocks double charges.
        Index(
            "uq_payments_cart_id_active",
            "cart_id",
            unique=True,
            postgresql_where=text(
                _status_in(PaymentStatus.PENDING, PaymentStatus.SUCCEEDED)
            ),
        ),
        # Finds payments stuck in pending, to cancel them.
        Index(
            "ix_payments_pending_created_at",
            "created_at",
            postgresql_where=text(_status_in(PaymentStatus.PENDING)),
        ),
    )

    cart_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("carts.id"), nullable=False
    )
    payment_method_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user_payment_methods.id"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    total: Mapped[Money] = composite("amount", "currency")
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text(f"'{PaymentStatus.PENDING}'")
    )
    provider_payment_id: Mapped[str | None] = mapped_column(Text, unique=True)
    failure_reason: Mapped[str | None] = mapped_column(Text)

    cart: Mapped[Cart] = relationship(back_populates="payments")
    payment_method: Mapped[UserPaymentMethod] = relationship()

    @classmethod
    def start(
        cls,
        cart: Cart,
        payment_method: UserPaymentMethod,
        total: Money,
    ) -> "Payment":
        if payment_method.user_id != cart.user_id:
            raise PaymentMethodNotFound("Payment method not found")
        if total.amount <= 0:
            raise InvalidCartTotal("Cart total must be positive")
        return cls(
            cart=cart,
            payment_method=payment_method,
            total=total,
            status=PaymentStatus.PENDING,
        )

    @property
    def is_pending(self) -> bool:
        return self.status == PaymentStatus.PENDING

    def succeed(self, provider_payment_id: str) -> None:
        self.status = PaymentStatus.SUCCEEDED
        self.provider_payment_id = provider_payment_id

    def fail(self, reason: str | None) -> None:
        self.status = PaymentStatus.FAILED
        self.failure_reason = reason

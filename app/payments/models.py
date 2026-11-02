"""The payment of a cart."""

import uuid
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import CHAR, CheckConstraint, ForeignKey, Index, Numeric, Text, text
from sqlalchemy.orm import Mapped, composite, mapped_column, relationship

from app.errors import InvalidCartTotal, PaymentMethodNotFound
from app.models import BaseTrackUpdates, Cart, Money, UserPaymentMethod, status_in
from app.payments.errors import PaymentInProgress


class PaymentStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class Payment(BaseTrackUpdates):
    """A charge for a cart."""

    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount > 0", name="payments_amount_check"),
        CheckConstraint(status_in(*PaymentStatus), name="payments_status_check"),
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
                status_in(PaymentStatus.PENDING, PaymentStatus.SUCCEEDED)
            ),
        ),
        # Finds payments stuck in pending, to cancel them.
        Index(
            "ix_payments_pending_created_at",
            "created_at",
            postgresql_where=text(status_in(PaymentStatus.PENDING)),
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

    cart: Mapped[Cart] = relationship(backref="payments")
    payment_method: Mapped[UserPaymentMethod] = relationship()

    @classmethod
    def start(
        cls,
        cart: Cart,
        payment_method: UserPaymentMethod,
        total: Money,
    ) -> "Payment":
        if any(payment.is_pending for payment in cart.payments):
            raise PaymentInProgress("A payment for this cart is already in progress")
        if payment_method.user_id != cart.user_id:
            raise PaymentMethodNotFound("Payment method not found")
        if total.amount <= 0:
            raise InvalidCartTotal("Cart total must be positive")
        return cls(
            cart=cart,
            payment_method=payment_method,
            total=total,
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

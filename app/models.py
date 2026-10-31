"""SQLAlchemy models for the shop schema."""

import uuid
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
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


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


class CartStatus(StrEnum):
    ACTIVE = "active"
    CHECKED_OUT = "checked_out"
    ABANDONED = "abandoned"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class User(BaseTrackUpdates):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)

    carts: Mapped[list["Cart"]] = relationship(back_populates="user")
    payment_methods: Mapped[list["UserPaymentMethod"]] = relationship(
        back_populates="user"
    )


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
        CheckConstraint(
            "status IN ('active', 'checked_out', 'abandoned')",
            name="carts_status_check",
        ),
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

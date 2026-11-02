"""Stand-in for the existing total calculation service."""

import uuid
from sqlalchemy import func, select

from app.db import db_session
from app.errors import InvalidCartTotal
from app.models import CartItem, Money, Product


def calculate_total(cart_id: uuid.UUID) -> Money:
    """Mock: sum of the cart items, in the products' single currency."""
    rows = db_session.execute(
        select(func.sum(CartItem.quantity * CartItem.unit_price), Product.currency)
        .join(Product)
        .where(CartItem.cart_id == cart_id)
        .group_by(Product.currency)
    ).all()
    if len(rows) != 1:
        raise InvalidCartTotal("Cart must contain items in exactly one currency")
    amount, currency = rows[0]
    return Money(amount, currency)

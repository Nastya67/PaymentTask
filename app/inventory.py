"""Stock reservation for the products in a cart."""

import uuid

from sqlalchemy import func, select, update

from app.db import db_session
from app.errors import OutOfStock
from app.models import CartItem, Product


def reserve(cart_id: uuid.UUID) -> None:
    quantities = _cart_quantities_subquery(cart_id)
    rows = db_session.execute(
        select(Product.stock_quantity, quantities.c.quantity)
        .join(quantities, Product.id == quantities.c.product_id)
        .order_by(Product.id)
        .with_for_update(of=Product)
    ).all()
    if any(stock < quantity for stock, quantity in rows):
        raise OutOfStock("Some products are out of stock")
    _change_stock(cart_id, -1)


def release(cart_id: uuid.UUID) -> None:
    _change_stock(cart_id, 1)


def _cart_quantities_subquery(cart_id: uuid.UUID):
    """Quantity per product; a product can appear in several cart items."""
    return (
        select(CartItem.product_id, func.sum(CartItem.quantity).label("quantity"))
        .where(CartItem.cart_id == cart_id)
        .group_by(CartItem.product_id)
        .subquery()
    )


def _change_stock(cart_id: uuid.UUID, sign: int) -> None:
    quantities = _cart_quantities_subquery(cart_id)
    db_session.execute(
        update(Product)
        .where(Product.id == quantities.c.product_id)
        .values(stock_quantity=Product.stock_quantity + sign * quantities.c.quantity)
    )

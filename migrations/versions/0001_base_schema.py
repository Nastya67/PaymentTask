"""Base shop schema, as given by the task (without sample data, see db/seed.sql).

Revision ID: 0001
Revises:
Create Date: 2026-10-31

"""
from typing import Sequence, Union

from alembic import op

revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
CREATE EXTENSION IF NOT EXISTS "pgcrypto";  -- for gen_random_uuid()


-- Users of the shop.
CREATE TABLE users (
    id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    email      TEXT        NOT NULL UNIQUE,
    name       TEXT        NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- The physical products the shop sells.
CREATE TABLE products (
    id             UUID           PRIMARY KEY DEFAULT gen_random_uuid(),
    name           TEXT           NOT NULL,
    price          NUMERIC(12, 2) NOT NULL CHECK (price >= 0),
    currency       CHAR(3)        NOT NULL DEFAULT 'USD',
    stock_quantity INTEGER        NOT NULL DEFAULT 0 CHECK (stock_quantity >= 0),
    created_at     TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);


-- A shopping cart. A user can have many carts over time.
-- One cart is "active" at a time. The user pays for that cart.
-- Status values:
--   active       — the user can still add or remove products.
--   checked_out  — the user paid for this cart.
--   abandoned    — the user did not pay and started a new cart.
CREATE TABLE carts (
    id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID        NOT NULL REFERENCES users(id),
    status     TEXT        NOT NULL DEFAULT 'active'
                           CHECK (status IN ('active', 'checked_out', 'abandoned')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_carts_user_id ON carts(user_id);


-- The products a user added to a cart.
-- unit_price is stored on the row so the price at checkout is stable
-- if the product price changes later.
CREATE TABLE cart_items (
    id         UUID           PRIMARY KEY DEFAULT gen_random_uuid(),
    cart_id    UUID           NOT NULL REFERENCES carts(id) ON DELETE CASCADE,
    product_id UUID           NOT NULL REFERENCES products(id),
    quantity   INTEGER        NOT NULL CHECK (quantity > 0),
    unit_price NUMERIC(12, 2) NOT NULL,
    created_at TIMESTAMPTZ    NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_cart_items_cart_id ON cart_items(cart_id);


-- The payment methods a user has saved.
-- provider_token is the token from the external payment provider.
-- You send this token to the provider to charge the card.
-- The real card number is not stored — the provider holds it.
CREATE TABLE user_payment_methods (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id        UUID        NOT NULL REFERENCES users(id),
    provider_token TEXT        NOT NULL,
    last_four      CHAR(4),
    is_default     BOOLEAN     NOT NULL DEFAULT FALSE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_user_payment_methods_user_id ON user_payment_methods(user_id);
"""
    )


def downgrade() -> None:
    op.execute("DROP TABLE user_payment_methods, cart_items, carts, products, users")

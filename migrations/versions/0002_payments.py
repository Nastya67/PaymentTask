"""payments

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-31 12:33:46.575901

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('payments',
    sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
    sa.Column('cart_id', sa.UUID(), nullable=False),
    sa.Column('payment_method_id', sa.UUID(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('currency', sa.CHAR(length=3), nullable=False),
    sa.Column('status', sa.Text(), server_default=sa.text("'pending'"), nullable=False),
    sa.Column('provider_payment_id', sa.Text(), nullable=True),
    sa.Column('failure_reason', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status <> 'succeeded' OR provider_payment_id IS NOT NULL", name='payments_succeeded_has_provider_id'),
    sa.CheckConstraint("status IN ('pending', 'succeeded', 'failed')", name='payments_status_check'),
    sa.CheckConstraint('amount > 0', name='payments_amount_check'),
    sa.ForeignKeyConstraint(['cart_id'], ['carts.id'], ),
    sa.ForeignKeyConstraint(['payment_method_id'], ['user_payment_methods.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('provider_payment_id')
    )
    op.create_index('uq_payments_cart_id_active', 'payments', ['cart_id'], unique=True, postgresql_where=sa.text("status IN ('pending', 'succeeded')"))
    op.create_index('ix_payments_pending_created_at', 'payments', ['created_at'], unique=False, postgresql_where=sa.text("status = 'pending'"))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_payments_pending_created_at', table_name='payments', postgresql_where=sa.text("status = 'pending'"))
    op.drop_index('uq_payments_cart_id_active', table_name='payments', postgresql_where=sa.text("status IN ('pending', 'succeeded')"))
    op.drop_table('payments')

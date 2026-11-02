"""index pending payments

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-02 16:36:56.704760

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_index('ix_payments_pending_created_at', 'payments', ['created_at'], unique=False, postgresql_where=sa.text("status = 'pending'"))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_payments_pending_created_at', table_name='payments', postgresql_where=sa.text("status = 'pending'"))

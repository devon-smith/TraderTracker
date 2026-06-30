"""trade.is_taker (on-chain aggressor signal)

Revision ID: 0003_trade_is_taker
Revises: 0002_derived_tables
Create Date: 2026-06-30
"""

from alembic import op

revision = "0003_trade_is_taker"
down_revision = "0002_derived_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 0001's create_all reflects the current model (which already includes
    # is_taker), so guard with IF NOT EXISTS for fresh DBs; pre-0003 DBs get it added.
    op.execute("ALTER TABLE trade ADD COLUMN IF NOT EXISTS is_taker boolean")


def downgrade() -> None:
    op.execute("ALTER TABLE trade DROP COLUMN IF EXISTS is_taker")

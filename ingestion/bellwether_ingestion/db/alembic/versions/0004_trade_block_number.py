"""trade.block_number (on-chain block for copy-chain block-gap confirmation)

Revision ID: 0004_trade_block_number
Revises: 0003_trade_is_taker
Create Date: 2026-06-30
"""

from alembic import op

revision = "0004_trade_block_number"
down_revision = "0003_trade_is_taker"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE trade ADD COLUMN IF NOT EXISTS block_number bigint")


def downgrade() -> None:
    op.execute("ALTER TABLE trade DROP COLUMN IF EXISTS block_number")

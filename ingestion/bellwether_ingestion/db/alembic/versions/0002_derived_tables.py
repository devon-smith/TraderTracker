"""derived tables: candidate_score + kalshi_flow

Revision ID: 0002_derived_tables
Revises: 0001_initial
Create Date: 2026-06-30

create_all is idempotent (checkfirst), so this creates only the newly-added
derived tables without touching the existing schema.
"""

from alembic import op
from bellwether_ingestion.db.models import Base

revision = "0002_derived_tables"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(op.get_bind())


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS candidate_score")
    op.execute("DROP TABLE IF EXISTS kalshi_flow")

"""initial canonical schema + TimescaleDB hypertables

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-30

Creates the enum types, all canonical tables, and converts the time-series tables
(trade, position_event, event) into TimescaleDB hypertables. Idempotent enough to
re-run cleanly (extension + create_hypertable use IF/NOT EXISTS).
"""

from alembic import op
from bellwether_ingestion.db.models import HYPERTABLES, Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
    # Create enums + tables + indexes from the ORM metadata (single source of truth).
    Base.metadata.create_all(bind)
    for table in HYPERTABLES:
        op.execute(
            f"SELECT create_hypertable('{table}', 'ts', "
            "if_not_exists => TRUE, migrate_data => TRUE)"
        )


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind)
    for enum_name in ("position_event_type", "source_enum", "side_enum", "platform_enum"):
        op.execute(f"DROP TYPE IF EXISTS {enum_name}")

"""Programmatic Alembic entrypoints so `tt db init` (and tests) can migrate without
a shell. Migrations run with a synchronous psycopg2 driver; the app uses asyncpg.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from alembic import command
from alembic.config import Config

from .session import sync_dsn

_ALEMBIC_DIR = Path(__file__).resolve().parent / "alembic"


def alembic_config(url: Optional[str] = None) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(_ALEMBIC_DIR))
    cfg.set_main_option("sqlalchemy.url", sync_dsn(url))
    return cfg


def upgrade_head(url: Optional[str] = None) -> None:
    command.upgrade(alembic_config(url), "head")


def downgrade_base(url: Optional[str] = None) -> None:
    command.downgrade(alembic_config(url), "base")

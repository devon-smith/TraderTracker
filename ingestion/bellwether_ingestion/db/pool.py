"""Thin async Postgres/TimescaleDB access layer (asyncpg).

Kept minimal on purpose: a connection pool, a migration runner that applies the
SQL files in infra/db/migrations in lexical order, and a batched trade upsert.
Heavier query logic belongs in the analytics package.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import asyncpg

from .normalize import canonical_trade_columns

DEFAULT_DSN = os.environ.get(
    "DATABASE_URL", "postgresql://bellwether:bellwether@localhost:5432/bellwether"
)

# Repo-root-relative path to the migrations dir.
_MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "infra" / "db" / "migrations"


class Database:
    def __init__(self, dsn: str = DEFAULT_DSN):
        self.dsn = dsn
        self._pool: Optional[asyncpg.Pool] = None

    async def connect(self) -> None:
        if self._pool is None:
            self._pool = await asyncpg.create_pool(self.dsn, min_size=1, max_size=10)

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    @property
    def pool(self) -> asyncpg.Pool:
        if self._pool is None:
            raise RuntimeError("Database.connect() must be awaited before use")
        return self._pool

    async def apply_migrations(self, migrations_dir: Path = _MIGRATIONS_DIR) -> list[str]:
        """Apply every *.sql file in lexical order. Migrations must be idempotent."""
        applied: list[str] = []
        files = sorted(migrations_dir.glob("*.sql"))
        async with self.pool.acquire() as conn:
            for f in files:
                await conn.execute(f.read_text())
                applied.append(f.name)
        return applied

    async def insert_trades(self, rows: Iterable[dict]) -> int:
        """Batch-insert canonical trade rows (dicts from db.normalize). Dedups on
        (platform, wallet_id, tx_hash, asset, ts) via the table's unique index."""
        records = []
        for r in rows:
            ts = datetime.fromtimestamp(int(r["ts_epoch"]), tz=timezone.utc)
            records.append(
                (
                    r["platform"],
                    r["wallet_id"],
                    r["market_id"],
                    r["condition_id"],
                    r["asset"],
                    r["side"],
                    r["size"],
                    r["price"],
                    r["notional"],
                    r["outcome"],
                    r["outcome_index"],
                    r["tx_hash"],
                    ts,
                )
            )
        if not records:
            return 0
        cols = ", ".join(canonical_trade_columns[:-1] + ("ts",))
        placeholders = ", ".join(f"${i}" for i in range(1, len(records[0]) + 1))
        sql = (
            f"INSERT INTO trade ({cols}) VALUES ({placeholders}) "
            f"ON CONFLICT DO NOTHING"
        )
        async with self.pool.acquire() as conn:
            await conn.executemany(sql, records)
        return len(records)

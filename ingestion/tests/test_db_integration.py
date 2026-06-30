"""DB-integration tests. Skipped unless DATABASE_URL points at a reachable
Postgres/TimescaleDB. Run locally against the compose db (or a throwaway
container); the CI `migrations` job covers schema apply separately.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import os

import pytest

DSN = os.environ.get("DATABASE_URL")


def _db_available() -> bool:
    if not DSN:
        return False
    try:
        import psycopg2

        conn = psycopg2.connect(DSN)
        conn.close()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _db_available(), reason="no DATABASE_URL / DB unreachable"
)


def test_schema_hypertables_dedup_and_idempotency():
    from bellwether_ingestion.db import (
        Trade,
        downgrade_base,
        make_engine,
        make_sessionmaker,
        repo,
        upgrade_head,
    )
    from sqlalchemy import insert, text
    from sqlalchemy.exc import IntegrityError

    downgrade_base()  # clean slate
    upgrade_head()

    async def _run():
        engine = make_engine(DSN)
        Session = make_sessionmaker(engine)
        try:
            async with Session() as s:
                # hypertables registered
                rows = await s.execute(
                    text("SELECT hypertable_name FROM timescaledb_information.hypertables")
                )
                names = {r[0] for r in rows.all()}
                assert {"trade", "position_event", "event"} <= names

                wid = await repo.upsert_wallet(s, "manifold", "u-test")
                mid = await repo.upsert_market(
                    s,
                    "manifold",
                    {"external_id": "m-test", "title": "t", "category": "c", "is_multi_outcome": False},
                )
                await s.commit()

                # upsert is idempotent: same external id returns same surrogate id
                wid2 = await repo.upsert_wallet(s, "manifold", "u-test")
                assert wid == wid2

                row = {
                    "dedup_key": "itest:1",
                    "ts": dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc),
                    "platform": "manifold",
                    "wallet_id": wid,
                    "market_id": mid,
                    "side": "BUY",
                    "outcome": "YES",
                    "size": 1.0,
                    "price": 0.5,
                    "notional": 0.5,
                    "source": "manifold_api",
                }
                n1 = await repo.insert_trades(s, [row])
                await s.commit()
                n2 = await repo.insert_trades(s, [row])
                await s.commit()
                assert n1 == 1  # first insert lands
                assert n2 == 0  # idempotent: duplicate skipped

                # a PLAIN insert of the same dedup PK must raise (constraint exists)
                raised = False
                try:
                    await s.execute(insert(Trade).values(**row))
                    await s.commit()
                except IntegrityError:
                    await s.rollback()
                    raised = True
                assert raised
            return n1, n2
        finally:
            await engine.dispose()

    n1, n2 = asyncio.run(_run())
    assert (n1, n2) == (1, 0)

"""Async persistence helpers shared by the per-venue ingesters.

Upserts for reference entities (wallet/market), idempotent bulk inserts for the
time-series tables (ON CONFLICT DO NOTHING on the dedup PK), and ingestion_run
bookkeeping. Loaders resolve external ids -> surrogate ids, then call these.
"""

from __future__ import annotations

import datetime as dt
from typing import Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from .models import IngestionRun, Market, PositionEvent, Trade, Wallet


def _now() -> dt.datetime:
    return dt.datetime.now(tz=dt.timezone.utc)


async def upsert_wallet(
    session: AsyncSession,
    platform: str,
    external_id: str,
    handle: Optional[str] = None,
    pseudonym: Optional[str] = None,
    ts: Optional[dt.datetime] = None,
) -> int:
    stmt = pg_insert(Wallet).values(
        platform=platform,
        external_id=external_id,
        handle=handle,
        pseudonym=pseudonym,
        first_seen=ts,
        last_seen=ts,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_wallet_platform_external",
        set_={
            "last_seen": func.greatest(
                func.coalesce(Wallet.last_seen, stmt.excluded.last_seen),
                stmt.excluded.last_seen,
            ),
            "handle": func.coalesce(stmt.excluded.handle, Wallet.handle),
        },
    ).returning(Wallet.id)
    return (await session.execute(stmt)).scalar_one()


async def upsert_market(session: AsyncSession, platform: str, fields: dict) -> int:
    values = {"platform": platform, **fields}
    stmt = pg_insert(Market).values(**values)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_market_platform_external",
        set_={
            "title": func.coalesce(stmt.excluded.title, Market.title),
            "slug": func.coalesce(stmt.excluded.slug, Market.slug),
            "category": func.coalesce(stmt.excluded.category, Market.category),
            "raw_category": func.coalesce(stmt.excluded.raw_category, Market.raw_category),
            "resolved_at": func.coalesce(stmt.excluded.resolved_at, Market.resolved_at),
            "resolution": func.coalesce(stmt.excluded.resolution, Market.resolution),
            "is_multi_outcome": stmt.excluded.is_multi_outcome,
        },
    ).returning(Market.id)
    return (await session.execute(stmt)).scalar_one()


# asyncpg caps a single statement at 32767 bind params; chunk large batches so
# a full-history backfill (thousands of rows/wallet) doesn't blow the limit.
_PG_MAX_PARAMS = 32767


def _chunk_size(row: dict) -> int:
    cols = max(1, len(row))
    return max(1, _PG_MAX_PARAMS // cols)


async def _insert_chunked(session: AsyncSession, model, rows: list[dict]) -> int:
    if not rows:
        return 0
    size = _chunk_size(rows[0])
    inserted = 0
    for i in range(0, len(rows), size):
        chunk = rows[i : i + size]
        stmt = (
            pg_insert(model)
            .values(chunk)
            .on_conflict_do_nothing(index_elements=["dedup_key", "ts"])
            .returning(model.dedup_key)
        )
        result = await session.execute(stmt)
        inserted += len(result.fetchall())
    return inserted


async def insert_trades(session: AsyncSession, rows: list[dict]) -> int:
    """Bulk idempotent insert. Returns the number of rows actually inserted."""
    return await _insert_chunked(session, Trade, rows)


async def insert_position_events(session: AsyncSession, rows: list[dict]) -> int:
    return await _insert_chunked(session, PositionEvent, rows)


async def market_id_map(session: AsyncSession, platform: str, external_ids: Iterable[str]) -> dict[str, int]:
    ids = [e for e in set(external_ids) if e]
    if not ids:
        return {}
    rows = await session.execute(
        select(Market.external_id, Market.id).where(
            Market.platform == platform, Market.external_id.in_(ids)
        )
    )
    return {ext: mid for ext, mid in rows.all()}


async def start_run(session: AsyncSession, source: str, target: str) -> int:
    stmt = (
        pg_insert(IngestionRun)
        .values(source=source, target=target, started_at=_now(), status="running")
        .returning(IngestionRun.id)
    )
    rid = (await session.execute(stmt)).scalar_one()
    await session.commit()
    return rid


async def finish_run(
    session: AsyncSession,
    run_id: int,
    status: str,
    rows_written: int,
    cursor: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    run = await session.get(IngestionRun, run_id)
    if run is None:
        return
    run.finished_at = _now()
    run.status = status
    run.rows_written = rows_written
    run.cursor = cursor
    run.error = error
    await session.commit()

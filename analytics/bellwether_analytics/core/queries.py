"""Load a canonical trades DataFrame from the DB for the analytics primitives.

Joins trade -> market -> wallet so every row carries the wallet external id, the
market category, and the market resolution needed to settle P&L.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
from bellwether_ingestion.db.session import sync_dsn
from sqlalchemy import create_engine, text

_SQL = """
SELECT
    w.external_id AS wallet,
    m.external_id AS market,
    m.category    AS category,
    m.slug        AS slug,
    t.outcome     AS outcome,
    t.side::text  AS side,
    t.size        AS size,
    t.price       AS price,
    t.notional    AS notional,
    t.ts          AS ts,
    t.source::text AS source,
    t.is_taker    AS is_taker,
    t.block_number AS block_number,
    m.resolution  AS resolution,
    m.resolved_at AS resolved_at
FROM trade t
LEFT JOIN market m ON m.id = t.market_id
LEFT JOIN wallet w ON w.id = t.wallet_id
WHERE (:platform IS NULL OR t.platform = CAST(:platform AS platform_enum))
  AND (:wallet IS NULL OR w.external_id = :wallet)
"""


_EVENTS_SQL = """
SELECT
    w.external_id     AS wallet,
    m.external_id     AS market,
    m.category        AS category,
    pe.event_type::text AS event_type,
    pe.size           AS size,
    pe.value          AS value,
    pe.ts             AS ts
FROM position_event pe
LEFT JOIN market m ON m.id = pe.market_id
LEFT JOIN wallet w ON w.id = pe.wallet_id
WHERE (:platform IS NULL OR pe.platform = CAST(:platform AS platform_enum))
  AND (:wallet IS NULL OR w.external_id = :wallet)
"""


def load_trades_df(
    dsn: Optional[str] = None,
    platform: Optional[str] = None,
    wallet_external: Optional[str] = None,
) -> pd.DataFrame:
    engine = create_engine(sync_dsn(dsn))
    try:
        with engine.connect() as conn:
            df = pd.read_sql(
                text(_SQL),
                conn,
                params={"platform": platform, "wallet": wallet_external},
                parse_dates=["ts", "resolved_at"],
            )
    finally:
        engine.dispose()
    return df


def load_events_df(
    dsn: Optional[str] = None,
    platform: Optional[str] = None,
    wallet_external: Optional[str] = None,
) -> pd.DataFrame:
    engine = create_engine(sync_dsn(dsn))
    try:
        with engine.connect() as conn:
            df = pd.read_sql(
                text(_EVENTS_SQL),
                conn,
                params={"platform": platform, "wallet": wallet_external},
                parse_dates=["ts"],
            )
    finally:
        engine.dispose()
    return df

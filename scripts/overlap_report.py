"""Co-trading overlap report for the seed candidate pool (goal outcome 4).

Verifies the pool actually co-trades before it's declared usable: builds the
shared-market graph over the loaded `trade` table and reports the fraction of
wallets with >=3 shared-market neighbors (the minimum the block-gap/copy-chain
logic needs). Pure read query — no detection logic.
"""

from __future__ import annotations

import os

from bellwether_ingestion.db import make_engine
from sqlalchemy import text

# Distinct (wallet, market) participation -> undirected co-trading pairs with the
# count of markets each pair shares -> per-wallet distinct-neighbor counts.
SQL = text(
    """
WITH wm AS (
    SELECT DISTINCT wallet_id, market_id
    FROM trade
    WHERE market_id IS NOT NULL AND wallet_id IS NOT NULL
),
pairs AS (
    SELECT a.wallet_id AS w1, b.wallet_id AS w2, count(*) AS shared
    FROM wm a
    JOIN wm b ON a.market_id = b.market_id AND a.wallet_id < b.wallet_id
    GROUP BY a.wallet_id, b.wallet_id
),
neigh AS (
    SELECT w1 AS w, w2 AS o FROM pairs
    UNION ALL
    SELECT w2 AS w, w1 AS o FROM pairs
),
wallet_neighbors AS (
    SELECT w, count(DISTINCT o) AS n
    FROM neigh
    GROUP BY w
),
loaded AS (
    SELECT DISTINCT wallet_id FROM trade WHERE wallet_id IS NOT NULL
)
SELECT
    (SELECT count(*) FROM loaded)                                   AS wallets_with_trades,
    (SELECT count(*) FROM wallet_neighbors WHERE n >= 1)            AS ge1_neighbor,
    (SELECT count(*) FROM wallet_neighbors WHERE n >= 3)            AS ge3_neighbors,
    (SELECT count(*) FROM wallet_neighbors WHERE n >= 10)           AS ge10_neighbors,
    (SELECT count(*) FROM pairs)                                    AS co_trading_pairs,
    (SELECT count(*) FROM pairs WHERE shared >= 3)                  AS pairs_share_ge3,
    (SELECT round(avg(n), 1) FROM wallet_neighbors)                 AS avg_neighbors,
    (SELECT max(n) FROM wallet_neighbors)                           AS max_neighbors,
    (SELECT round(avg(shared), 2) FROM pairs)                       AS avg_shared_markets,
    (SELECT max(shared) FROM pairs)                                 AS max_shared_markets
"""
)

DIST_SQL = text(
    """
WITH wm AS (
    SELECT DISTINCT wallet_id, market_id FROM trade
    WHERE market_id IS NOT NULL AND wallet_id IS NOT NULL
),
pairs AS (
    SELECT a.wallet_id AS w1, b.wallet_id AS w2, count(*) AS shared
    FROM wm a JOIN wm b ON a.market_id = b.market_id AND a.wallet_id < b.wallet_id
    GROUP BY a.wallet_id, b.wallet_id
)
SELECT
    width_bucket(shared, 1, 21, 20) AS bucket,
    count(*) AS pair_count
FROM pairs
GROUP BY bucket ORDER BY bucket
"""
)


def main() -> None:
    import asyncio

    eng = make_engine(os.environ.get("DATABASE_URL"))

    async def _go():
        async with eng.connect() as c:
            await c.execute(text("SET statement_timeout = '180s'"))
            row = (await c.execute(SQL)).mappings().one()
            dist = (await c.execute(DIST_SQL)).all()
        await eng.dispose()
        return row, dist

    row, dist = asyncio.run(_go())

    wt = row["wallets_with_trades"] or 0
    ge3 = row["ge3_neighbors"] or 0
    frac = (ge3 / wt) if wt else 0.0
    print("=" * 64)
    print("CO-TRADING OVERLAP REPORT")
    print("=" * 64)
    print(f"wallets with >=1 trade loaded : {wt}")
    print(f"  >=1 shared-market neighbor  : {row['ge1_neighbor']}")
    print(f"  >=3 shared-market neighbors : {ge3}   ({frac:.1%} of pool)")
    print(f"  >=10 shared-market neighbors: {row['ge10_neighbors']}")
    print(f"avg / max neighbors per wallet: {row['avg_neighbors']} / {row['max_neighbors']}")
    print(f"co-trading pairs (share >=1 mkt): {row['co_trading_pairs']}")
    print(f"  pairs sharing >=3 markets    : {row['pairs_share_ge3']}")
    print(f"avg / max shared markets / pair: {row['avg_shared_markets']} / {row['max_shared_markets']}")
    print("-" * 64)
    print("pairwise shared-market-count distribution (bucket = #shared markets):")
    for b, n in dist:
        label = f"{b}" if b and b <= 20 else "21+"
        print(f"  shared={label:>3}: {n}")
    print("=" * 64)
    verdict = "USABLE" if frac >= 0.5 else ("MARGINAL" if frac >= 0.2 else "TOO DIFFUSE")
    print(f"VERDICT: {verdict} — {frac:.1%} of the pool has >=3 co-trading neighbors")


if __name__ == "__main__":
    main()

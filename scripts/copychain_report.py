"""Memory-bounded null-model copy-chain detection for one market family.

The `tt strategy leadlag/copychains` CLI loads all 1.67M trades at once and OOMs
the 4GB box. Copy-chains live *within* a recurring family, so we scope the load
to one family (e.g. eth-updown-5m: ~145k trades) and run the SAME
confirmed_copy_chains pipeline. block_number is null, so the on-chain block-gap
guard no-ops and we get the null-model-filtered (statistical) survivors — the
first of the two guards. No new detection logic.

Usage: python scripts/copychain_report.py [family-stem]   # default eth-updown-5m
"""

from __future__ import annotations

import sys

import pandas as pd
from bellwether_analytics.core.queries import sync_dsn
from bellwether_analytics.strategy import confirmed_copy_chains
from sqlalchemy import create_engine, text

# Mirrors core.queries._SQL column schema (what the detector expects), scoped to a
# single market family so the load fits in memory.
FAMILY_SQL = """
SELECT w.external_id AS wallet, m.external_id AS market, m.category AS category,
       m.slug AS slug, t.outcome AS outcome, t.side::text AS side, t.size AS size,
       t.price AS price, t.notional AS notional, t.ts AS ts, t.source::text AS source,
       t.is_taker AS is_taker, t.block_number AS block_number,
       m.resolution AS resolution, m.resolved_at AS resolved_at
FROM trade t
JOIN market m ON m.id = t.market_id
JOIN wallet w ON w.id = t.wallet_id
WHERE t.platform = 'polymarket' AND m.slug LIKE :fam
"""


def main() -> None:
    fam = sys.argv[1] if len(sys.argv) > 1 else "eth-updown-5m"
    eng = create_engine(sync_dsn(None))
    with eng.connect() as c:
        df = pd.read_sql(text(FAMILY_SQL), c, params={"fam": f"{fam}-%"}, parse_dates=["ts", "resolved_at"])
    eng.dispose()
    print(f"[copychain] family={fam}  trades={len(df)}  "
          f"wallets={df['wallet'].nunique()}  markets={df['market'].nunique()}")

    chains = confirmed_copy_chains(df, max_lag_seconds=120.0, min_events=3, same_side=True)
    print("=" * 60)
    print(f"NULL-MODEL COPY-CHAINS — {fam} (block-gap guard pending on-chain)")
    print("=" * 60)
    if chains.empty:
        print("  no (leader, follower) pair survived the permutation null model")
        return
    print(f"  {len(chains)} surviving (leader -> follower) pairs")
    cols = [c for c in ("leader", "follower", "follow_events", "null_threshold", "p_value") if c in chains.columns]
    for _, r in chains.head(20).iterrows():
        parts = []
        for c in cols:
            v = r[c]
            parts.append(f"{c}={v:.3f}" if isinstance(v, float) else f"{c}={str(v)[:12]}")
        print("   " + "  ".join(parts))


if __name__ == "__main__":
    main()

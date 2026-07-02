"""Outcome 2: apply the on-chain block-gap guard to the null-model copy-chain
survivors, and report how many pass vs are rejected.

Reuses the real detection functions verbatim: detect_followers_significant (the
permutation null model) then confirm_block_gaps (positive, small, CONSISTENT gap
across >= N shared markets). Also reports bidirectionality among the confirmed
pairs — A<->B both confirmed is the fingerprint of shared-signal co-reaction, not
one-way copying (the decisive copy/shared-signal test is outcome 3).

Usage: python scripts/blockgap_verdict.py [family-stem]   # default eth-updown-5m
"""

from __future__ import annotations

import sys

import pandas as pd
from bellwether_analytics.core.queries import sync_dsn
from bellwether_analytics.strategy import confirm_block_gaps, detect_followers_significant
from bellwether_analytics.strategy.archetypes import StrategyConfig
from sqlalchemy import create_engine, text

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
    n_block = int(df["block_number"].notna().sum())
    print(f"[blockgap] family={fam}  trades={len(df)}  wallets={df['wallet'].nunique()}  "
          f"rows_with_block={n_block} ({n_block/max(1,len(df)):.1%})")

    cfg = StrategyConfig()
    print(f"[blockgap] guard: gap in (0,{cfg.leadlag_max_block_gap}] blocks, "
          f"std<={cfg.leadlag_max_block_gap_std}, >={cfg.leadlag_min_block_confirmations} markets")

    sig = detect_followers_significant(df, config=cfg)
    conf = confirm_block_gaps(df, sig, config=cfg)

    total = len(conf)
    confirmed = conf[conf["block_confirmed"] == True]  # noqa: E712
    rejected = conf[conf["block_confirmed"] == False]  # noqa: E712
    na = conf[conf["block_confirmed"].isna()]

    print("=" * 62)
    print(f"NULL-MODEL SURVIVORS: {total}")
    print(f"  block-gap CONFIRMED : {len(confirmed)}  ({len(confirmed)/max(1,total):.1%})")
    print(f"  block-gap REJECTED  : {len(rejected)}  (gap absent / too large / inconsistent)")
    print(f"  no block data (NA)  : {len(na)}")
    print("-" * 62)

    if not confirmed.empty:
        cset = set(zip(confirmed["leader"], confirmed["follower"]))
        bidir = {tuple(sorted(p)) for p in cset if (p[1], p[0]) in cset}
        print(f"bidirectional among confirmed (A<->B both pass): {len(bidir)} pairs "
              f"-> shared-signal fingerprint, not one-way copying")
        print("block_gap_median distribution (confirmed pairs):")
        print(confirmed["block_gap_median"].describe().to_string())
        print("-" * 62)
        print("top confirmed pairs by follow_events:")
        cols = ["leader", "follower", "follow_events", "block_gap_median",
                "block_gap_std", "n_block_confirmations"]
        cols = [c for c in cols if c in confirmed.columns]
        for _, r in confirmed.sort_values("follow_events", ascending=False).head(15).iterrows():
            print("  " + "  ".join(
                f"{c}={r[c]:.2f}" if isinstance(r[c], float) else f"{c}={str(r[c])[:12]}" for c in cols))
    print("=" * 62)


if __name__ == "__main__":
    main()

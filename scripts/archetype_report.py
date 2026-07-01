"""Memory-bounded archetype distribution for the co-trading pool.

The `tt strategy classify` CLI loads all 1.67M trades into pandas at once, which
OOMs the 4GB box. Archetype features are per-wallet independent, so we batch:
load each active wallet's trades/events, run the SAME extract_features + classify,
and concat the tiny per-wallet feature rows. No new detection logic — it reuses
bellwether_analytics.strategy verbatim.
"""

from __future__ import annotations

import collections

import pandas as pd
from bellwether_analytics.core.queries import load_events_df, load_trades_df, sync_dsn
from bellwether_analytics.strategy import classify, extract_features
from sqlalchemy import create_engine, text

MIN_TRADES = 50


def main() -> None:
    eng = create_engine(sync_dsn(None))
    with eng.connect() as c:
        wallets = [r[0] for r in c.execute(text(
            "SELECT w.external_id FROM wallet w JOIN trade t ON t.wallet_id = w.id "
            "WHERE w.platform = 'polymarket' "
            "GROUP BY w.external_id HAVING count(*) >= :m ORDER BY count(*) DESC"
        ), {"m": MIN_TRADES})]
    eng.dispose()
    print(f"[archetype] classifying {len(wallets)} active wallets (>= {MIN_TRADES} trades)")

    feats = []
    for i, w in enumerate(wallets):
        try:
            tr = load_trades_df(platform="polymarket", wallet_external=w)
            if tr.empty:
                continue
            ev = load_events_df(platform="polymarket", wallet_external=w)
            feats.append(extract_features(tr, ev))
        except Exception as e:  # noqa: BLE001
            print(f"  skip {w[:10]}: {e}")
        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{len(wallets)}")

    features = pd.concat(feats)
    labeled = classify(features)
    dist = collections.Counter(labeled["archetype"])
    total = sum(dist.values())
    print("=" * 56)
    print("ARCHETYPE DISTRIBUTION — active co-trading pool")
    print("=" * 56)
    for arche, n in dist.most_common():
        print(f"  {arche:22s} {n:4d}  ({n/total:.1%})")
    print("-" * 56)
    print(f"  total classified: {total}")
    # a couple of behavioral medians for context
    for col in ("trades_per_day", "net_direction", "roundtrip_ratio"):
        if col in features.columns:
            print(f"  median {col:16s}: {features[col].median():.2f}")


if __name__ == "__main__":
    main()

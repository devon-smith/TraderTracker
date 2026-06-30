import pandas as pd
from bellwether_analytics.strategy import (
    classify,
    cluster_wallets,
    compare_to_rules,
    extract_features,
    recommend_thresholds,
)

T0 = pd.Timestamp("2026-01-01T00:00:00Z")


def _t(wallet, market, slug, side, notional, ts, category="crypto"):
    return dict(wallet=wallet, market=market, slug=slug, category=category, outcome="YES",
                side=side, size=notional / 0.5, price=0.5, notional=notional, ts=ts,
                resolution=None, resolved_at=pd.NaT)


def _separable_population():
    rows = []
    # 3 scalper-like wallets: rapid, one btc-updown-5m family
    for w in ("S1", "S2", "S3"):
        for i in range(60):
            rows.append(_t(w, f"{w}m{i}", f"btc-updown-5m-{i}", "BUY" if i % 2 else "SELL", 50,
                           T0 + pd.Timedelta(seconds=30 * i)))
    # 3 accumulator-like wallets: slow, directional, distinct sports markets
    for w in ("A1", "A2", "A3"):
        for i in range(30):
            rows.append(_t(w, f"{w}a{i}", f"sports-game-{i}", "BUY", 500,
                           T0 + pd.Timedelta(hours=6 * i), category="sports"))
    return pd.DataFrame(rows)


def test_clusters_align_with_rule_labels_on_separable_data():
    feats = extract_features(_separable_population())
    labeled = classify(feats)
    clusters = cluster_wallets(feats, k=2, seed=0)
    cmp = compare_to_rules(clusters, labeled["archetype"])
    # clearly separable synthetic archetypes -> high agreement
    assert cmp["agreement"] >= 0.8
    assert cmp["contingency"].shape[0] == 2  # two clusters
    recs = recommend_thresholds(feats, cmp)
    assert isinstance(recs, list) and recs

"""The null model must PASS a consistent copier and REJECT synchronized reaction
(many wallets filling near-simultaneously with no consistent leader)."""

import pandas as pd
from bellwether_analytics.strategy import detect_followers_significant
from bellwether_analytics.strategy.archetypes import StrategyConfig

T0 = pd.Timestamp("2026-01-01T00:00:00Z")


def _t(wallet, market, side, ts):
    return dict(wallet=wallet, market=market, slug=f"m-{market}", category="x", outcome="YES",
                side=side, size=100, price=0.5, notional=50, ts=ts,
                resolution=None, resolved_at=pd.NaT)


def test_consistent_follower_survives_null():
    rows = []
    # 12 markets: LEADER fills, FOLLOWER copies 10s later. Consistent ordering.
    for i in range(12):
        mkt = f"mk{i}"
        rows.append(_t("LEADER", mkt, "BUY", T0 + pd.Timedelta(minutes=i)))
        rows.append(_t("FOLLOWER", mkt, "BUY", T0 + pd.Timedelta(minutes=i, seconds=10)))
    cfg = StrategyConfig(leadlag_n_permutations=200, leadlag_significance=0.95)
    out = detect_followers_significant(pd.DataFrame(rows), max_lag_seconds=60, min_events=3,
                                       config=cfg, seed=1)
    assert not out.empty
    top = out.iloc[0]
    assert (top["leader"], top["follower"]) == ("LEADER", "FOLLOWER")
    assert top["follow_events"] == 12
    assert top["follow_events"] > top["null_threshold"]


def test_synchronized_reaction_is_rejected():
    import random

    rng = random.Random(0)
    rows = []
    # 30 markets, 3 wallets fill simultaneously (same ts) in a RANDOM order each
    # market -> no consistent leader. This is shared-info reaction, not copying.
    wallets = ["A", "B", "C"]
    for i in range(30):
        order = wallets[:]
        rng.shuffle(order)
        for w in order:
            rows.append(_t(w, f"mk{i}", "BUY", T0 + pd.Timedelta(minutes=i)))
    cfg = StrategyConfig(leadlag_n_permutations=300, leadlag_significance=0.95)
    out = detect_followers_significant(pd.DataFrame(rows), max_lag_seconds=30, min_events=3,
                                       config=cfg, seed=1)
    # No pair should survive the null at 95% (no real leader).
    assert out.empty

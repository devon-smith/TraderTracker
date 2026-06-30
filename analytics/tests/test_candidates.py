import numpy as np
import pandas as pd
from bellwether_analytics.candidates import PoolConfig, build_pool, trackability_score, walk_forward

T0 = pd.Timestamp("2024-01-01T00:00:00Z")


def _resolved_trade(wallet, market, cat, outcome, resolution, size, price, ts):
    return dict(
        wallet=wallet, market=market, category=cat, outcome=outcome, side="BUY",
        size=size, price=price, notional=size * price, ts=ts,
        resolution=resolution, resolved_at=ts + pd.Timedelta(days=1),
    )


def test_trackability_prefers_slow_deep_over_fast_thin():
    rows = []
    # SLOW: 3 big trades spread over 30 days
    for i, d in enumerate([0, 15, 30]):
        rows.append(dict(wallet="SLOW", market=f"m{i}", category="x", outcome="YES", side="BUY",
                         size=1000, price=0.5, notional=500, ts=T0 + pd.Timedelta(days=d),
                         resolution=None, resolved_at=pd.NaT))
    # FAST: 50 tiny trades within a single day
    for i in range(50):
        rows.append(dict(wallet="FAST", market=f"f{i}", category="x", outcome="YES", side="BUY",
                         size=1, price=0.5, notional=0.5, ts=T0 + pd.Timedelta(minutes=i),
                         resolution=None, resolved_at=pd.NaT))
    ts = trackability_score(pd.DataFrame(rows))
    assert ts.loc["SLOW", "trackability"] > ts.loc["FAST", "trackability"]
    assert ts.loc["FAST", "trades_per_day"] > ts.loc["SLOW", "trades_per_day"]


def test_build_pool_applies_baseline_filters():
    rows = []
    # SKILL: 60 resolved markets, all wins -> passes
    for i in range(60):
        rows.append(_resolved_trade("SKILL", f"s{i}", "crypto", "YES", "YES", 10, 0.5,
                                    T0 + pd.Timedelta(hours=i)))
    # WEAK: 60 resolved, all losses -> fails win-rate
    for i in range(60):
        rows.append(_resolved_trade("WEAK", f"w{i}", "politics", "YES", "NO", 10, 0.5,
                                    T0 + pd.Timedelta(hours=i)))
    # SMALL: 5 resolved -> fails min_resolved_trades
    for i in range(5):
        rows.append(_resolved_trade("SMALL", f"x{i}", "sports", "YES", "YES", 10, 0.5,
                                    T0 + pd.Timedelta(hours=i)))
    pool = build_pool(pd.DataFrame(rows), config=PoolConfig(min_resolved_trades=50, min_win_rate=0.55))
    assert list(pool.index) == ["SKILL"]


def test_walk_forward_edge_positive_and_shuffled_control_smaller():
    rows = []
    # 6 wallets. Train (Jan): skilled (W3-W5) win both, weak (W0-W2) lose both.
    # Test (Jul): same skill -> skilled win, weak lose. Train rank should predict test.
    for w in range(6):
        skilled = w >= 3
        for m in range(2):  # train resolved markets
            res = "YES" if skilled else "NO"
            rows.append(_resolved_trade(f"W{w}", f"tr{w}_{m}", "x", "YES", res, 10, 0.5,
                                        T0 + pd.Timedelta(days=m)))
        for m in range(2):  # test resolved markets (after split)
            res = "YES" if skilled else "NO"
            rows.append(_resolved_trade(f"W{w}", f"te{w}_{m}", "x", "YES", res, 10, 0.5,
                                        pd.Timestamp("2024-07-01T00:00:00Z") + pd.Timedelta(days=m)))
    df = pd.DataFrame(rows)
    out = walk_forward(df, split_ts="2024-06-01", seed=3)
    assert out["edge"] > 0                       # train rank predicts test performance
    assert out["edge_shuffled"] < out["edge"]    # shuffled control destroys the edge
    assert out["n"] == 6


def test_walk_forward_handles_insufficient_data():
    df = pd.DataFrame([_resolved_trade("W", "m", "x", "YES", "YES", 1, 0.5, T0)])
    out = walk_forward(df, split_ts="2024-06-01")
    assert np.isnan(out["edge"])

import pandas as pd
from bellwether_analytics.experiments import copyable_score, pair_copy_metrics, rank_leaders

T0 = pd.Timestamp("2026-01-01T00:00:00Z")


def _t(wallet, market, side, price, ts):
    return dict(wallet=wallet, market=market, slug=f"m-{market}", category="x", outcome="YES",
                side=side, size=100, price=price, notional=100 * price, ts=ts,
                resolution=None, resolved_at=pd.NaT)


def test_tight_fast_follower_scores_higher_than_loose_late():
    rows = []
    for i in range(6):
        mkt = f"mk{i}"
        # LEADER buys at 0.50
        rows.append(_t("LEADER", mkt, "BUY", 0.50, T0 + pd.Timedelta(minutes=i)))
        # TIGHT copies at ~same price, 5s later
        rows.append(_t("TIGHT", mkt, "BUY", 0.505, T0 + pd.Timedelta(minutes=i, seconds=5)))
        # LOOSE copies at much worse price, 10 min later
        rows.append(_t("LOOSE", mkt, "BUY", 0.70, T0 + pd.Timedelta(minutes=i, seconds=600)))
    trades = pd.DataFrame(rows)

    tight = copyable_score(pair_copy_metrics(trades, "LEADER", "TIGHT"))
    loose = copyable_score(pair_copy_metrics(trades, "LEADER", "LOOSE"))
    assert tight > loose

    pairs = pd.DataFrame([
        {"leader": "LEADER", "follower": "TIGHT"},
        {"leader": "LEADER", "follower": "LOOSE"},
    ])
    ranked = rank_leaders(trades, pairs)
    assert ranked.iloc[0]["leader"] == "LEADER"
    assert ranked.iloc[0]["n_followers"] == 2
    assert ranked.iloc[0]["n_copied_positions"] == 12


def test_pair_copy_metrics_entry_delta_and_gap():
    trades = pd.DataFrame([
        _t("L", "m1", "BUY", 0.40, T0),
        _t("F", "m1", "BUY", 0.44, T0 + pd.Timedelta(seconds=8)),
    ])
    m = pair_copy_metrics(trades, "L", "F")
    assert len(m) == 1
    assert abs(m.iloc[0]["entry_delta"] - 0.04) < 1e-9
    assert abs(m.iloc[0]["time_gap_seconds"] - 8.0) < 1e-9

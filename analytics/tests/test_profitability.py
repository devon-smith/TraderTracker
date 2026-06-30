import pandas as pd
from bellwether_analytics.strategy import archetype_pnl, rank_templates

T0 = pd.Timestamp("2026-01-01T00:00:00Z")
SPLIT = "2026-06-01"
TEST_T = pd.Timestamp("2026-07-01T00:00:00Z")


def test_archetype_pnl_separates_profitable_from_flat():
    arche = pd.Series({"P1": "scalper", "P2": "scalper", "F1": "accumulator", "F2": "accumulator"})
    pnl = pd.Series({"P1": 100.0, "P2": 120.0, "F1": 0.0, "F2": 5.0})
    out = archetype_pnl(arche, pnl)
    assert out.loc["scalper", "median_pnl"] > out.loc["accumulator", "median_pnl"]
    assert out.loc["scalper", "pct_profitable"] == 1.0


def _scalp_train(w):
    # rapid, single btc-updown-5m family -> scalper
    return [dict(wallet=w, market=f"{w}m{i}", slug=f"btc-updown-5m-{i}", category="crypto",
                 outcome="YES", side="BUY", size=100, price=0.5, notional=50,
                 ts=T0 + pd.Timedelta(seconds=30 * i), resolution=None, resolved_at=pd.NaT)
            for i in range(60)]


def _acc_train(w):
    # slow directional sports buys -> accumulator
    return [dict(wallet=w, market=f"{w}a{i}", slug=f"sports-game-{i}", category="sports",
                 outcome="YES", side="BUY", size=500, price=0.5, notional=250,
                 ts=T0 + pd.Timedelta(hours=6 * i), resolution=None, resolved_at=pd.NaT)
            for i in range(30)]


def _resolved(w, market, resolution):
    # one resolved test position: BUY 100 YES @0.4 -> +60 if YES else -40
    return dict(wallet=w, market=market, slug="x-1", category="crypto", outcome="YES", side="BUY",
                size=100, price=0.4, notional=40, ts=TEST_T, resolution=resolution,
                resolved_at=TEST_T + pd.Timedelta(days=1))


def _fixture():
    rows = []
    for w in ("S1", "S2", "S3"):
        rows += _scalp_train(w) + [_resolved(w, f"{w}win", "YES")]   # +60
    for w in ("A1", "A2", "A3"):
        rows += _acc_train(w) + [_resolved(w, f"{w}lose", "NO")]     # -40
    return pd.DataFrame(rows)


def test_rank_templates_out_of_sample_and_shuffled_control():
    trades = _fixture()
    ranked = rank_templates(trades, split_ts=SPLIT)
    # The scalper btc-updown-5m template should top the ranking with positive P&L.
    top = ranked.iloc[0]
    assert top["archetype"] == "scalper"
    assert top["family"] == "btc-updown-5m"
    assert top["median_pnl"] > 0

    def edge(df):
        sc = df[df["archetype"] == "scalper"]["median_pnl"]
        ac = df[df["archetype"] == "accumulator"]["median_pnl"]
        return (sc.iloc[0] if len(sc) else 0) - (ac.iloc[0] if len(ac) else 0)

    real_edge = edge(ranked)
    shuffled_edge = edge(rank_templates(trades, split_ts=SPLIT, shuffle=True, seed=0))
    assert real_edge > 0
    assert shuffled_edge < real_edge  # control destroys the strategy edge

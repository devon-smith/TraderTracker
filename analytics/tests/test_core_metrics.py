import math
from pathlib import Path

import pandas as pd
import pytest
from bellwether_analytics.core import (
    RankConfig,
    load_config,
    performance_by_wallet,
    rank,
    specialization_by_wallet,
)

T1 = pd.Timestamp("2024-01-01T00:00:00Z")
T2 = pd.Timestamp("2024-01-02T00:00:00Z")  # +86400s


def _fixture() -> pd.DataFrame:
    rows = [
        # W1: two sports positions, one win (YES==YES, pnl=100-40=60), one loss (pnl=-25)
        dict(wallet="W1", market="M1", category="sports", outcome="YES", side="BUY",
             size=100, price=0.4, notional=40, ts=T1, resolution="YES", resolved_at=T2),
        dict(wallet="W1", market="M2", category="sports", outcome="YES", side="BUY",
             size=50, price=0.5, notional=25, ts=T1, resolution="NO", resolved_at=T2),
        # W2: politics win (+5), crypto loss (-5)
        dict(wallet="W2", market="M3", category="politics", outcome="YES", side="BUY",
             size=10, price=0.5, notional=5, ts=T1, resolution="YES", resolved_at=T2),
        dict(wallet="W2", market="M4", category="crypto", outcome="YES", side="BUY",
             size=10, price=0.5, notional=5, ts=T1, resolution="NO", resolved_at=T2),
    ]
    return pd.DataFrame(rows)


def test_performance_matches_hand_computed():
    perf = performance_by_wallet(_fixture())

    w1 = perf.loc["W1"]
    assert w1["trade_count"] == 2
    assert w1["resolved_trade_count"] == 2
    assert w1["resolved_positions"] == 2
    assert w1["realized_pnl"] == pytest.approx(35.0)       # 60 - 25
    assert w1["win_rate"] == pytest.approx(0.5)            # 1 of 2
    assert w1["roi"] == pytest.approx(35.0 / 65.0)         # pnl / buy_cost
    assert w1["avg_hold_seconds"] == pytest.approx(86400.0)

    w2 = perf.loc["W2"]
    assert w2["realized_pnl"] == pytest.approx(0.0)
    assert w2["win_rate"] == pytest.approx(0.5)
    assert w2["roi"] == pytest.approx(0.0)


def test_specialization_hhi_concentrated_vs_diffuse():
    spec = specialization_by_wallet(_fixture())
    # W1 is a pure sports specialist -> HHI 1.0
    assert spec.loc["W1", "hhi"] == pytest.approx(1.0)
    assert spec.loc["W1", "top_category"] == "sports"
    assert spec.loc["W1", "top_category_share"] == pytest.approx(1.0)
    # W2 split 50/50 across two categories -> HHI 0.5
    assert spec.loc["W2", "hhi"] == pytest.approx(0.5)
    assert spec.loc["W2", "n_categories"] == 2


def test_unresolved_markets_excluded_from_settlement():
    df = _fixture()
    df = pd.concat([df, pd.DataFrame([dict(
        wallet="W1", market="M9", category="sports", outcome="YES", side="BUY",
        size=10, price=0.5, notional=5, ts=T1, resolution=None, resolved_at=pd.NaT)])],
        ignore_index=True)
    perf = performance_by_wallet(df)
    assert perf.loc["W1", "trade_count"] == 3            # all trades counted
    assert perf.loc["W1", "resolved_trade_count"] == 2   # unresolved excluded
    assert perf.loc["W1", "realized_pnl"] == pytest.approx(35.0)  # unchanged


def test_rank_orders_by_score_and_respects_filters():
    df = _fixture()
    perf = performance_by_wallet(df)
    spec = specialization_by_wallet(df)
    cfg = RankConfig(min_resolved_trades=2, min_win_rate=0.5, min_specialization=0.0)
    ranked = rank(perf, spec, cfg)
    # both pass; W1 outranks W2 (higher HHI + positive pnl)
    assert list(ranked.index) == ["W1", "W2"]
    w1_score = 0.4 * 0.5 + 0.3 * math.tanh(35.0 / 10000.0) + 0.3 * 1.0
    assert ranked.loc["W1", "score"] == pytest.approx(w1_score)

    # tighten win-rate filter -> nobody qualifies
    strict = rank(perf, spec, RankConfig(min_resolved_trades=2, min_win_rate=0.9))
    assert len(strict) == 0


def test_load_config_from_example_yaml():
    cfg = load_config(Path(__file__).resolve().parents[2] / "config" / "ranking.example.yaml")
    assert cfg.min_resolved_trades == 50
    assert cfg.min_win_rate == 0.55
    assert cfg.w_win_rate == 0.4

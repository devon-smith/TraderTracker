import pytest
from bellwether_analytics.paper_trade import PaperTradeSimulator
from bellwether_ingestion.schemas import Trade


def _t(side, size, price, ts, outcome="YES"):
    return Trade(
        proxyWallet="0xL",
        side=side,
        asset="a",
        conditionId="c1",
        size=size,
        price=price,
        timestamp=ts,
        outcome=outcome,
        outcomeIndex=0,
        slug="sports-game",
    )


def test_paper_trade_realizes_pnl_with_slippage():
    leader_trades = [_t("BUY", 1000, 0.40, ts=1), _t("SELL", 1000, 0.70, ts=2)]
    sim = PaperTradeSimulator(slippage_bps=100, size_scale=0.1, min_leader_notional=0)
    r = sim.run("0xL", leader_trades)
    assert r.copied_count == 2
    assert r.realized_pnl == pytest.approx(28.9, abs=1e-4)
    assert r.slippage_paid == pytest.approx(1.1, abs=1e-4)


def test_paper_trade_skips_undersized_and_respects_same_side_only():
    leader_trades = [
        _t("BUY", 10, 0.5, ts=1),
        _t("BUY", 1000, 0.5, ts=2),
        _t("SELL", 1000, 0.5, ts=3),
    ]
    sim = PaperTradeSimulator(min_leader_notional=100, size_scale=0.05, slippage_bps=0, same_side_only=True)
    r = sim.run("0xL", leader_trades)
    assert r.skipped_undersized == 1
    assert r.copied_count == 1

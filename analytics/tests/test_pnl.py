import pandas as pd
import pytest
from bellwether_analytics.core import cashflow_pnl_by_wallet


def test_cashflow_pnl_with_split_redeem():
    # W1: split 100 USDC into YES+NO, sells NO for 40, redeems YES for 90, +1 reward.
    #   net = -100 (split) + 40 (sell) + 90 (redeem) + 1 (reward) = 31
    trades = pd.DataFrame([
        dict(wallet="W1", side="SELL", notional=40.0),
        dict(wallet="W2", side="BUY", notional=10.0),
    ])
    events = pd.DataFrame([
        dict(wallet="W1", event_type="SPLIT", value=100.0),
        dict(wallet="W1", event_type="REDEEM", value=90.0),
        dict(wallet="W1", event_type="REWARD", value=1.0),
        dict(wallet="W2", event_type="REDEEM", value=12.0),
    ])
    pnl = cashflow_pnl_by_wallet(trades, events)

    assert pnl.loc["W1", "net_cashflow"] == pytest.approx(31.0)
    assert pnl.loc["W1", "split_cost"] == pytest.approx(100.0)
    assert pnl.loc["W1", "redeemed"] == pytest.approx(90.0)
    # W2: -10 buy + 12 redeem = +2
    assert pnl.loc["W2", "net_cashflow"] == pytest.approx(2.0)


def test_cashflow_pnl_trades_only_and_events_only():
    trades = pd.DataFrame([dict(wallet="A", side="BUY", notional=5.0)])
    events = pd.DataFrame(columns=["wallet", "event_type", "value"])
    pnl = cashflow_pnl_by_wallet(trades, events)
    assert pnl.loc["A", "net_cashflow"] == pytest.approx(-5.0)

    trades2 = pd.DataFrame(columns=["wallet", "side", "notional"])
    events2 = pd.DataFrame([dict(wallet="B", event_type="REDEEM", value=7.0)])
    pnl2 = cashflow_pnl_by_wallet(trades2, events2)
    assert pnl2.loc["B", "net_cashflow"] == pytest.approx(7.0)

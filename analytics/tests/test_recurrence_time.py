import pandas as pd
from bellwether_analytics.strategy import (
    cycle_motifs,
    periodicity,
    recurrence_in_time_report,
)

T0 = pd.Timestamp("2026-01-01T00:00:00Z")


def _trade(wallet, market, slug, side, ts):
    return dict(wallet=wallet, market=market, slug=slug, category="crypto", outcome="YES",
                side=side, size=100, price=0.5, notional=50, ts=ts,
                resolution=None, resolved_at=pd.NaT)


def _regular_wallet():
    """60 markets in the btc-updown-5m family: BUY every 300s, REDEEM 60s later."""
    trades, events = [], []
    for i in range(60):
        mkt = f"m{i}"
        entry = T0 + pd.Timedelta(seconds=300 * i)
        trades.append(_trade("REG", mkt, f"btc-updown-5m-{i}", "BUY", entry))
        events.append(dict(wallet="REG", market=mkt, event_type="REDEEM",
                           ts=entry + pd.Timedelta(seconds=60), value=55.0))
    return pd.DataFrame(trades), pd.DataFrame(events)


def test_periodicity_high_for_regular_cadence():
    trades, _ = _regular_wallet()
    p = periodicity(trades, "REG", family="btc-updown-5m")
    assert p["n_events"] == 60
    assert p["regularity"] > 0.95            # near-perfect 300s cadence
    assert abs(p["dominant_period_seconds"] - 300.0) < 1e-6


def test_cycle_motifs_detects_repeated_buy_redeem_cycles():
    trades, events = _regular_wallet()
    c = cycle_motifs(trades, events, "REG", family="btc-updown-5m")
    assert c["n_cycles"] == 60
    assert abs(c["median_cycle_duration_seconds"] - 60.0) < 1e-6
    assert abs(c["median_cycle_start_gap_seconds"] - 300.0) < 1e-6
    assert c["cycle_consistency"] > 0.95


def test_report_flags_recurring_vs_one_off():
    trades, events = _regular_wallet()
    rep = recurrence_in_time_report(trades, events, "REG")
    assert rep["top_family"] == "btc-updown-5m"
    assert rep["is_recurring"] is True

    one = pd.DataFrame([_trade("ONE", "x", "some-market", "BUY", T0)])
    one_ev = pd.DataFrame([dict(wallet="ONE", market="x", event_type="REDEEM",
                                ts=T0 + pd.Timedelta(days=3), value=10.0)])
    rep2 = recurrence_in_time_report(one, one_ev, "ONE")
    assert rep2["is_recurring"] is False
    assert rep2["n_cycles"] == 1

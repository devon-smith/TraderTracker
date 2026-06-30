from tradertracker.kalshi.flow import FlowAggregator


def _t(ticker, yes_price, count, side, no_price=None, block=False):
    return {
        "ticker": ticker,
        "yes_price": yes_price,
        "no_price": no_price if no_price is not None else 100 - yes_price,
        "count": count,
        "taker_side": side,
        "is_block_trade": block,
    }


def test_flow_aggregation_imbalance_and_vwap():
    agg = FlowAggregator()
    agg.update(
        [
            _t("KXFED-26JAN", 60, 100, "yes"),  # YES taker, $60 notional
            _t("KXFED-26JAN", 65, 200, "yes"),  # YES taker, $130 notional
            _t("KXFED-26JAN", 35, 50, "no"),    # NO taker  (no_price=65), $32.50 notional
            _t("KXBTC", 80, 10, "no", block=True),  # block trade
        ]
    )
    flows = {f.ticker: f for f in agg.all_flows()}
    fed = flows["KXFED-26JAN"]
    assert fed.yes_count == 300
    assert fed.no_count == 50
    # YES notional = 60*100/100 + 65*200/100 = 60 + 130 = 190
    assert round(fed.yes_notional, 2) == 190.0
    # NO notional uses no_price=65 → 65*50/100 = 32.50
    assert round(fed.no_notional, 2) == 32.5
    # YES VWAP = (60*100 + 65*200) / 300 = 19000/300 ≈ 63.33
    assert round(fed.yes_vwap, 2) == 63.33
    assert fed.imbalance > 0  # net YES buying

    btc = flows["KXBTC"]
    # NO taker at no_price = 100 - 80 = 20; notional = 20*10/100 = 2.0
    assert round(btc.no_notional, 2) == 2.0
    assert btc.block_trade_notional == 2.0


def test_top_imbalances_gated_by_min_notional():
    agg = FlowAggregator()
    # Tiny market — below threshold.
    agg.update([_t("SMALL", 50, 1, "yes")])
    # Real market — large one-sided YES.
    agg.update([_t("BIG", 50, 10_000, "yes")])

    top = agg.top_imbalances(n=10, min_notional=100)
    assert [f.ticker for f in top] == ["BIG"]

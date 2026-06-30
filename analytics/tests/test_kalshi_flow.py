from bellwether_analytics.kalshi_flow import FlowAggregator


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
            _t("KXFED-26JAN", 60, 100, "yes"),
            _t("KXFED-26JAN", 65, 200, "yes"),
            _t("KXFED-26JAN", 35, 50, "no"),
            _t("KXBTC", 80, 10, "no", block=True),
        ]
    )
    flows = {f.ticker: f for f in agg.all_flows()}
    fed = flows["KXFED-26JAN"]
    assert fed.yes_count == 300
    assert fed.no_count == 50
    assert round(fed.yes_notional, 2) == 190.0
    assert round(fed.no_notional, 2) == 32.5
    assert round(fed.yes_vwap, 2) == 63.33
    assert fed.imbalance > 0

    btc = flows["KXBTC"]
    assert round(btc.no_notional, 2) == 2.0
    assert btc.block_trade_notional == 2.0


def test_top_imbalances_gated_by_min_notional():
    agg = FlowAggregator()
    agg.update([_t("SMALL", 50, 1, "yes")])
    agg.update([_t("BIG", 50, 10_000, "yes")])
    top = agg.top_imbalances(n=10, min_notional=100)
    assert [f.ticker for f in top] == ["BIG"]

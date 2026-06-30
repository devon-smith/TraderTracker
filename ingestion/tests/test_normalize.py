import datetime as dt

import pytest
from bellwether_ingestion.db import normalize
from bellwether_ingestion.schemas import Activity, Trade


def test_manifold_trade_fields_buy_sell_and_ts():
    buy = normalize.manifold_trade_fields(
        {
            "id": "bet1",
            "userId": "u1",
            "contractId": "c1",
            "shares": 50,
            "amount": 20,
            "outcome": "YES",
            "probAfter": 0.6,
            "createdTime": 1_700_000_000_000,  # ms
        }
    )
    assert buy["dedup_key"] == "manifold:bet1"
    assert buy["platform"] == "manifold"
    assert buy["source"] == "manifold_api"
    assert buy["side"] == "BUY"
    assert buy["size"] == 50.0
    assert buy["price"] == 0.6
    assert buy["notional"] == 30.0
    assert buy["wallet_external"] == "u1"
    assert buy["market_external"] == "c1"
    assert buy["ts"] == dt.datetime(2023, 11, 14, 22, 13, 20, tzinfo=dt.timezone.utc)

    sell = normalize.manifold_trade_fields(
        {"id": "b2", "userId": "u1", "contractId": "c1", "amount": -10, "probAfter": 0.5}
    )
    assert sell["side"] == "SELL"
    assert sell["size"] == 10.0


def test_manifold_market_fields_multi_outcome_and_resolution():
    m = normalize.manifold_market_fields(
        {
            "id": "c1",
            "question": "Who wins?",
            "slug": "who-wins",
            "outcomeType": "MULTIPLE_CHOICE",
            "groupSlugs": ["politics", "us"],
            "createdTime": 1_600_000_000_000,
            "resolutionTime": 1_700_000_000_000,
            "resolution": "YES",
        }
    )
    assert m["external_id"] == "c1"
    assert m["category"] == "politics"
    assert m["raw_category"] == "MULTIPLE_CHOICE"
    assert m["is_multi_outcome"] is True
    assert m["resolution"] == "YES"
    assert m["resolved_at"] is not None


def test_polymarket_trade_fields_and_stable_dedup_key():
    t = Trade(
        proxyWallet="0xABC",
        side="buy",
        asset="tok1",
        conditionId="cond1",
        size=100,
        price=0.4,
        timestamp=1_700_000_000,
        slug="fed-rates",
        outcome="YES",
        outcomeIndex=0,
        transactionHash="0xhash",
    )
    row = normalize.polymarket_trade_fields(t)
    assert row["platform"] == "polymarket"
    assert row["source"] == "data_api"
    assert row["side"] == "BUY"
    assert row["notional"] == 40.0
    assert row["wallet_external"] == "0xABC"
    # dedup key is stable for identical inputs.
    assert row["dedup_key"] == normalize.polymarket_trade_fields(t)["dedup_key"]
    assert row["dedup_key"].startswith("pmapi:")


def test_polymarket_activity_uses_usdc_and_maps_income_types():
    redeem = Activity(
        proxyWallet="0xA", type="REDEEM", timestamp=1_700_000_000, asset="tok",
        conditionId="cond1", size=33828.16, usdcSize=33828.16, price=0,
    )
    row = normalize.polymarket_activity_fields(redeem)
    assert row is not None
    assert row["event_type"] == "REDEEM"
    assert row["value"] == pytest.approx(33828.16)  # usdcSize, not size*price(=0)

    # rebate/yield income folds into REWARD
    rebate = Activity(proxyWallet="0xA", type="MAKER_REBATE", timestamp=2, size=3.3, usdcSize=3.3)
    assert normalize.polymarket_activity_fields(rebate)["event_type"] == "REWARD"

    # TRADE rows are not position events (they come from /trades)
    trade = Activity(proxyWallet="0xA", type="TRADE", timestamp=1, conditionId="c")
    assert normalize.polymarket_activity_fields(trade) is None

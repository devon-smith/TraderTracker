from bellwether_ingestion.db.normalize import (
    canonical_trade_columns,
    normalize_manifold_bet,
    normalize_polymarket_trade,
)
from bellwether_ingestion.schemas import Trade


def test_normalize_polymarket_trade():
    t = Trade(
        proxyWallet="0xABC",
        side="buy",
        asset="tok1",
        conditionId="cond1",
        size=100,
        price=0.4,
        timestamp=1_700_000_000,
        slug="fed-rates-january",
        outcome="YES",
        outcomeIndex=0,
        transactionHash="0xhash",
    )
    row = normalize_polymarket_trade(t)
    assert row["platform"] == "polymarket"
    assert row["wallet_id"] == "0xABC"
    assert row["market_id"] == "cond1"
    assert row["side"] == "BUY"  # upper-cased
    assert row["notional"] == 40.0
    assert row["ts_epoch"] == 1_700_000_000
    # Every canonical column is present.
    assert set(canonical_trade_columns) <= set(row.keys())


def test_normalize_manifold_bet_buy_and_sell():
    buy = normalize_manifold_bet(
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
    assert buy["platform"] == "manifold"
    assert buy["side"] == "BUY"
    assert buy["size"] == 50.0
    assert buy["price"] == 0.6
    assert buy["notional"] == 30.0
    assert buy["ts_epoch"] == 1_700_000_000  # ms -> s

    sell = normalize_manifold_bet({"userId": "u1", "contractId": "c1", "amount": -10, "probAfter": 0.5})
    assert sell["side"] == "SELL"
    assert sell["size"] == 10.0

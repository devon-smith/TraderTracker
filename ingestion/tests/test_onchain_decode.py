"""Deterministic decoder tests — no RPC/DB needed. Encode an OrderFilled log with
the V1 ABI, decode it back, and normalize to trade rows."""

import datetime as dt

import pytest
from bellwether_ingestion.polymarket_onchain import decode_log, normalize_order_filled
from bellwether_ingestion.polymarket_onchain.contracts import (
    ORDER_FILLED_V1,
    ORDER_FILLED_V2,
    ORDER_FILLED_V2_TOPIC0,
    order_filled_topic0,
)
from bellwether_ingestion.polymarket_onchain.decode import event_topic0
from bellwether_ingestion.polymarket_onchain.normalize import (
    V2OrderFilledError,
    assert_v2_order_filled_log,
)
from eth_abi import encode

MAKER = "0x" + "11" * 20
TAKER = "0x" + "22" * 20


def _addr_topic(a: str) -> str:
    return "0x" + "00" * 12 + a[2:]


def _make_log(maker_asset, taker_asset, maker_amt, taker_amt):
    order_hash = b"\xab" * 32
    topics = [
        event_topic0(ORDER_FILLED_V1),
        "0x" + order_hash.hex(),
        _addr_topic(MAKER),
        _addr_topic(TAKER),
    ]
    data = "0x" + encode(
        ["uint256"] * 5, [maker_asset, taker_asset, maker_amt, taker_amt, 0]
    ).hex()
    return topics, data


def test_signature_and_topic0_shape():
    assert ORDER_FILLED_V1.signature() == (
        "OrderFilled(bytes32,address,address,uint256,uint256,uint256,uint256,uint256)"
    )
    t0 = event_topic0(ORDER_FILLED_V1)
    assert t0.startswith("0x") and len(t0) == 66


def test_decode_roundtrip():
    topics, data = _make_log(0, 12345, 750_000, 1_000_000)
    d = decode_log(ORDER_FILLED_V1, topics, data)
    assert d["maker"].lower() == MAKER
    assert d["taker"].lower() == TAKER
    assert d["makerAssetId"] == 0
    assert d["takerAssetId"] == 12345
    assert d["makerAmountFilled"] == 750_000
    assert d["takerAmountFilled"] == 1_000_000
    assert d["orderHash"] == "0x" + "ab" * 32


def test_normalize_maker_buys_when_maker_pays_usdc():
    # maker_asset=0 (USDC) -> maker BUYS token 12345; 0.75 USDC for 1.0 share
    topics, data = _make_log(0, 12345, 750_000, 1_000_000)
    d = decode_log(ORDER_FILLED_V1, topics, data)
    ts = dt.datetime(2026, 5, 1, tzinfo=dt.timezone.utc)
    rows = normalize_order_filled(d, "0xtx", 7, ts)
    assert len(rows) == 2
    maker, taker = rows
    assert maker["wallet_external"].lower() == MAKER
    assert maker["side"] == "BUY"
    assert maker["asset"] == "12345"
    assert maker["size"] == 1.0
    assert maker["price"] == 0.75
    assert maker["notional"] == 0.75
    assert maker["dedup_key"] == "onchain:0xtx:7:m"
    assert maker["is_taker"] is False
    assert taker["side"] == "SELL"
    assert taker["dedup_key"] == "onchain:0xtx:7:t"
    assert taker["is_taker"] is True  # taker is the aggressor


def test_normalize_maker_sells_when_taker_pays_usdc():
    # taker_asset=0 -> maker SELLS token 999; receives 0.6 USDC for 1.0 share
    topics, data = _make_log(999, 0, 1_000_000, 600_000)
    d = decode_log(ORDER_FILLED_V1, topics, data)
    rows = normalize_order_filled(d, "0xtx", 1, dt.datetime(2026, 5, 1, tzinfo=dt.timezone.utc))
    maker = rows[0]
    assert maker["side"] == "SELL"
    assert maker["asset"] == "999"
    assert maker["size"] == 1.0
    assert maker["price"] == 0.6


# --- V2 OrderFilled: live-verified layout + ingest assertions -----------------

ORDER_HASH = b"\xab" * 32
BUILDER = b"\xbb" * 32
METADATA = b"\xcc" * 32


def _make_v2_log(token_id=12345, side=0, maker_amt=750_000, taker_amt=1_000_000, topic0=None):
    topics = [
        topic0 or ORDER_FILLED_V2_TOPIC0,
        "0x" + ORDER_HASH.hex(),
        _addr_topic(MAKER),
        _addr_topic(TAKER),
    ]
    data = "0x" + encode(
        ["uint8", "uint256", "uint256", "uint256", "uint256", "bytes32", "bytes32"],
        [side, token_id, maker_amt, taker_amt, 0, BUILDER, METADATA],
    ).hex()
    return topics, data


def test_v2_signature_and_verified_topic0():
    assert ORDER_FILLED_V2.signature() == (
        "OrderFilled(bytes32,address,address,uint8,uint256,uint256,uint256,uint256,bytes32,bytes32)"
    )
    # the exported topic0 for v2 is the authoritative constant, not re-derived
    assert order_filled_topic0("v2") == ORDER_FILLED_V2_TOPIC0
    assert ORDER_FILLED_V2_TOPIC0.startswith("0x") and len(ORDER_FILLED_V2_TOPIC0) == 66


def test_v2_decode_all_ten_fields():
    topics, data = _make_v2_log()
    d = decode_log(ORDER_FILLED_V2, topics, data)
    # maker/taker pulled from the indexed topics
    assert d["maker"].lower() == MAKER
    assert d["taker"].lower() == TAKER
    assert d["orderHash"] == "0x" + "ab" * 32
    # all 10 fields present, including the trailing builder/metadata that mark V2
    assert set(d) == {
        "orderHash", "maker", "taker", "side", "tokenId",
        "makerAmountFilled", "takerAmountFilled", "fee", "builder", "metadata",
    }
    assert d["tokenId"] == 12345
    assert d["builder"] == BUILDER
    assert d["metadata"] == METADATA


def test_v2_assert_accepts_valid_log():
    topics, data = _make_v2_log()
    assert assert_v2_order_filled_log(topics, data) is None  # no raise


def test_v2_assert_rejects_wrong_topic0():
    topics, data = _make_v2_log(topic0=event_topic0(ORDER_FILLED_V1))
    with pytest.raises(V2OrderFilledError, match="topic0"):
        assert_v2_order_filled_log(topics, data)


def test_v2_assert_rejects_v1_shaped_log():
    # correct V2 topic0 but V1-shaped data (5 words, no builder/metadata)
    topics = [ORDER_FILLED_V2_TOPIC0, "0x" + ORDER_HASH.hex(), _addr_topic(MAKER), _addr_topic(TAKER)]
    v1_data = "0x" + encode(["uint256"] * 5, [0, 12345, 750_000, 1_000_000, 0]).hex()
    with pytest.raises(V2OrderFilledError, match="builder/metadata"):
        assert_v2_order_filled_log(topics, v1_data)


def test_v2_assert_rejects_wrong_topic_count():
    topics, data = _make_v2_log()
    with pytest.raises(V2OrderFilledError, match="4 topics"):
        assert_v2_order_filled_log(topics[:3], data)

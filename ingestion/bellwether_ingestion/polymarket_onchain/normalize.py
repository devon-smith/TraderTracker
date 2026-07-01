"""Decoded OrderFilled -> canonical trade rows.

OrderFilled is maker-perspective. USDC collateral is asset id 0; the other leg is
the outcome token. We emit a row for BOTH maker and taker (opposite sides) so a
watchlist wallet is captured whichever side it's on. conditionId isn't in the
event, so market linkage (tokenId -> market) is deferred; asset holds the tokenId.
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

from .contracts import COLLATERAL_ASSET_ID, ORDER_FILLED_V2, ORDER_FILLED_V2_TOPIC0

DECIMALS = 6  # USDC and CTF outcome tokens both use 6 decimals on Polymarket.

# A V2 OrderFilled log carries one word per non-indexed field (side..metadata);
# the trailing builder+metadata are what a V1 log lacks.
_V2_DATA_MIN_BYTES = 32 * len(ORDER_FILLED_V2.non_indexed)


class V2OrderFilledError(ValueError):
    """A log does not match the live-verified V2 OrderFilled shape."""


def _to_bytes(x) -> bytes:
    if isinstance(x, (bytes, bytearray)):
        return bytes(x)
    s = x[2:] if isinstance(x, str) and x[:2].lower() == "0x" else x
    return bytes.fromhex(s)


def assert_v2_order_filled_log(topics: list, data) -> None:
    """Guard a raw log against the live-verified V2 OrderFilled BEFORE decoding, so
    a V1/foreign log is rejected loudly instead of silently decoded as garbage.

    Asserts: topic[0] == the verified V2 signature hash; exactly 4 topics
    (sig + 3 indexed = orderHash/maker/taker); and enough data to carry the
    trailing builder+metadata fields (their presence distinguishes V2 from V1).
    Raises V2OrderFilledError on any mismatch."""
    if not topics:
        raise V2OrderFilledError("log has no topics")
    raw = topics[0]
    t0 = raw.lower() if isinstance(raw, str) else "0x" + _to_bytes(raw).hex()
    if t0 != ORDER_FILLED_V2_TOPIC0:
        raise V2OrderFilledError(
            f"topic0 {t0} != verified V2 OrderFilled {ORDER_FILLED_V2_TOPIC0}"
        )
    if len(topics) != 4:
        raise V2OrderFilledError(f"expected 4 topics (sig + 3 indexed), got {len(topics)}")
    n = len(_to_bytes(data))
    if n < _V2_DATA_MIN_BYTES:
        raise V2OrderFilledError(
            f"data {n}B < {_V2_DATA_MIN_BYTES}B — builder/metadata absent (looks like a V1 log)"
        )


def _row(dedup_suffix, wallet, side, token, size, price, tx_hash, log_index, ts, is_taker, block_number):
    return {
        "dedup_key": f"onchain:{tx_hash}:{log_index}:{dedup_suffix}",
        "ts": ts,
        "platform": "polymarket",
        "wallet_external": wallet,
        "market_external": None,  # resolve tokenId -> conditionId later
        "side": side,
        "outcome": None,
        "asset": str(token),
        "size": size,
        "price": price,
        "notional": size * price,
        "tx_hash": tx_hash,
        "log_index": log_index,
        "block_number": block_number,
        "source": "onchain",
        "is_taker": is_taker,  # taker is the aggressor; maker provides liquidity
    }


def normalize_order_filled(
    decoded: dict,
    tx_hash: str,
    log_index: int,
    ts: dt.datetime,
    block_number: Optional[int] = None,
) -> list[dict]:
    """Return maker + taker trade rows for one decoded OrderFilled event."""
    maker = decoded["maker"]
    taker = decoded["taker"]
    maker_asset = int(decoded["makerAssetId"])
    taker_asset = int(decoded["takerAssetId"])
    maker_amt = int(decoded["makerAmountFilled"])
    taker_amt = int(decoded["takerAmountFilled"])

    if maker_asset == COLLATERAL_ASSET_ID:
        # maker pays USDC for taker_asset tokens -> maker BUYS
        token, usdc_amt, share_amt = taker_asset, maker_amt, taker_amt
        maker_side, taker_side = "BUY", "SELL"
    elif taker_asset == COLLATERAL_ASSET_ID:
        # maker gives maker_asset tokens for USDC -> maker SELLS
        token, usdc_amt, share_amt = maker_asset, taker_amt, maker_amt
        maker_side, taker_side = "SELL", "BUY"
    else:
        return []  # token<->token (not a USDC-collateralized fill)

    if share_amt == 0:
        return []
    size = share_amt / 10**DECIMALS
    price = usdc_amt / share_amt  # both scaled by 10**DECIMALS -> ratio is the price

    return [
        _row("m", maker, maker_side, token, size, price, tx_hash, log_index, ts,
             is_taker=False, block_number=block_number),
        _row("t", taker, taker_side, token, size, price, tx_hash, log_index, ts,
             is_taker=True, block_number=block_number),
    ]


def block_ts_to_dt(ts_hex_or_int) -> dt.datetime:
    ts = int(ts_hex_or_int, 16) if isinstance(ts_hex_or_int, str) else int(ts_hex_or_int)
    return dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc)


def freshness_lag_seconds(latest_onchain_ts: Optional[dt.datetime], now: dt.datetime) -> Optional[float]:
    if latest_onchain_ts is None:
        return None
    return (now - latest_onchain_ts).total_seconds()

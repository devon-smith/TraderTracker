"""Decoded OrderFilled -> canonical trade rows.

OrderFilled is maker-perspective. USDC collateral is asset id 0; the other leg is
the outcome token. We emit a row for BOTH maker and taker (opposite sides) so a
watchlist wallet is captured whichever side it's on. conditionId isn't in the
event, so market linkage (tokenId -> market) is deferred; asset holds the tokenId.
"""

from __future__ import annotations

import datetime as dt
from typing import Optional

from .contracts import COLLATERAL_ASSET_ID

DECIMALS = 6  # USDC and CTF outcome tokens both use 6 decimals on Polymarket.


def _row(dedup_suffix, wallet, side, token, size, price, tx_hash, log_index, ts):
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
        "source": "onchain",
    }


def normalize_order_filled(
    decoded: dict,
    tx_hash: str,
    log_index: int,
    ts: dt.datetime,
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
        _row("m", maker, maker_side, token, size, price, tx_hash, log_index, ts),
        _row("t", taker, taker_side, token, size, price, tx_hash, log_index, ts),
    ]


def block_ts_to_dt(ts_hex_or_int) -> dt.datetime:
    ts = int(ts_hex_or_int, 16) if isinstance(ts_hex_or_int, str) else int(ts_hex_or_int)
    return dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc)


def freshness_lag_seconds(latest_onchain_ts: Optional[dt.datetime], now: dt.datetime) -> Optional[float]:
    if latest_onchain_ts is None:
        return None
    return (now - latest_onchain_ts).total_seconds()

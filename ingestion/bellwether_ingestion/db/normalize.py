"""Pure normalizers: raw platform records -> canonical field dicts + dedup keys.

Side-effect-free so they unit-test without a database. Loaders (per-venue) resolve
wallet/market external ids to surrogate ids and persist via ON CONFLICT.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from typing import Optional

from ..schemas import Activity, Trade


def epoch_s_to_dt(ts: Optional[float]) -> dt.datetime:
    return dt.datetime.fromtimestamp(int(ts or 0), tz=dt.timezone.utc)


def epoch_ms_to_dt(ts: Optional[float]) -> dt.datetime:
    return dt.datetime.fromtimestamp(int((ts or 0) / 1000), tz=dt.timezone.utc)


# --------------------------------------------------------------------------- #
# Dedup keys (stable, source-scoped)
# --------------------------------------------------------------------------- #
def manifold_dedup_key(bet_id: str) -> str:
    return f"manifold:{bet_id}"


def polymarket_api_dedup_key(t: Trade) -> str:
    raw = "|".join(
        str(x)
        for x in (
            t.proxyWallet,
            t.conditionId,
            t.asset,
            t.side,
            t.size,
            t.price,
            t.timestamp,
            t.transactionHash,
        )
    )
    return "pmapi:" + hashlib.sha1(raw.encode()).hexdigest()


def onchain_dedup_key(tx_hash: str, log_index: int) -> str:
    return f"onchain:{tx_hash}:{log_index}"


# --------------------------------------------------------------------------- #
# Manifold
# --------------------------------------------------------------------------- #
def manifold_market_fields(contract: dict) -> dict:
    outcome_type = contract.get("outcomeType", "BINARY")
    groups = contract.get("groupSlugs") or []
    category = (groups[0] if groups else None) or outcome_type.lower()
    resolution_time = contract.get("resolutionTime")
    return {
        "external_id": contract.get("id"),
        "title": contract.get("question"),
        "slug": contract.get("slug"),
        "category": category,
        "raw_category": outcome_type,
        "created_at": epoch_ms_to_dt(contract.get("createdTime")),
        "resolved_at": epoch_ms_to_dt(resolution_time) if resolution_time else None,
        "resolution": contract.get("resolution"),
        "is_multi_outcome": outcome_type not in ("BINARY", "PSEUDO_NUMERIC", "STONK"),
    }


def manifold_trade_fields(bet: dict) -> dict:
    amount = float(bet.get("amount", 0) or 0)
    shares = bet.get("shares")
    size = abs(float(shares)) if shares is not None else abs(amount)
    price = float(bet.get("probAfter", bet.get("probBefore", 0.0)) or 0.0)
    return {
        "dedup_key": manifold_dedup_key(bet["id"]),
        "ts": epoch_ms_to_dt(bet.get("createdTime")),
        "platform": "manifold",
        "wallet_external": bet.get("userId"),
        "market_external": bet.get("contractId"),
        "side": "BUY" if amount >= 0 else "SELL",
        "outcome": bet.get("outcome"),
        "size": size,
        "price": price,
        "notional": size * price,
        "tx_hash": bet.get("id"),
        "log_index": None,
        "source": "manifold_api",
    }


# --------------------------------------------------------------------------- #
# Polymarket Data API
# --------------------------------------------------------------------------- #
def polymarket_trade_fields(t: Trade) -> dict:
    return {
        "dedup_key": polymarket_api_dedup_key(t),
        "ts": epoch_s_to_dt(t.timestamp),
        "platform": "polymarket",
        "wallet_external": t.proxyWallet,
        "market_external": t.conditionId,
        "side": (t.side or "").upper() or None,
        "outcome": t.outcome,
        "size": float(t.size),
        "price": float(t.price),
        "notional": float(t.size) * float(t.price),
        "tx_hash": t.transactionHash,
        "log_index": None,
        "source": "data_api",
    }


# Raw Data-API activity type -> canonical PositionEventType. Rebates/yield are all
# positive USDC income, folded into REWARD (the enum stays stable).
_EVENT_TYPE_MAP = {
    "SPLIT": "SPLIT",
    "MERGE": "MERGE",
    "REDEEM": "REDEEM",
    "CONVERSION": "CONVERSION",
    "REWARD": "REWARD",
    "MAKER_REBATE": "REWARD",
    "TAKER_REBATE": "REWARD",
    "YIELD": "REWARD",
}


def polymarket_activity_fields(a: Activity) -> Optional[dict]:
    """Map a Polymarket /activity row to a position_event dict, or None if it's a
    TRADE (trades come from /trades). `value` is the USDC leg (usdcSize)."""
    etype = (a.type or "").upper()
    canonical = _EVENT_TYPE_MAP.get(etype)
    if canonical is None:
        return None
    usdc = a.usdcSize if a.usdcSize is not None else ((a.size or 0) * (a.price or 0))
    # Activity rows frequently lack a tx hash, so hash the identifying fields
    # (including timestamp) to avoid dedup collisions.
    key_raw = "|".join(
        str(x) for x in (etype, a.conditionId, a.timestamp, usdc, a.outcome, a.asset)
    )
    return {
        "dedup_key": "pmact:" + hashlib.sha1(key_raw.encode()).hexdigest(),
        "ts": epoch_s_to_dt(a.timestamp),
        "platform": "polymarket",
        "wallet_external": a.proxyWallet,
        "market_external": a.conditionId or None,
        "event_type": canonical,
        "size": a.size,
        "value": usdc,
        "tx_hash": a.transactionHash,
        "log_index": None,
    }

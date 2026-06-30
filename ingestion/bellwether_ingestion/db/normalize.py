"""Pure normalizers: raw platform records -> canonical `trade` rows.

These are deliberately side-effect-free so they can be unit-tested without a
database. The dict keys match the columns of the canonical `trade` table in
infra/db/migrations/0001_canonical_schema.sql.
"""

from __future__ import annotations

from typing import Optional

from ..schemas import Trade

# Single source of truth for the canonical trade column order (used by COPY/INSERT).
canonical_trade_columns = (
    "platform",
    "wallet_id",
    "market_id",
    "condition_id",
    "asset",
    "side",
    "size",
    "price",
    "notional",
    "outcome",
    "outcome_index",
    "tx_hash",
    "ts_epoch",
)


def normalize_polymarket_trade(t: Trade, platform: str = "polymarket") -> dict:
    """Polymarket Data-API Trade -> canonical trade row."""
    return {
        "platform": platform,
        "wallet_id": t.proxyWallet,
        "market_id": t.conditionId,
        "condition_id": t.conditionId,
        "asset": t.asset,
        "side": (t.side or "").upper(),
        "size": float(t.size),
        "price": float(t.price),
        "notional": float(t.size) * float(t.price),
        "outcome": t.outcome,
        "outcome_index": t.outcomeIndex,
        "tx_hash": t.transactionHash,
        "ts_epoch": int(t.timestamp),
    }


def _ms_to_s(ts: Optional[float]) -> int:
    """Manifold timestamps are epoch milliseconds; canonical store uses seconds."""
    return int((ts or 0) / 1000)


def normalize_manifold_bet(b: dict, platform: str = "manifold") -> dict:
    """Manifold bet -> canonical trade row.

    Manifold bets are share purchases against a probability. We approximate:
      - size  := |shares| (fallback to |amount|)
      - price := probAfter (the post-trade probability ~ the share's marginal price)
      - side  := BUY if amount >= 0 else SELL
    These are approximations appropriate for a play-money prototype venue.
    """
    shares = b.get("shares")
    amount = b.get("amount", 0) or 0
    size = abs(float(shares)) if shares is not None else abs(float(amount))
    price = float(b.get("probAfter", b.get("probBefore", 0.0)) or 0.0)
    return {
        "platform": platform,
        "wallet_id": b.get("userId"),
        "market_id": b.get("contractId"),
        "condition_id": b.get("contractId"),
        "asset": b.get("outcome"),
        "side": "BUY" if float(amount) >= 0 else "SELL",
        "size": size,
        "price": price,
        "notional": size * price,
        "outcome": b.get("outcome"),
        "outcome_index": None,
        "tx_hash": b.get("id"),
        "ts_epoch": _ms_to_s(b.get("createdTime")),
    }

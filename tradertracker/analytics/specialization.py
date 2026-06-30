"""Category-specialization analytics for a wallet.

Specialists outperform generalists per the study; this module gives a per-wallet
breakdown by category (derived from market slug prefixes — a cheap proxy for the
Gamma tag join).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from ..polymarket.data_api import Trade


def _category(t: Trade) -> str:
    slug = t.slug or ""
    if slug:
        return slug.split("-")[0].lower()
    title = t.title or ""
    return (title.split(" ")[0] or "unknown").lower()


def category_breakdown(trades: Iterable[Trade]) -> list[dict]:
    by_cat: dict[str, dict] = defaultdict(lambda: {"trades": 0, "volume": 0.0, "buy_volume": 0.0, "sell_volume": 0.0})
    for t in trades:
        cat = _category(t)
        bucket = by_cat[cat]
        bucket["trades"] += 1
        bucket["volume"] += t.notional
        if t.side.upper() == "BUY":
            bucket["buy_volume"] += t.notional
        else:
            bucket["sell_volume"] += t.notional

    total_vol = sum(b["volume"] for b in by_cat.values()) or 1.0
    rows = []
    for cat, b in by_cat.items():
        rows.append(
            {
                "category": cat,
                "trades": b["trades"],
                "volume": b["volume"],
                "share": b["volume"] / total_vol,
                "buy_volume": b["buy_volume"],
                "sell_volume": b["sell_volume"],
                "net_buy": b["buy_volume"] - b["sell_volume"],
            }
        )
    rows.sort(key=lambda r: r["volume"], reverse=True)
    return rows

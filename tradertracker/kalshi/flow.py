"""Anonymous order-flow aggregation for Kalshi.

Kalshi's public feed never identifies the trader. The only honest 'smart money' signal
is one-directional accumulation: per-market, per-side notional and VWAP. Large
one-sided flow over a window is the threshold for further action — typically your own
limit order, not a copy-trade (which is impossible without account-level data).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable


@dataclass
class MarketFlow:
    ticker: str
    yes_notional: float = 0.0
    no_notional: float = 0.0
    yes_count: int = 0
    no_count: int = 0
    yes_vwap: float = 0.0
    no_vwap: float = 0.0
    block_trade_notional: float = 0.0
    trades_seen: int = 0

    @property
    def imbalance(self) -> float:
        """Signed flow imbalance in [-1, +1]. Positive = net YES buying."""
        total = self.yes_notional + self.no_notional
        if total == 0:
            return 0.0
        return (self.yes_notional - self.no_notional) / total

    @property
    def total_notional(self) -> float:
        return self.yes_notional + self.no_notional


class FlowAggregator:
    """Roll a stream of anonymous Kalshi trades into per-market flow stats.

    Kalshi trade prices are in cents (0..100). Notional is computed as
    `count * price_cents / 100` to express in dollars.
    """

    def __init__(self):
        self._flows: dict[str, MarketFlow] = {}
        # Running VWAP accumulators kept separate so the public MarketFlow stays a
        # plain dataclass for serialization.
        self._yes_px_qty: dict[str, float] = defaultdict(float)
        self._yes_qty: dict[str, float] = defaultdict(float)
        self._no_px_qty: dict[str, float] = defaultdict(float)
        self._no_qty: dict[str, float] = defaultdict(float)

    def update(self, trades: Iterable[dict]) -> None:
        for t in trades:
            ticker = t.get("ticker")
            if not ticker:
                continue
            flow = self._flows.setdefault(ticker, MarketFlow(ticker=ticker))
            flow.trades_seen += 1
            count = float(t.get("count", 0))
            yes_price = float(t.get("yes_price", 0))
            no_price = float(t.get("no_price", 100 - yes_price))
            taker_side = (t.get("taker_side") or "").lower()
            is_block = bool(t.get("is_block_trade", False))

            # The taker side identifies which contract the taker bought. Notional
            # attributed to that side captures aggressive one-directional buying.
            if taker_side == "yes":
                notional = count * yes_price / 100.0
                flow.yes_notional += notional
                flow.yes_count += int(count)
                self._yes_px_qty[ticker] += yes_price * count
                self._yes_qty[ticker] += count
                flow.yes_vwap = self._yes_px_qty[ticker] / self._yes_qty[ticker]
            elif taker_side == "no":
                notional = count * no_price / 100.0
                flow.no_notional += notional
                flow.no_count += int(count)
                self._no_px_qty[ticker] += no_price * count
                self._no_qty[ticker] += count
                flow.no_vwap = self._no_px_qty[ticker] / self._no_qty[ticker]
            else:
                notional = count * yes_price / 100.0
            if is_block:
                flow.block_trade_notional += notional

    def top_imbalances(self, n: int = 20, min_notional: float = 1000.0) -> list[MarketFlow]:
        """Return top-n markets by absolute imbalance, gated by minimum total flow."""
        candidates = [f for f in self._flows.values() if f.total_notional >= min_notional]
        return sorted(candidates, key=lambda f: abs(f.imbalance), reverse=True)[:n]

    def all_flows(self) -> list[MarketFlow]:
        return list(self._flows.values())

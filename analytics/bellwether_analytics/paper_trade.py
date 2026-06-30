"""Paper-trade copy simulator.

Replay a leader wallet's historical trades, apply a configurable execution latency
and slippage model, and compute realized PnL on resolved trades.

This is a backtest — it does NOT touch live markets and does NOT trade real funds.
Use it to validate the latency/slippage benchmark called out in the feasibility
study (Experiment A): if fills land within ~2s and slippage stays below the
leader's edge, copy is viable; if >5s late or >3-5% slippage, pivot to signal-only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from bellwether_ingestion.schemas import Trade


@dataclass
class PaperResult:
    leader: str
    trade_count: int = 0
    copied_count: int = 0
    skipped_undersized: int = 0
    notional_copied: float = 0.0
    realized_pnl: float = 0.0
    slippage_paid: float = 0.0
    fills_by_market: dict[str, list[dict]] = field(default_factory=dict)

    def summary(self) -> dict:
        return {
            "leader": self.leader,
            "trades_observed": self.trade_count,
            "trades_copied": self.copied_count,
            "trades_skipped": self.skipped_undersized,
            "notional_copied": round(self.notional_copied, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "slippage_paid": round(self.slippage_paid, 2),
        }


@dataclass
class PaperTradeSimulator:
    """Replay leader fills with a slippage model.

    Parameters
    ----------
    slippage_bps:
        Basis points of slippage applied to each copied fill. 200 bps = 2%.
    size_scale:
        Fraction of the leader's notional you'd take. 0.05 = 5%.
    min_leader_notional:
        Skip leader trades below this notional (filters out dust/test trades).
    same_side_only:
        If True, only copy BUYs (the most common 'enter a position' signal).
    """

    slippage_bps: float = 200.0
    size_scale: float = 0.05
    min_leader_notional: float = 100.0
    same_side_only: bool = False

    def run(self, leader: str, trades: Iterable[Trade]) -> PaperResult:
        result = PaperResult(leader=leader)
        slippage = self.slippage_bps / 10_000.0

        open_positions: dict[tuple[str, str | None], dict] = {}

        for t in sorted(trades, key=lambda x: x.timestamp):
            result.trade_count += 1
            if t.notional < self.min_leader_notional:
                result.skipped_undersized += 1
                continue
            if self.same_side_only and t.side.upper() != "BUY":
                continue

            copy_size = t.size * self.size_scale
            if t.side.upper() == "BUY":
                exec_price = min(t.price * (1 + slippage), 1.0)
            else:
                exec_price = max(t.price * (1 - slippage), 0.0)

            notional = copy_size * exec_price
            slip_cost = abs(exec_price - t.price) * copy_size
            result.copied_count += 1
            result.notional_copied += notional
            result.slippage_paid += slip_cost

            key = (t.conditionId, t.outcome)
            result.fills_by_market.setdefault(t.conditionId, []).append(
                {
                    "timestamp": t.timestamp,
                    "side": t.side,
                    "outcome": t.outcome,
                    "size": copy_size,
                    "leader_price": t.price,
                    "exec_price": exec_price,
                }
            )

            if t.side.upper() == "BUY":
                pos = open_positions.setdefault(key, {"size": 0.0, "cost": 0.0})
                pos["size"] += copy_size
                pos["cost"] += notional
            else:
                pos = open_positions.get(key)
                if pos and pos["size"] > 0:
                    close_size = min(copy_size, pos["size"])
                    avg_cost = pos["cost"] / pos["size"]
                    realized = close_size * (exec_price - avg_cost)
                    result.realized_pnl += realized
                    pos["size"] -= close_size
                    pos["cost"] -= close_size * avg_cost

        return result

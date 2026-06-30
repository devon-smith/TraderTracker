"""Score Polymarket wallets for 'smart money' filtering.

Scoring is intentionally explainable: every component maps to a finding from the
feasibility study (win-rate, trade count, P&L, category concentration). No
black-box ranking; downstream callers can re-weight via WalletScore.weighted_score().
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Optional

from bellwether_ingestion.schemas import Position, Trade


@dataclass
class WalletScore:
    wallet: str
    trade_count: int
    total_volume: float
    realized_pnl: float
    unrealized_pnl: float
    total_pnl: float
    win_rate: Optional[float]  # None if no resolved positions yet
    resolved_positions: int
    open_positions: int
    category_concentration: float  # 0..1; share of volume in the wallet's top category
    top_category: Optional[str]
    category_volume: dict[str, float] = field(default_factory=dict)

    def weighted_score(
        self,
        w_winrate: float = 0.35,
        w_pnl: float = 0.30,
        w_volume: float = 0.15,
        w_specialization: float = 0.20,
        pnl_norm: float = 100_000.0,
        volume_norm: float = 1_000_000.0,
    ) -> float:
        """Combine components into a single 0..1-ish score for ranking."""
        wr = self.win_rate if self.win_rate is not None else 0.5
        pnl_term = max(min(self.total_pnl / pnl_norm, 1.0), -1.0)
        vol_term = min(self.total_volume / volume_norm, 1.0)
        return (
            w_winrate * wr
            + w_pnl * pnl_term
            + w_volume * vol_term
            + w_specialization * self.category_concentration
        )


def _resolve_category(p_or_t) -> str:
    """Best-effort category extraction from Position/Trade slug/title.

    The Data API does not return a category field directly; we cluster by slug
    prefix as a cheap proxy. Callers wanting true categories should join against
    Gamma `tags`.
    """
    slug = getattr(p_or_t, "slug", None) or ""
    if not slug:
        title = getattr(p_or_t, "title", None) or ""
        return (title.split(" ")[0] or "unknown").lower()
    return slug.split("-")[0].lower() or "unknown"


def score_wallet(
    wallet: str,
    trades: Iterable[Trade],
    positions: Iterable[Position],
) -> WalletScore:
    trades = list(trades)
    positions = list(positions)

    total_volume = sum(t.notional for t in trades)
    realized_pnl = sum(p.realizedPnl for p in positions)
    unrealized_pnl = sum(p.cashPnl for p in positions)
    total_pnl = realized_pnl + unrealized_pnl

    # A resolved position has size==0 and a non-zero realized PnL. Heuristic — true
    # resolution requires joining against the market's `closed` status from Gamma.
    resolved = [p for p in positions if p.size == 0 and p.realizedPnl != 0]
    wins = sum(1 for p in resolved if p.realizedPnl > 0)
    win_rate = (wins / len(resolved)) if resolved else None

    cat_vol: dict[str, float] = defaultdict(float)
    for t in trades:
        cat_vol[_resolve_category(t)] += t.notional
    top_cat, top_vol = (None, 0.0)
    if cat_vol:
        top_cat, top_vol = max(cat_vol.items(), key=lambda kv: kv[1])
    concentration = (top_vol / total_volume) if total_volume > 0 else 0.0

    open_positions = sum(1 for p in positions if p.size > 0)

    return WalletScore(
        wallet=wallet,
        trade_count=len(trades),
        total_volume=total_volume,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        total_pnl=total_pnl,
        win_rate=win_rate,
        resolved_positions=len(resolved),
        open_positions=open_positions,
        category_concentration=concentration,
        top_category=top_cat,
        category_volume=dict(cat_vol),
    )


def rank_wallets(
    scores: Iterable[WalletScore],
    min_trades: int = 50,
    min_win_rate: float = 0.55,
    min_pnl: float = 0.0,
    require_resolved: int = 10,
) -> list[WalletScore]:
    """Filter + rank wallets by the study's recommended thresholds.

    Defaults match the widely-cited workflow: >=50 trades, >=55% win rate on
    resolved positions, positive P&L.
    """
    filtered = [
        s
        for s in scores
        if s.trade_count >= min_trades
        and s.total_pnl >= min_pnl
        and s.resolved_positions >= require_resolved
        and (s.win_rate is None or s.win_rate >= min_win_rate)
    ]
    return sorted(filtered, key=lambda s: s.weighted_score(), reverse=True)

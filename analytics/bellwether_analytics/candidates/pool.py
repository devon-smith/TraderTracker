"""Candidate pool: filter + rank wallets, and persist to candidate_score.

Baseline filters follow the study: >= min resolved trades, >= min win rate,
non-negative realized P&L. Config-driven and regenerable on demand.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from ..core import (
    RankConfig,
    cashflow_pnl_by_wallet,
    performance_by_wallet,
    rank,
    specialization_by_wallet,
)


@dataclass
class PoolConfig:
    min_resolved_trades: int = 50
    min_win_rate: float = 0.55
    min_pnl: float = 0.0
    target_size: int = 500

    def rank_config(self) -> RankConfig:
        return RankConfig(
            min_resolved_trades=self.min_resolved_trades,
            min_win_rate=self.min_win_rate,
            min_realized_pnl=self.min_pnl,
        )


def build_pool(
    trades: pd.DataFrame,
    events: Optional[pd.DataFrame] = None,
    config: Optional[PoolConfig] = None,
) -> pd.DataFrame:
    """Return the ranked candidate pool (index: wallet), capped at target_size."""
    config = config or PoolConfig()
    events = events if events is not None else pd.DataFrame(columns=["wallet", "event_type", "value"])

    perf = performance_by_wallet(trades)
    spec = specialization_by_wallet(trades)
    ranked = rank(perf, spec, config.rank_config())
    if ranked.empty:
        return ranked

    pnl = cashflow_pnl_by_wallet(trades, events)
    out = ranked.join(pnl[["net_cashflow"]])
    return out.head(config.target_size)


def persist_pool(pool: pd.DataFrame, platform: str, dsn: Optional[str] = None) -> int:
    """Upsert the pool into candidate_score (wallet_id = external id). Returns rows."""
    from bellwether_ingestion.db.models import CandidateScore
    from bellwether_ingestion.db.session import sync_dsn
    from sqlalchemy import create_engine
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    def _int(x) -> int:
        return 0 if x is None or pd.isna(x) else int(x)

    def _float(x):
        return None if x is None or pd.isna(x) else float(x)

    def _str(x):
        return None if x is None or pd.isna(x) else str(x)

    now = dt.datetime.now(tz=dt.timezone.utc)
    rows = []
    for wallet, r in pool.iterrows():
        rows.append(
            {
                "platform": platform,
                "wallet_id": str(wallet),
                "trade_count": _int(r.get("trade_count")),
                "total_volume": _float(r.get("total_volume")) or 0.0,
                "total_pnl": _float(r.get("realized_pnl")) or 0.0,
                "win_rate": _float(r.get("win_rate")),
                "resolved_positions": _int(r.get("resolved_positions")),
                "top_category": _str(r.get("top_category")),
                "concentration": _float(r.get("hhi")),
                "score": _float(r.get("score")),
                "computed_ts": now,
            }
        )
    if not rows:
        return 0

    engine = create_engine(sync_dsn(dsn))
    try:
        with engine.begin() as conn:
            stmt = pg_insert(CandidateScore).values(rows)
            update_cols = {
                c: stmt.excluded[c]
                for c in (
                    "trade_count", "total_volume", "total_pnl", "win_rate",
                    "resolved_positions", "top_category", "concentration", "score", "computed_ts",
                )
            }
            stmt = stmt.on_conflict_do_update(
                index_elements=["platform", "wallet_id"], set_=update_cols
            )
            conn.execute(stmt)
    finally:
        engine.dispose()
    return len(rows)

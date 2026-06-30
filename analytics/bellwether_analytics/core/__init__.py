"""Platform-agnostic analytics primitives computed from the canonical tables.

The same functions run on Manifold and Polymarket data — the whole point of the
canonical schema. Pure compute functions take a trades DataFrame; the `load_*`
helpers pull that DataFrame from the DB.
"""

from .performance import performance_by_wallet, position_settlements
from .pnl import cashflow_pnl_by_wallet
from .queries import load_events_df, load_trades_df
from .ranking import RankConfig, load_config, rank
from .specialization import specialization_by_wallet

__all__ = [
    "performance_by_wallet",
    "position_settlements",
    "cashflow_pnl_by_wallet",
    "specialization_by_wallet",
    "load_trades_df",
    "load_events_df",
    "RankConfig",
    "load_config",
    "rank",
]

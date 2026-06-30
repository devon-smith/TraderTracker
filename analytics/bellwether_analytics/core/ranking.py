"""Config-driven candidate ranking. Thresholds + weights live in a YAML/TOML file,
never hardcoded, so a ranking is reproducible from config + the DB."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd


@dataclass
class RankConfig:
    # Filters
    min_resolved_trades: int = 50
    min_win_rate: float = 0.55
    min_specialization: float = 0.0  # HHI floor (0 = no filter)
    min_realized_pnl: float = 0.0
    # Score weights
    w_win_rate: float = 0.4
    w_pnl: float = 0.3
    w_specialization: float = 0.3
    pnl_norm: float = 10_000.0  # P&L that maps to ~0.76 of the pnl term (tanh)

    @classmethod
    def from_dict(cls, d: dict) -> "RankConfig":
        known = {f for f in cls.__dataclass_fields__}  # noqa: E1101
        return cls(**{k: v for k, v in (d or {}).items() if k in known})


def load_config(path: str | Path) -> RankConfig:
    path = Path(path)
    text = path.read_text()
    if path.suffix in (".yaml", ".yml"):
        import yaml

        data = yaml.safe_load(text) or {}
    elif path.suffix == ".toml":
        import tomllib

        data = tomllib.loads(text)
    else:
        raise ValueError(f"unsupported config format: {path.suffix}")
    # allow a top-level 'ranking' table
    if "ranking" in data and isinstance(data["ranking"], dict):
        data = data["ranking"]
    return RankConfig.from_dict(data)


def rank(
    performance: pd.DataFrame,
    specialization: pd.DataFrame,
    config: Optional[RankConfig] = None,
) -> pd.DataFrame:
    """Join performance + specialization, filter by thresholds, score, and sort.

    Returns a DataFrame sorted by `score` descending, with the filter inputs and
    the score column, indexed by wallet.
    """
    config = config or RankConfig()
    df = performance.join(specialization, how="left")

    mask = (
        (df["resolved_trade_count"].fillna(0) >= config.min_resolved_trades)
        & (df["win_rate"].fillna(0) >= config.min_win_rate)
        & (df["hhi"].fillna(0) >= config.min_specialization)
        & (df["realized_pnl"].fillna(0) >= config.min_realized_pnl)
    )
    df = df[mask].copy()

    def _num(x) -> float:
        return 0.0 if x is None or (isinstance(x, float) and math.isnan(x)) else float(x)

    def _score(row) -> float:
        wr = _num(row.get("win_rate"))
        pnl_term = math.tanh(_num(row.get("realized_pnl")) / config.pnl_norm)
        hhi = _num(row.get("hhi"))
        return (
            config.w_win_rate * wr
            + config.w_pnl * pnl_term
            + config.w_specialization * hhi
        )

    df["score"] = df.apply(_score, axis=1)
    return df.sort_values("score", ascending=False)

"""Strategy -> profitability synthesis.

Reframes the deliverable from "top accounts" to "profitable strategy TEMPLATES".
Joins archetype/template labels to realized P&L from the EXISTING Phase-3 engine
(performance_by_wallet) and ranks (archetype, market-family) templates by
risk-adjusted, strictly out-of-sample P&L — with a shuffled-label control.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..core import performance_by_wallet
from .archetypes import classify
from .features import extract_features
from .recurrence import wallet_family_recurrence


def _agg(df: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    g = df.groupby(by).agg(
        n_wallets=("pnl", "size"),
        median_pnl=("pnl", "median"),
        mean_pnl=("pnl", "mean"),
        std_pnl=("pnl", "std"),
        total_pnl=("pnl", "sum"),
        pct_profitable=("pnl", lambda s: float((s > 0).mean())),
    )
    g["sharpe"] = g["median_pnl"] / (g["std_pnl"].fillna(0.0) + 1e-9)
    return g


def archetype_pnl(archetype: pd.Series, pnl: pd.Series) -> pd.DataFrame:
    """Per-archetype realized-P&L distribution across the wallets carrying it."""
    df = pd.DataFrame({"archetype": archetype, "pnl": pnl}).dropna(subset=["archetype"])
    df["pnl"] = df["pnl"].fillna(0.0)
    if df.empty:
        return pd.DataFrame()
    return _agg(df, ["archetype"]).sort_values("median_pnl", ascending=False)


def template_pnl(trades: pd.DataFrame, archetype: pd.Series, pnl: pd.Series) -> pd.DataFrame:
    """Per (archetype, top market-family) template realized-P&L distribution."""
    fam = wallet_family_recurrence(trades)["top_family"]
    df = pd.DataFrame({"archetype": archetype, "family": fam, "pnl": pnl}).dropna(subset=["archetype"])
    df["family"] = df["family"].fillna("unknown")
    df["pnl"] = df["pnl"].fillna(0.0)
    if df.empty:
        return pd.DataFrame()
    return _agg(df, ["archetype", "family"]).reset_index().sort_values(
        "median_pnl", ascending=False
    )


def rank_templates(
    trades: pd.DataFrame,
    split_ts,
    shuffle: bool = False,
    seed: int = 0,
) -> pd.DataFrame:
    """STRICT out-of-sample: fit archetype/template labels on the window BEFORE
    split_ts, measure realized P&L on the window AFTER. `shuffle=True` permutes the
    label->P&L association (the control: a real edge must vanish)."""
    df = trades.copy()
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    split = pd.Timestamp(split_ts)
    if split.tzinfo is None:
        split = split.tz_localize("UTC")
    train = df[df["ts"] < split]
    test = df[df["ts"] >= split]
    if train.empty or test.empty:
        return pd.DataFrame()

    labeled = classify(extract_features(train))
    fam = wallet_family_recurrence(train)["top_family"]
    test_pnl = performance_by_wallet(test)
    pnl = test_pnl["realized_pnl"] if "realized_pnl" in test_pnl else pd.Series(dtype=float)

    out = pd.DataFrame({"archetype": labeled["archetype"], "family": fam}).join(
        pnl.rename("pnl")
    )
    out = out.dropna(subset=["archetype"])
    out["family"] = out["family"].fillna("unknown")
    out["pnl"] = out["pnl"].fillna(0.0)
    if out.empty:
        return pd.DataFrame()

    if shuffle:
        rng = np.random.default_rng(seed)
        out["pnl"] = rng.permutation(out["pnl"].to_numpy())

    return _agg(out, ["archetype", "family"]).reset_index().sort_values(
        "median_pnl", ascending=False
    )

"""Strategy -> profitability synthesis (the project's core question).

Reframes the deliverable from "top accounts" to "feasible strategy TEMPLATES".
Joins archetype/template labels to realized P&L from the EXISTING Phase-3 engine
(performance_by_wallet) and ranks (archetype, market-family) templates by
risk-adjusted, strictly out-of-sample P&L — with a shuffled-label control,
persistence over time, and a capacity proxy (P&L vs position size).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..core import performance_by_wallet
from .archetypes import classify
from .features import extract_features
from .recurrence import wallet_family_recurrence


def _capacity_corr(g: pd.DataFrame) -> float:
    """Correlation of per-wallet avg position size vs P&L within a template.
    Negative -> bigger size does worse (capacity-limited); ~0/positive -> edge scales."""
    if len(g) < 3 or g["avg_size"].nunique() < 2 or g["pnl"].nunique() < 2:
        return float("nan")
    return float(np.corrcoef(g["avg_size"], g["pnl"])[0, 1])


def _template_table(df: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    """Aggregate a per-wallet (template, pnl, avg_size, volume) frame into template
    rows with the full distribution + capacity proxy."""
    def agg(g: pd.DataFrame) -> pd.Series:
        pnl = g["pnl"]
        total_vol = float(g["volume"].sum())
        return pd.Series({
            "n_wallets": int(len(g)),
            "median_pnl": float(pnl.median()),
            "mean_pnl": float(pnl.mean()),
            "std_pnl": float(pnl.std(ddof=0)),
            "total_pnl": float(pnl.sum()),
            "pct_profitable": float((pnl > 0).mean()),
            "total_volume": total_vol,
            "pnl_per_volume": float(pnl.sum() / total_vol) if total_vol > 0 else float("nan"),
            "capacity_corr": _capacity_corr(g),
        })

    out = df.groupby(by, group_keys=False).apply(agg, include_groups=False)
    out["sharpe"] = out["median_pnl"] / (out["std_pnl"].replace(0, np.nan) + 1e-9)
    return out.reset_index()


def archetype_pnl(archetype: pd.Series, pnl: pd.Series) -> pd.DataFrame:
    """Per-archetype realized-P&L distribution across the wallets carrying it."""
    df = pd.DataFrame({"archetype": archetype, "pnl": pnl}).dropna(subset=["archetype"])
    df["pnl"] = df["pnl"].fillna(0.0)
    if df.empty:
        return pd.DataFrame()
    g = df.groupby("archetype")["pnl"].agg(
        n_wallets="size", median_pnl="median", mean_pnl="mean", std_pnl="std",
        total_pnl="sum", pct_profitable=lambda s: float((s > 0).mean()),
    )
    g["sharpe"] = g["median_pnl"] / (g["std_pnl"].fillna(0.0) + 1e-9)
    return g.sort_values("median_pnl", ascending=False)


def template_pnl(trades: pd.DataFrame, archetype: pd.Series, pnl: pd.Series) -> pd.DataFrame:
    """Per (archetype, top market-family) template distribution + capacity proxy."""
    fam = wallet_family_recurrence(trades)["top_family"]
    avg_size = trades.groupby("wallet")["notional"].mean().rename("avg_size")
    volume = trades.groupby("wallet")["notional"].sum().rename("volume")
    df = (
        pd.DataFrame({"archetype": archetype, "family": fam})
        .join(pnl.rename("pnl")).join(avg_size).join(volume)
        .dropna(subset=["archetype"])
    )
    df["family"] = df["family"].fillna("unknown")
    df[["pnl", "avg_size", "volume"]] = df[["pnl", "avg_size", "volume"]].fillna(0.0)
    if df.empty:
        return pd.DataFrame()
    return _template_table(df, ["archetype", "family"]).sort_values("median_pnl", ascending=False)


def _persistence(
    test: pd.DataFrame, template_map: pd.DataFrame, n_periods: int, shuffle: bool, seed: int
) -> pd.DataFrame:
    """Fraction of test sub-periods in which each template's median P&L is positive."""
    ts = pd.to_datetime(test["ts"], utc=True)
    edges = pd.date_range(ts.min(), ts.max(), periods=n_periods + 1)
    rng = np.random.default_rng(seed)
    medians = []
    for k in range(n_periods):
        lo, hi = edges[k], edges[k + 1]
        mask = (ts >= lo) & ((ts <= hi) if k == n_periods - 1 else (ts < hi))
        sub = test[mask.values]
        if sub.empty:
            continue
        perf = performance_by_wallet(sub)
        if "realized_pnl" not in perf:
            continue
        d = template_map.join(perf["realized_pnl"].rename("pnl"))
        d["pnl"] = d["pnl"].fillna(0.0)
        if shuffle:
            d["pnl"] = rng.permutation(d["pnl"].to_numpy())
        medians.append(d.groupby(["archetype", "family"])["pnl"].median())
    if not medians:
        return pd.DataFrame(columns=["archetype", "family", "persistence"])
    mat = pd.concat(medians, axis=1)
    denom = mat.notna().sum(axis=1).replace(0, np.nan)
    persistence = ((mat > 0).sum(axis=1) / denom).rename("persistence")
    return persistence.reset_index()


def rank_templates(
    trades: pd.DataFrame,
    split_ts,
    n_periods: int = 3,
    shuffle: bool = False,
    seed: int = 0,
) -> pd.DataFrame:
    """STRICT out-of-sample: fit archetype/template labels on the window BEFORE
    split_ts, measure realized P&L on the window AFTER. Returns the ranked template
    table (by median out-of-sample P&L) with win rate, consistency (sharpe),
    distinct-wallet count, persistence across sub-periods, and a capacity proxy.
    `shuffle=True` permutes the label->P&L association (the control: edge must vanish)."""
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
    template_map = pd.DataFrame({"archetype": labeled["archetype"], "family": fam}).dropna(
        subset=["archetype"]
    )
    template_map["family"] = template_map["family"].fillna("unknown")

    perf = performance_by_wallet(test)
    pnl = perf["realized_pnl"] if "realized_pnl" in perf else pd.Series(dtype=float)
    avg_size = test.groupby("wallet")["notional"].mean().rename("avg_size")
    volume = test.groupby("wallet")["notional"].sum().rename("volume")

    base = template_map.join(pnl.rename("pnl")).join(avg_size).join(volume)
    base[["pnl", "avg_size", "volume"]] = base[["pnl", "avg_size", "volume"]].fillna(0.0)
    if base.empty:
        return pd.DataFrame()
    if shuffle:
        rng = np.random.default_rng(seed)
        base["pnl"] = rng.permutation(base["pnl"].to_numpy())

    table = _template_table(base, ["archetype", "family"])
    persistence = _persistence(test, template_map, n_periods, shuffle, seed)
    table = table.merge(persistence, on=["archetype", "family"], how="left")
    return table.sort_values("median_pnl", ascending=False).reset_index(drop=True)

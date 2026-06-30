"""Walk-forward, out-of-sample validation of the candidate ranking.

Rank wallets on data BEFORE a split time, then measure whether the top-ranked
half actually outperformed on resolved markets AFTER the split. A shuffled-label
control (permute the test outcomes across wallets) must show ~no edge — guarding
against survivorship/luck masquerading as skill.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..core import performance_by_wallet


def walk_forward(
    trades: pd.DataFrame,
    split_ts,
    rank_metric: str = "win_rate",
    outcome_metric: str = "realized_pnl",
    seed: int = 0,
) -> dict:
    """Return {edge, edge_shuffled, n, n_top, n_bottom, split_ts}.

    edge = mean(test outcome | top-half train rank) - mean(... | bottom-half).
    edge_shuffled = same after permuting the test outcomes (control).
    """
    df = trades.copy()
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    split = pd.Timestamp(split_ts)
    if split.tzinfo is None:
        split = split.tz_localize("UTC")

    train = df[df["ts"] < split]
    test = df[df["ts"] >= split]

    perf_tr = performance_by_wallet(train) if not train.empty else pd.DataFrame()
    perf_te = performance_by_wallet(test) if not test.empty else pd.DataFrame()

    nan = float("nan")
    if rank_metric not in perf_tr or outcome_metric not in perf_te:
        return {"edge": nan, "edge_shuffled": nan, "n": 0, "n_top": 0, "n_bottom": 0,
                "split_ts": str(split)}

    joined = pd.DataFrame(
        {"rank": perf_tr[rank_metric], "outcome": perf_te[outcome_metric]}
    ).dropna()
    if len(joined) < 2:
        return {"edge": nan, "edge_shuffled": nan, "n": len(joined), "n_top": 0,
                "n_bottom": 0, "split_ts": str(split)}

    median = joined["rank"].median()
    top = joined[joined["rank"] > median]
    bottom = joined[joined["rank"] <= median]
    if top.empty:  # all-tie at the median -> split by position
        top, bottom = joined.iloc[: len(joined) // 2], joined.iloc[len(joined) // 2 :]

    def _edge(outcomes_by_group: tuple[pd.Series, pd.Series]) -> float:
        t, b = outcomes_by_group
        return float(t.mean() - b.mean())

    edge = _edge((top["outcome"], bottom["outcome"]))

    rng = np.random.default_rng(seed)
    shuffled = joined["outcome"].to_numpy().copy()
    rng.shuffle(shuffled)
    shuf = joined.assign(outcome=shuffled)
    s_top = shuf.loc[top.index, "outcome"]
    s_bottom = shuf.loc[bottom.index, "outcome"]
    edge_shuffled = _edge((s_top, s_bottom))

    return {
        "edge": edge,
        "edge_shuffled": edge_shuffled,
        "n": len(joined),
        "n_top": len(top),
        "n_bottom": len(bottom),
        "split_ts": str(split),
    }

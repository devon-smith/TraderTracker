"""Real-data trackability (a better Experiment A).

A confirmed copy-chain is empirical proof of trackability — stronger than a
simulated copy. For each significant (leader, follower) pair we measure what the
follower ACTUALLY captured: the entry-price delta vs the leader, the time gap, and
(when resolved) the realized-P&L delta. These aggregate into a per-leader
"empirically copyable" score.

NOTE: on-chain block-gap needs block numbers from the (RPC-gated) on-chain
listener; the available proxy here is the wall-clock time gap.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


def _vwap(g: pd.DataFrame) -> Optional[float]:
    buys = g[g["side"].astype(str).str.upper() == "BUY"]
    sz = buys["size"].sum()
    return float((buys["notional"].sum() / sz)) if sz > 0 else None


def pair_copy_metrics(trades: pd.DataFrame, leader: str, follower: str) -> pd.DataFrame:
    """Per shared (market, outcome): leader/follower entry VWAP, entry_delta
    (follower - leader; positive = follower paid more), and time_gap_seconds."""
    cols = ["market", "outcome", "leader_entry", "follower_entry", "entry_delta", "time_gap_seconds"]
    if trades.empty:
        return pd.DataFrame(columns=cols)
    df = trades.copy()
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    L = df[df["wallet"] == leader]
    F = df[df["wallet"] == follower]

    rows = []
    for (market, outcome), lg in L.groupby(["market", "outcome"]):
        fg = F[(F["market"] == market) & (F["outcome"] == outcome)]
        if fg.empty:
            continue
        l_entry, f_entry = _vwap(lg), _vwap(fg)
        if l_entry is None or f_entry is None:
            continue
        l_first = lg[lg["side"].astype(str).str.upper() == "BUY"]["ts"].min()
        f_first = fg[fg["side"].astype(str).str.upper() == "BUY"]["ts"].min()
        if pd.isna(l_first) or pd.isna(f_first):
            continue
        rows.append({
            "market": market, "outcome": outcome,
            "leader_entry": l_entry, "follower_entry": f_entry,
            "entry_delta": f_entry - l_entry,
            "time_gap_seconds": (f_first - l_first).total_seconds(),
        })
    return pd.DataFrame(rows, columns=cols)


def copyable_score(metrics: pd.DataFrame, gap_scale_seconds: float = 30.0) -> float:
    """0..1: how closely (small |entry_delta|) and quickly (small, positive time
    gap) a follower tracked the leader. Empty -> 0."""
    if metrics.empty:
        return 0.0
    closeness = 1.0 / (1.0 + float(metrics["entry_delta"].abs().median()))
    gaps = metrics["time_gap_seconds"].clip(lower=0)  # negative = led, not copied
    speed = 1.0 / (1.0 + float(gaps.median()) / gap_scale_seconds)
    return float(0.5 * closeness + 0.5 * speed)


def rank_leaders(trades: pd.DataFrame, pairs: pd.DataFrame, gap_scale_seconds: float = 30.0) -> pd.DataFrame:
    """Per leader (from significance-filtered lead-lag pairs), the empirical
    copyability score aggregated over its followers + the captured edge spread."""
    cols = ["leader", "n_followers", "n_copied_positions", "copyable_score",
            "median_entry_delta", "median_time_gap_seconds"]
    if pairs.empty:
        return pd.DataFrame(columns=cols)

    out = []
    for leader, grp in pairs.groupby("leader"):
        all_metrics = []
        for follower in grp["follower"].unique():
            m = pair_copy_metrics(trades, leader, follower)
            if not m.empty:
                all_metrics.append(m)
        if not all_metrics:
            continue
        metrics = pd.concat(all_metrics, ignore_index=True)
        out.append({
            "leader": leader,
            "n_followers": int(grp["follower"].nunique()),
            "n_copied_positions": int(len(metrics)),
            "copyable_score": copyable_score(metrics, gap_scale_seconds),
            "median_entry_delta": float(metrics["entry_delta"].median()),
            "median_time_gap_seconds": float(np.median(metrics["time_gap_seconds"])),
        })
    if not out:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(out).sort_values("copyable_score", ascending=False).reset_index(drop=True)

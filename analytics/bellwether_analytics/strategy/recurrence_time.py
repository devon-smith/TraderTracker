"""Temporal (in-time) recurrence — the same strategy repeated over time within one
account, distinct from market_family (recurrence across markets).

- periodicity: how regular is a wallet's trade cadence in a market family?
  Regularity = 1/(1+CV) of inter-event gaps (CV≈0 periodic → ~1; CV≈1 random →
  ~0.5; bursty → lower). Dominant period = median inter-event gap.
- cycle_motifs: repeated entry→accumulate→exit/redeem cycles. A cycle is a market
  the wallet entered (BUY) and closed (SELL or REDEEM/MERGE). Returns cycle count,
  median cadence, and intra-cycle duration consistency.
- recurrence_in_time_report: aggregate over a wallet's most-active family.
"""

from __future__ import annotations

from statistics import median
from typing import Optional

import numpy as np
import pandas as pd

from .archetypes import StrategyConfig
from .recurrence import _family_series


def _regularity(gaps_seconds) -> tuple[float, Optional[float]]:
    g = np.asarray([x for x in gaps_seconds if x and x > 0], dtype=float)
    if len(g) < 2:
        return 0.0, (float(g[0]) if len(g) == 1 else None)
    mean = g.mean()
    cv = (g.std() / mean) if mean > 0 else float("inf")
    return float(1.0 / (1.0 + cv)), float(np.median(g))


def _filter(trades: pd.DataFrame, wallet: str, family: Optional[str]) -> pd.DataFrame:
    df = trades[trades["wallet"] == wallet].copy()
    if family is not None and not df.empty:
        df = df[_family_series(df) == family]
    return df


def periodicity(trades: pd.DataFrame, wallet: str, family: Optional[str] = None) -> dict:
    df = _filter(trades, wallet, family)
    ts = sorted(pd.to_datetime(df["ts"], utc=True).tolist())
    gaps = [(ts[i] - ts[i - 1]).total_seconds() for i in range(1, len(ts))]
    regularity, period = _regularity(gaps)
    return {
        "n_events": len(ts),
        "regularity": regularity,
        "dominant_period_seconds": period,
        "mean_gap_seconds": float(np.mean(gaps)) if gaps else None,
    }


def cycle_motifs(
    trades: pd.DataFrame, events: Optional[pd.DataFrame], wallet: str, family: Optional[str] = None
) -> dict:
    tt = _filter(trades, wallet, family)
    ev = events[events["wallet"] == wallet] if events is not None and not events.empty else None

    cycles = []
    for market, g in tt.groupby("market"):
        side = g["side"].astype(str).str.upper()
        buys = pd.to_datetime(g.loc[side == "BUY", "ts"], utc=True)
        if buys.empty:
            continue
        entry = buys.min()
        closes = list(pd.to_datetime(g.loc[side == "SELL", "ts"], utc=True))
        if ev is not None and "market" in ev.columns:
            evm = ev[(ev["market"] == market) & (ev["event_type"].isin(["REDEEM", "MERGE"]))]
            closes += list(pd.to_datetime(evm["ts"], utc=True))
        closes = [c for c in closes if c >= entry]
        if not closes:
            continue  # still open -> not a completed cycle
        cycles.append({"entry": entry, "duration": (min(closes) - entry).total_seconds()})

    n = len(cycles)
    if n == 0:
        return {"n_cycles": 0, "median_cycle_duration_seconds": None,
                "median_cycle_start_gap_seconds": None, "cycle_consistency": 0.0}
    starts = sorted(c["entry"] for c in cycles)
    start_gaps = [(starts[i] - starts[i - 1]).total_seconds() for i in range(1, len(starts))]
    durations = [c["duration"] for c in cycles]
    consistency, _ = _regularity(durations) if len(durations) >= 2 else (1.0, None)
    return {
        "n_cycles": n,
        "median_cycle_duration_seconds": float(median(durations)),
        "median_cycle_start_gap_seconds": float(median(start_gaps)) if start_gaps else None,
        "cycle_consistency": consistency,
    }


def recurrence_in_time_report(
    trades: pd.DataFrame,
    events: Optional[pd.DataFrame],
    wallet: str,
    config: Optional[StrategyConfig] = None,
) -> dict:
    """Most-active family for a wallet + its periodicity, cycle motifs, and an
    is_recurring flag (regular cadence AND enough completed cycles)."""
    config = config or StrategyConfig()
    df = trades[trades["wallet"] == wallet].copy()
    if df.empty:
        return {"wallet": wallet, "top_family": None, "is_recurring": False, "n_events": 0}
    df["family"] = _family_series(df)
    family = df.groupby("family")["notional"].sum().idxmax()

    per = periodicity(trades, wallet, family)
    cyc = cycle_motifs(trades, events, wallet, family)
    is_recurring = bool(
        per["regularity"] >= config.recurrence_regular_threshold
        and cyc["n_cycles"] >= config.recurrence_min_cycles
    )
    return {"wallet": wallet, "top_family": str(family), "is_recurring": is_recurring, **per, **cyc}

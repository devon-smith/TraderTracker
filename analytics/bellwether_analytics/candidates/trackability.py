"""Trackability pre-score: how plausibly *copyable* a wallet is.

Slow, high-conviction, deep-market wallets are easier to copy within a useful
latency/slippage budget than HFT-style wallets churning thin markets. This is the
input filter to Experiment A (Prompt 9), not a performance metric.

Proxies (true order-book depth needs the CLOB /book feed — a documented TODO):
  - cadence: trades per active day (slower = better)
  - avg_notional: bigger average fills imply deeper markets / higher conviction
  - median_gap_seconds: longer gaps between fills = more reaction time
Each is min-max normalized across wallets and combined into a 0..1 score.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _minmax(s: pd.Series) -> pd.Series:
    lo, hi = s.min(), s.max()
    if not np.isfinite(lo) or not np.isfinite(hi) or hi == lo:
        return pd.Series(0.5, index=s.index)
    return (s - lo) / (hi - lo)


def trackability_score(
    trades: pd.DataFrame,
    w_cadence: float = 0.4,
    w_notional: float = 0.3,
    w_gap: float = 0.3,
) -> pd.DataFrame:
    """Index: wallet. Columns: trades, trades_per_day, avg_notional,
    median_gap_seconds, trackability."""
    if trades.empty:
        return pd.DataFrame(
            columns=["trades", "trades_per_day", "avg_notional", "median_gap_seconds", "trackability"]
        ).rename_axis("wallet")

    df = trades.copy()
    df["ts"] = pd.to_datetime(df["ts"], utc=True)

    rows = []
    for wallet, g in df.sort_values("ts").groupby("wallet"):
        ts = g["ts"]
        span_days = max((ts.max() - ts.min()).total_seconds() / 86400.0, 1e-9)
        n = len(g)
        trades_per_day = n / span_days
        gaps = ts.diff().dropna().dt.total_seconds()
        median_gap = float(gaps.median()) if not gaps.empty else 0.0
        rows.append(
            {
                "wallet": wallet,
                "trades": n,
                "trades_per_day": trades_per_day,
                "avg_notional": float(g["notional"].mean()),
                "median_gap_seconds": median_gap,
            }
        )
    out = pd.DataFrame(rows).set_index("wallet")

    # Slower cadence is better -> invert. Bigger notional + longer gaps are better.
    slow = 1.0 - _minmax(out["trades_per_day"])
    deep = _minmax(out["avg_notional"])
    patient = _minmax(out["median_gap_seconds"])
    out["trackability"] = w_cadence * slow + w_notional * deep + w_gap * patient
    return out.sort_values("trackability", ascending=False)

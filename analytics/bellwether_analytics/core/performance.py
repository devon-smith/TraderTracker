"""Per-wallet performance metrics over *resolved* markets.

Settlement model (intentionally simple for the prototype; Prompt 6 hardens P&L
with SPLIT/MERGE/REDEEM/CONVERSION):

  For each (wallet, market, outcome) position on a resolved market:
    net_shares = sum(BUY size) - sum(SELL size)
    net_cost   = sum(BUY notional) - sum(SELL notional)      # net cash out
    payout     = 1 if str(outcome) == str(resolution) else 0
    realized_pnl = net_shares * payout - net_cost
    win        = realized_pnl > 0

ROI = sum(realized_pnl) / sum(buy_cost). Win rate = share of winning positions.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

REQUIRED_COLUMNS = {
    "wallet", "market", "category", "outcome", "side",
    "size", "price", "notional", "ts", "resolution", "resolved_at",
}


def _prepare(df: pd.DataFrame) -> pd.DataFrame:
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"trades frame missing columns: {sorted(missing)}")
    df = df.copy()
    # Coerce time columns to a single tz-aware dtype (robust to mixed tz-aware/naive
    # inputs, which otherwise collapse to object dtype and break date arithmetic).
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df["resolved_at"] = pd.to_datetime(df["resolved_at"], utc=True)
    is_buy = df["side"].astype(str).str.upper() == "BUY"
    df["signed_size"] = np.where(is_buy, df["size"], -df["size"])
    df["signed_cost"] = np.where(is_buy, df["notional"], -df["notional"])
    df["buy_notional"] = np.where(is_buy, df["notional"], 0.0)
    df["resolved"] = df["resolution"].notna() & df["resolved_at"].notna()
    return df


def position_settlements(df: pd.DataFrame) -> pd.DataFrame:
    """One row per resolved (wallet, market, outcome) position with realized P&L."""
    df = _prepare(df)
    res = df[df["resolved"]]
    if res.empty:
        return pd.DataFrame(
            columns=["wallet", "market", "outcome", "net_shares", "net_cost",
                     "buy_cost", "resolution", "payout", "realized_pnl", "win",
                     "first_ts", "resolved_at", "hold_seconds"]
        )
    grp = res.groupby(["wallet", "market", "outcome"], dropna=False)
    settle = grp.agg(
        net_shares=("signed_size", "sum"),
        net_cost=("signed_cost", "sum"),
        buy_cost=("buy_notional", "sum"),
        resolution=("resolution", "first"),
        resolved_at=("resolved_at", "first"),
        first_ts=("ts", "min"),
    ).reset_index()
    settle["payout"] = (
        settle["outcome"].astype(str) == settle["resolution"].astype(str)
    ).astype(float)
    settle["realized_pnl"] = settle["net_shares"] * settle["payout"] - settle["net_cost"]
    settle["win"] = settle["realized_pnl"] > 0
    settle["hold_seconds"] = (
        settle["resolved_at"] - settle["first_ts"]
    ).dt.total_seconds()
    return settle


def performance_by_wallet(df: pd.DataFrame) -> pd.DataFrame:
    """Per-wallet metrics. Index: wallet. Columns: trade_count,
    resolved_trade_count, resolved_positions, realized_pnl, roi, win_rate,
    avg_hold_seconds."""
    prepared = _prepare(df)
    trade_count = prepared.groupby("wallet").size().rename("trade_count")
    resolved_trade_count = (
        prepared[prepared["resolved"]].groupby("wallet").size().rename("resolved_trade_count")
    )

    settle = position_settlements(df)
    if settle.empty:
        out = trade_count.to_frame()
        out["resolved_trade_count"] = resolved_trade_count
        for col in ["resolved_positions", "realized_pnl", "roi", "win_rate", "avg_hold_seconds"]:
            out[col] = np.nan
        return out.fillna({"resolved_trade_count": 0}).reset_index().set_index("wallet")

    agg = settle.groupby("wallet").agg(
        resolved_positions=("realized_pnl", "size"),
        realized_pnl=("realized_pnl", "sum"),
        buy_cost=("buy_cost", "sum"),
        wins=("win", "sum"),
        avg_hold_seconds=("hold_seconds", "mean"),
    )
    agg["win_rate"] = agg["wins"] / agg["resolved_positions"]
    agg["roi"] = agg["realized_pnl"] / agg["buy_cost"].replace(0, np.nan)

    out = pd.concat([trade_count, resolved_trade_count, agg], axis=1)
    out["resolved_trade_count"] = out["resolved_trade_count"].fillna(0).astype(int)
    out["resolved_positions"] = out["resolved_positions"].fillna(0).astype(int)
    return out[
        ["trade_count", "resolved_trade_count", "resolved_positions",
         "realized_pnl", "roi", "win_rate", "avg_hold_seconds"]
    ]

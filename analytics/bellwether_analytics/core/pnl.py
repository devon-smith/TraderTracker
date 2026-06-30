"""Robust cash-flow P&L combining trades and position events (Prompt 6).

The settlement model in performance.py needs market resolution and ignores
SPLIT/MERGE/REDEEM. This module reconstructs realized P&L from actual USDC cash
flows, which is correct in the presence of those events:

  trade BUY      -> -notional        (cash out)
  trade SELL     -> +notional        (cash in)
  SPLIT          -> -value           (USDC spent minting YES+NO)
  MERGE          -> +value           (USDC recovered)
  REDEEM         -> +value           (winning shares -> USDC at resolution)
  REWARD         -> +value           (rewards/rebates/yield income)
  CONVERSION     ->  0               (neg-risk reshaping; no net cash)

net_cashflow over a fully-exited wallet == realized P&L. For wallets still
holding open positions it understates P&L by the locked-in share value, and it
is bounded by the API's pagination cap — both documented limitations.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

_EVENT_SIGN = {"SPLIT": -1.0, "MERGE": 1.0, "REDEEM": 1.0, "REWARD": 1.0, "CONVERSION": 0.0}


def cashflow_pnl_by_wallet(trades: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """Per-wallet realized cash-flow P&L + a component breakdown.

    `trades` needs columns: wallet, side, notional.
    `events` needs columns: wallet, event_type, value.
    """
    w_trades = trades["wallet"] if "wallet" in trades.columns else pd.Series(dtype=object)
    w_events = events["wallet"] if "wallet" in events.columns else pd.Series(dtype=object)
    wallets = pd.Index(
        pd.concat([w_trades, w_events]).dropna().unique(), name="wallet"
    )

    cols = ["buy_cost", "sell_proceeds", "split_cost", "merged", "redeemed", "income"]
    out = pd.DataFrame(0.0, index=wallets, columns=cols)

    if not trades.empty:
        t = trades.copy()
        is_buy = t["side"].astype(str).str.upper() == "BUY"
        t["buy_cost"] = np.where(is_buy, t["notional"], 0.0)
        t["sell_proceeds"] = np.where(~is_buy, t["notional"], 0.0)
        tg = t.groupby("wallet")[["buy_cost", "sell_proceeds"]].sum()
        out["buy_cost"] = tg["buy_cost"].reindex(wallets).fillna(0.0)
        out["sell_proceeds"] = tg["sell_proceeds"].reindex(wallets).fillna(0.0)

    if not events.empty:
        e = events.copy()
        e["value"] = e["value"].fillna(0.0)
        by = e.groupby(["wallet", "event_type"])["value"].sum().unstack(fill_value=0.0)
        for evt, col in (("REDEEM", "redeemed"), ("SPLIT", "split_cost"),
                         ("MERGE", "merged"), ("REWARD", "income")):
            if evt in by.columns:
                out[col] = by[evt].reindex(wallets).fillna(0.0)

    out["net_cashflow"] = (
        out["sell_proceeds"] - out["buy_cost"] + out["redeemed"]
        + out["merged"] + out["income"] - out["split_cost"]
    )
    return out[cols + ["net_cashflow"]]

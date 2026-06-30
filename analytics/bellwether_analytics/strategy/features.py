"""Per-wallet behavioral feature vector — the basis for strategy classification.

Pure: takes a canonical trades DataFrame (wallet, market, category, slug, outcome,
side, size, price, notional, ts) and an optional events DataFrame (wallet,
event_type, value). Every feature is interpretable so the downstream archetype
label is explainable.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from .recurrence import wallet_family_recurrence


def extract_features(trades: pd.DataFrame, events: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Index: wallet. Behavioral features per wallet."""
    cols = [
        "n_trades", "trades_per_day", "median_gap_seconds", "avg_notional",
        "total_volume", "buy_ratio", "net_direction", "roundtrip_ratio",
        "n_markets", "top_family", "top_family_share", "n_families",
        "redeem_ratio", "split_merge_ratio", "taker_ratio", "has_aggressor_data",
    ]
    if trades.empty:
        return pd.DataFrame(columns=cols).rename_axis("wallet")

    df = trades.copy()
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    is_buy = df["side"].astype(str).str.upper() == "BUY"
    df["buy_notional"] = np.where(is_buy, df["notional"], 0.0)
    df["sell_notional"] = np.where(~is_buy, df["notional"], 0.0)

    rows = []
    for wallet, g in df.sort_values("ts").groupby("wallet"):
        ts = g["ts"]
        span_days = max((ts.max() - ts.min()).total_seconds() / 86400.0, 1e-9)
        n = len(g)
        gaps = ts.diff().dropna().dt.total_seconds()
        buy_vol = float(g["buy_notional"].sum())
        sell_vol = float(g["sell_notional"].sum())
        total = buy_vol + sell_vol

        # round-tripping: positions where the wallet both bought and sold.
        pos = g.groupby(["market", "outcome"]).apply(
            lambda x: (x["buy_notional"].sum() > 0) and (x["sell_notional"].sum() > 0),
            include_groups=False,
        )
        roundtrip_ratio = float(pos.mean()) if len(pos) else 0.0

        rows.append(
            {
                "wallet": wallet,
                "n_trades": n,
                "trades_per_day": n / span_days,
                "median_gap_seconds": float(gaps.median()) if not gaps.empty else 0.0,
                "avg_notional": float(g["notional"].mean()),
                "total_volume": total,
                "buy_ratio": buy_vol / total if total else 0.0,
                "net_direction": abs(buy_vol - sell_vol) / total if total else 0.0,
                "roundtrip_ratio": roundtrip_ratio,
                "n_markets": int(g["market"].nunique()),
            }
        )
    feats = pd.DataFrame(rows).set_index("wallet")

    rec = wallet_family_recurrence(trades)
    feats = feats.join(rec)

    # Aggressor signal from on-chain fills (is_taker). REST-only wallets have no
    # is_taker -> has_aggressor_data False and taker_ratio falls back to NaN.
    feats["taker_ratio"] = float("nan")
    feats["has_aggressor_data"] = False
    if "is_taker" in df.columns:
        oc = df[df["is_taker"].notna()]
        if not oc.empty:
            tr = oc.groupby("wallet")["is_taker"].mean().rename("taker_ratio")
            cnt = oc.groupby("wallet")["is_taker"].size()
            feats.loc[tr.index, "taker_ratio"] = tr
            feats.loc[cnt.index, "has_aggressor_data"] = True

    # event mix: REDEEM (hold-to-resolution) and SPLIT/MERGE (mint/merge ~ MM/arb).
    feats["redeem_ratio"] = 0.0
    feats["split_merge_ratio"] = 0.0
    if events is not None and not events.empty:
        e = events.copy()
        e["value"] = e["value"].fillna(0.0)
        by = e.groupby(["wallet", "event_type"])["value"].sum().unstack(fill_value=0.0)
        redeem = by.get("REDEEM", pd.Series(0.0, index=by.index))
        split = by.get("SPLIT", pd.Series(0.0, index=by.index))
        merge = by.get("MERGE", pd.Series(0.0, index=by.index))
        denom = feats["total_volume"].replace(0, np.nan)
        feats["redeem_ratio"] = (redeem.reindex(feats.index).fillna(0.0) / denom).fillna(0.0)
        feats["split_merge_ratio"] = (
            (split.add(merge, fill_value=0.0)).reindex(feats.index).fillna(0.0) / denom
        ).fillna(0.0)

    return feats[cols]

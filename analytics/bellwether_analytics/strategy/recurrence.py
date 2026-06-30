"""Market-family normalization + recurrence detection.

Polymarket runs the same market *template* over and over: `btc-updown-5m-1782846000`,
`btc-updown-5m-1782846300`, … are one family (`btc-updown-5m`). Collapsing the
variable suffix lets us measure how much a wallet's activity recurs in a single
templated market type, and which (archetype, family) templates show up across many
accounts — i.e. strategies "implemented over and over."
"""

from __future__ import annotations

import re

import pandas as pd

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_YEAR_RE = re.compile(r"^(19|20)\d{2}$")


def market_family(slug: str | None) -> str:
    """Collapse a market slug to its recurring family by dropping the variable
    parts (timestamps, ids, dates, years)."""
    if not isinstance(slug, str) or not slug:  # None or pandas NaN (a float)
        return "unknown"
    kept = []
    for tok in str(slug).split("-"):
        if tok.isdigit():  # unix ts, sequence id, day/month number
            continue
        if _DATE_RE.match(tok) or _YEAR_RE.match(tok):
            continue
        kept.append(tok)
    return "-".join(kept) or "unknown"


def _family_series(df: pd.DataFrame) -> pd.Series:
    if "slug" in df.columns:
        fam = df["slug"].map(market_family)
    else:
        fam = pd.Series("unknown", index=df.index)
    # fall back to category where the slug yields nothing useful
    if "category" in df.columns:
        fam = fam.where(fam != "unknown", df["category"].fillna("unknown"))
    return fam


def wallet_family_recurrence(trades: pd.DataFrame) -> pd.DataFrame:
    """Per wallet: top market family, its volume share (recurrence), and #families."""
    if trades.empty:
        return pd.DataFrame(
            columns=["top_family", "top_family_share", "n_families"]
        ).rename_axis("wallet")
    df = trades.copy()
    df["family"] = _family_series(df)
    vol = df.groupby(["wallet", "family"])["notional"].sum().rename("v").reset_index()
    total = vol.groupby("wallet")["v"].transform("sum")
    vol["share"] = vol["v"] / total.replace(0, pd.NA)
    top_idx = vol.groupby("wallet")["v"].idxmax()
    top = vol.loc[top_idx, ["wallet", "family", "share"]].set_index("wallet")
    top = top.rename(columns={"family": "top_family", "share": "top_family_share"})
    top["n_families"] = vol.groupby("wallet")["family"].nunique()
    return top[["top_family", "top_family_share", "n_families"]]


def strategy_templates(
    trades: pd.DataFrame, archetypes: pd.Series, min_wallets: int = 2
) -> pd.DataFrame:
    """Strategies implemented over and over: (archetype, market-family) combinations
    run by many distinct wallets. `archetypes` maps wallet -> archetype label."""
    if trades.empty:
        return pd.DataFrame(columns=["archetype", "family", "n_wallets", "volume"])
    df = trades.copy()
    df["family"] = _family_series(df)
    df["archetype"] = df["wallet"].map(archetypes)
    g = df.groupby(["archetype", "family"]).agg(
        n_wallets=("wallet", "nunique"),
        volume=("notional", "sum"),
        trades=("wallet", "size"),
    ).reset_index()
    g = g[g["n_wallets"] >= min_wallets]
    return g.sort_values(["n_wallets", "volume"], ascending=False).reset_index(drop=True)

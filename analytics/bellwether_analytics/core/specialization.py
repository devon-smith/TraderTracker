"""Per-wallet category-specialization via a Herfindahl-Hirschman Index (HHI).

HHI over per-category volume share: sum(share_i^2). 1.0 = a pure specialist
(all volume in one category); ~1/N = a diffuse generalist across N categories.
"""

from __future__ import annotations

import pandas as pd


def specialization_by_wallet(df: pd.DataFrame) -> pd.DataFrame:
    """Index: wallet. Columns: hhi, top_category, top_category_share, n_categories,
    total_volume."""
    if df.empty:
        return pd.DataFrame(
            columns=["hhi", "top_category", "top_category_share", "n_categories", "total_volume"]
        ).rename_axis("wallet")

    work = df.copy()
    work["category"] = work["category"].fillna("unknown")
    vol = (
        work.groupby(["wallet", "category"])["notional"].sum().rename("volume").reset_index()
    )
    total = vol.groupby("wallet")["volume"].transform("sum")
    vol["share"] = vol["volume"] / total.replace(0, pd.NA)

    hhi = vol.groupby("wallet")["share"].apply(lambda s: float((s**2).sum())).rename("hhi")
    n_categories = vol.groupby("wallet")["category"].nunique().rename("n_categories")
    total_volume = vol.groupby("wallet")["volume"].sum().rename("total_volume")

    top_idx = vol.groupby("wallet")["volume"].idxmax()
    top = vol.loc[top_idx, ["wallet", "category", "share"]].set_index("wallet")
    top = top.rename(columns={"category": "top_category", "share": "top_category_share"})

    out = pd.concat([hhi, top, n_categories, total_volume], axis=1)
    return out[["hhi", "top_category", "top_category_share", "n_categories", "total_volume"]]

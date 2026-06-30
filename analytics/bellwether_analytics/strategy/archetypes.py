"""Explainable, rule-based strategy archetype classifier.

Each wallet gets a single archetype label plus the reason (the features that
triggered it). Rules are ordered; the first match wins. Thresholds live in
StrategyConfig so they're tunable, not magic numbers buried in code.

Archetypes:
  market_maker      two-sided, balanced, heavy round-tripping (provides liquidity)
  arbitrageur       significant SPLIT/MERGE usage (mint/merge complementary sets)
  scalper           very high cadence, short gaps, concentrated in one recurring
                    market family (e.g. btc-updown-5m run over and over)
  accumulator       one-directional, low round-trip, building a position
  hold_to_resolution slow, redeems winnings, rarely sells before resolution
  mixed             none of the above dominates
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

STRATEGY_ARCHETYPES = (
    "market_maker", "arbitrageur", "scalper", "accumulator", "hold_to_resolution", "mixed"
)


@dataclass
class StrategyConfig:
    # market_maker
    mm_max_net_direction: float = 0.25
    mm_min_roundtrip: float = 0.5
    mm_min_trades_per_day: float = 5.0
    mm_max_taker_ratio: float = 0.4  # applied only when aggressor data is present
    # arbitrageur
    arb_min_split_merge_ratio: float = 0.1
    # scalper
    scalp_min_trades_per_day: float = 20.0
    scalp_max_median_gap: float = 300.0
    scalp_min_family_share: float = 0.5
    scalp_min_taker_ratio: float = 0.6  # applied only when aggressor data is present
    # accumulator
    acc_min_net_direction: float = 0.6
    acc_max_roundtrip: float = 0.3
    # hold_to_resolution
    hold_max_trades_per_day: float = 2.0
    hold_min_redeem_ratio: float = 0.2
    hold_max_roundtrip: float = 0.3
    # temporal recurrence (in-time, within an account)
    recurrence_regular_threshold: float = 0.6
    recurrence_min_cycles: int = 3


def _classify_row(f: pd.Series, c: StrategyConfig) -> tuple[str, str]:
    fam_share = f.get("top_family_share")
    fam_share = 0.0 if fam_share is None or pd.isna(fam_share) else float(fam_share)
    has_aggr = bool(f.get("has_aggressor_data", False))
    taker = f.get("taker_ratio")
    taker = None if taker is None or pd.isna(taker) else float(taker)

    if (
        f["split_merge_ratio"] >= c.arb_min_split_merge_ratio
    ):
        return "arbitrageur", f"split_merge_ratio={f['split_merge_ratio']:.2f}"

    # market_maker: balanced, round-tripping, active — and a LOW taker ratio when
    # we have aggressor data (a true MM mostly provides liquidity).
    if (
        f["net_direction"] <= c.mm_max_net_direction
        and f["roundtrip_ratio"] >= c.mm_min_roundtrip
        and f["trades_per_day"] >= c.mm_min_trades_per_day
        and (not has_aggr or (taker is not None and taker <= c.mm_max_taker_ratio))
    ):
        reason = f"net_direction={f['net_direction']:.2f}, roundtrip={f['roundtrip_ratio']:.2f}"
        if has_aggr and taker is not None:
            reason += f", taker_ratio={taker:.2f}"
        return "market_maker", reason

    # scalper: rapid, concentrated in one recurring family — and a HIGH taker ratio
    # when aggressor data is present (aggressive taker scalping).
    if (
        f["trades_per_day"] >= c.scalp_min_trades_per_day
        and f["median_gap_seconds"] <= c.scalp_max_median_gap
        and fam_share >= c.scalp_min_family_share
        and (not has_aggr or (taker is not None and taker >= c.scalp_min_taker_ratio))
    ):
        reason = (
            f"trades/day={f['trades_per_day']:.0f}, gap={f['median_gap_seconds']:.0f}s, "
            f"family_share={fam_share:.2f}"
        )
        if has_aggr and taker is not None:
            reason += f", taker_ratio={taker:.2f}"
        return "scalper", reason

    if (
        f["net_direction"] >= c.acc_min_net_direction
        and f["roundtrip_ratio"] <= c.acc_max_roundtrip
    ):
        return "accumulator", f"net_direction={f['net_direction']:.2f}, roundtrip={f['roundtrip_ratio']:.2f}"

    if (
        f["trades_per_day"] <= c.hold_max_trades_per_day
        and f["redeem_ratio"] >= c.hold_min_redeem_ratio
        and f["roundtrip_ratio"] <= c.hold_max_roundtrip
    ):
        return "hold_to_resolution", f"redeem_ratio={f['redeem_ratio']:.2f}"

    return "mixed", "no dominant pattern"


def classify(features: pd.DataFrame, config: StrategyConfig | None = None) -> pd.DataFrame:
    """Return features + 'archetype' + 'reason' columns (index: wallet)."""
    config = config or StrategyConfig()
    if features.empty:
        out = features.copy()
        out["archetype"] = pd.Series(dtype=object)
        out["reason"] = pd.Series(dtype=object)
        return out
    labels = features.apply(lambda r: _classify_row(r, config), axis=1)
    out = features.copy()
    out["archetype"] = [lab[0] for lab in labels]
    out["reason"] = [lab[1] for lab in labels]
    return out

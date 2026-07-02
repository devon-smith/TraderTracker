"""Skill ranking on external-fact markets.

Reuses the existing resolution/P&L engine, market-family normalization, and the
significance/shuffled-control philosophy to rank demonstrably-skilled (not lucky)
strategists on markets that resolve against a knowable external fact, classified
by strategy type (predictor / momentum-rider / favorite-farmer). No new detection
logic — this is analysis on a new, latency-excluded pool.
"""

from .external_fact import (
    beat_market_p,
    calibrated_null_counts,
    classify_by_entry,
    permuted_null_counts,
    predictor_skilled,
    EXTERNAL_FACT_CATEGORIES,
    FAVORITE_FARMER,
    LATENCY_MARKERS,
    MOMENTUM_RIDER,
    PREDICTOR,
    SkillConfig,
    category_recon,
    exclude_latency,
    is_latency_family,
    null_control,
    rank_strategists,
    rank_within_type,
)

__all__ = [
    "beat_market_p",
    "calibrated_null_counts",
    "classify_by_entry",
    "permuted_null_counts",
    "predictor_skilled",
    "SkillConfig",
    "EXTERNAL_FACT_CATEGORIES",
    "LATENCY_MARKERS",
    "PREDICTOR",
    "MOMENTUM_RIDER",
    "FAVORITE_FARMER",
    "category_recon",
    "exclude_latency",
    "is_latency_family",
    "null_control",
    "rank_strategists",
    "rank_within_type",
]

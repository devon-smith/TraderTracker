"""Phase-4 experiments. Experiment A (trackability) is approached here from REAL
follower behavior (trackability_real) rather than a paper-fill simulator — a
confirmed copy-chain is empirical proof of trackability."""

from .trackability_real import copyable_score, pair_copy_metrics, rank_leaders

__all__ = ["pair_copy_metrics", "copyable_score", "rank_leaders"]

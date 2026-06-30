"""Candidate identification + validation (Prompt 8 — the Phase 3 payoff).

Build a filtered, ranked candidate pool; score how plausibly copyable each wallet
is (the input filter to Experiment A); and validate the ranking out-of-sample
with a walk-forward back-test guarded by a shuffled-label control.
"""

from .pool import PoolConfig, build_pool, persist_pool
from .trackability import trackability_score
from .validation import walk_forward

__all__ = [
    "PoolConfig",
    "build_pool",
    "persist_pool",
    "trackability_score",
    "walk_forward",
]

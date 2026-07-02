"""Skill scoring for external-fact strategists.

Three pieces the funnel rests on:
  beat_market_p        one-sided Poisson-binomial test — do an account's realized
                       wins exceed the sum of its entry-price-implied probabilities?
                       (entry price = the market's probability at entry).
  classify_by_entry    predictor / momentum_rider / favorite_farmer from entry prices.
  calibrated_null_counts  the CORRECTLY-SIZED no-skill null: per-position outcome ~
                       Bernoulli(entry_price), i.e. a perfectly calibrated market with
                       zero account skill. Under it the test is exactly `sig`-sized.

Why not permute realized labels: a label permutation imposes the POOL's marginal win
rate, so any selection / favorite-longshot bias (realized > implied) leaks into the
null and inflates it — making a broken test look like "no edge". The Bernoulli(entry)
null draws each outcome from that position's own implied probability, so E[wins] =
sum(entry_price) by construction and the false-positive rate is `sig`.
"""

from __future__ import annotations

import math

import numpy as np


def beat_market_p(entry_price, payout) -> tuple[float, float, float]:
    """(observed_wins, market_expected_wins, one-sided p) that observed > expected."""
    p = np.asarray(entry_price, dtype=float)
    y = np.asarray(payout, dtype=float)
    exp = float(p.sum())
    obs = float(y.sum())
    var = float((p * (1.0 - p)).sum())
    if var <= 0:
        return obs, exp, 1.0
    z = (obs - exp) / math.sqrt(var)
    return obs, exp, 0.5 * math.erfc(z / math.sqrt(2))  # upper-tail normal approx


def predictor_skilled(entry_price, payout, sig: float = 0.05) -> bool:
    obs, exp, pval = beat_market_p(entry_price, payout)
    return pval < sig and obs > exp


def classify_by_entry(entry_price, hi_share: float = 0.7) -> str:
    """Strategy type from the entry-price profile of an account's positions."""
    p = np.asarray(entry_price, dtype=float)
    if p.size == 0:
        return "unknown"
    med = float(np.median(p))
    hi = float((p >= 0.85).mean())
    if hi >= hi_share or med >= 0.85:
        return "favorite_farmer"
    if med <= 0.65:
        return "predictor"
    return "momentum_rider"


def calibrated_null_counts(accounts, n_sims: int = 50, seed: int = 0, sig: float = 0.05) -> list[int]:
    """Correctly-sized no-skill null. `accounts` is a list of per-account entry-price
    arrays (the eligible predictor accounts). For each sim, draw every position's
    outcome ~ Bernoulli(entry_price) and count accounts that pass the skill test.
    Mean count ≈ sig * len(accounts) when the test is well-sized."""
    rng = np.random.default_rng(seed)
    counts = []
    for _ in range(n_sims):
        c = 0
        for p in accounts:
            p = np.asarray(p, dtype=float)
            y = (rng.random(p.size) < p).astype(float)
            if predictor_skilled(p, y, sig=sig):
                c += 1
        counts.append(c)
    return counts


def permuted_null_counts(accounts, n_sims: int = 50, seed: int = 0, sig: float = 0.05) -> list[int]:
    """The WRONG null (kept for the regression test): permute realized labels across
    all positions, imposing the pool's marginal win rate. Inflates when realized >
    implied. Present so a test can prove why the calibrated null is the correct one."""
    rng = np.random.default_rng(seed)
    sizes = [np.asarray(p).size for p in accounts]
    pool = np.concatenate([np.asarray(a[1], dtype=float) for a in _as_pairs(accounts)])
    entry = [np.asarray(a[0], dtype=float) for a in _as_pairs(accounts)]
    counts = []
    for _ in range(n_sims):
        shuffled = rng.permutation(pool)
        c = 0
        off = 0
        for p, n in zip(entry, sizes):
            y = shuffled[off:off + n]
            off += n
            if predictor_skilled(p, y, sig=sig):
                c += 1
        counts.append(c)
    return counts


def _as_pairs(accounts):
    """Accept either [entry_array,...] or [(entry_array, payout_array),...]."""
    for a in accounts:
        if isinstance(a, tuple):
            yield a
        else:
            yield (a, np.zeros(np.asarray(a).size))

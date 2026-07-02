"""Regression tests for the external-fact skill test + null calibration.

This is the load-bearing, once-broken component: a mis-specified null made a broken
"beat the market" test look like "no edge". These fixtures pin the full contract on
synthetic accounts where we KNOW the ground truth — correct size, real power, correct
rejection — plus a demonstration that the WRONG (label-permutation) null inflates on a
pool with selection bias, which is why the calibrated Bernoulli(entry) null is correct.
"""

import numpy as np
from bellwether_analytics.skill import (
    beat_market_p,
    calibrated_null_counts,
    classify_by_entry,
    permuted_null_counts,
    predictor_skilled,
)

SIG = 0.05


def test_null_is_correctly_sized():
    """No-skill accounts (outcome ~ Bernoulli(entry_price)) -> false-positive rate ~ SIG."""
    rng = np.random.default_rng(0)
    accounts = [np.clip(rng.uniform(0.3, 0.7, 30), 0.02, 0.98) for _ in range(300)]
    counts = calibrated_null_counts(accounts, n_sims=60, seed=1, sig=SIG)
    fp_rate = float(np.mean(counts)) / len(accounts)
    # well-sized: near SIG, not wildly inflated or dead
    assert 0.02 <= fp_rate <= 0.09, fp_rate


def test_permutation_null_inflates_on_biased_pool():
    """The WRONG null: on a pool where realized wins (0.5) exceed entry-implied (0.4) —
    a favorite-longshot/selection gap — label permutation imposes the pool's 0.5 marginal
    and flags far more than SIG, while the calibrated null stays ~SIG. Documents why we
    switched nulls."""
    rng = np.random.default_rng(2)
    n_acct, n_mkt = 150, 30
    entry = [np.full(n_mkt, 0.40) for _ in range(n_acct)]
    # realized outcomes carry a +0.10 pool-wide bias, NOT individual skill
    pairs = [(e, (rng.random(n_mkt) < 0.50).astype(float)) for e in entry]

    perm = permuted_null_counts(pairs, n_sims=40, seed=3, sig=SIG)
    calib = calibrated_null_counts(entry, n_sims=40, seed=3, sig=SIG)
    perm_rate = float(np.mean(perm)) / n_acct
    calib_rate = float(np.mean(calib)) / n_acct
    assert perm_rate > 0.15, perm_rate       # inflated by the pool bias
    assert calib_rate <= 0.09, calib_rate    # correctly sized
    assert perm_rate > 3 * calib_rate        # the wrong null is dramatically worse


def test_power_detects_a_truly_skilled_predictor():
    """An account whose outcomes beat its entry prices by a real edge must pass."""
    rng = np.random.default_rng(4)
    p = np.clip(rng.uniform(0.35, 0.65, 100), 0.02, 0.98)
    y = (rng.random(100) < np.clip(p + 0.15, 0, 1)).astype(float)  # +15% forecasting edge
    obs, exp, pval = beat_market_p(p, y)
    assert obs > exp and pval < SIG
    assert predictor_skilled(p, y, sig=SIG)


def test_favorite_farmer_classified_and_rejected():
    """Only bets ~0.90 favorites and wins ~0.90: classified favorite_farmer AND fails the
    skill test (win rate ≈ entry-implied, no excess)."""
    rng = np.random.default_rng(5)
    p = np.full(40, 0.90)
    y = (rng.random(40) < 0.90).astype(float)
    assert classify_by_entry(p) == "favorite_farmer"
    assert not predictor_skilled(p, y, sig=SIG)


def test_classification_boundaries():
    assert classify_by_entry(np.full(20, 0.45)) == "predictor"
    assert classify_by_entry(np.full(20, 0.75)) == "momentum_rider"
    assert classify_by_entry(np.full(20, 0.92)) == "favorite_farmer"

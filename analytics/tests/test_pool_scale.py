"""Scale + trustworthiness: run the guarded cross-account pipeline on a >=500-wallet
pool. Synchronized reaction to shared news (no leader) must be REJECTED; a planted
consistent copy-chain (consistent timestamp lag AND consistent on-chain block gap)
must SURVIVE. Only significance + block-confirmed chains appear, each with a
block-gap profile and a real follower-capture measurement.
"""

import random

import pandas as pd
from bellwether_analytics.experiments import trackability_verdict
from bellwether_analytics.strategy import (
    confirmed_copy_chains,
    detect_followers,
    detect_followers_significant,
)
from bellwether_analytics.strategy.archetypes import StrategyConfig

T0 = pd.Timestamp("2026-01-01T00:00:00Z")


def _row(wallet, market, ts, block, price=0.5):
    return dict(wallet=wallet, market=market, slug=f"m-{market}", category="x", outcome="YES",
                side="BUY", size=100, price=price, notional=100 * price, ts=ts,
                block_number=block, resolution=None, resolved_at=pd.NaT)


def _population(seed=0):
    rng = random.Random(seed)
    rows = []

    # (1) Pool bulk: 490 background wallets, each in its own distinct markets (no overlap).
    for w in range(490):
        for k in range(2):
            mkt = f"bg-{w}-{k}"
            rows.append(_row(f"BG{w}", mkt, T0 + pd.Timedelta(hours=w + k), 5000 + w))

    # (2) Synchronized reactors: 10 wallets all fill in the SAME 25 news markets,
    #     near-simultaneously, in RANDOM order, with RANDOM blocks -> no real leader.
    reactors = [f"RX{i}" for i in range(10)]
    for j in range(25):
        order = reactors[:]
        rng.shuffle(order)
        base_ts = T0 + pd.Timedelta(days=10, minutes=j)
        base_blk = 20000 + j * 10
        # Near-simultaneous reactions land in the SAME block -> any pair's block gap
        # is 0 (no consistent positive gap), so block confirmation rejects them.
        for w in order:
            rows.append(_row(w, f"news-{j}", base_ts + pd.Timedelta(seconds=rng.randint(0, 3)),
                             base_blk))

    # (3) Planted copy-chain: LEADER + FOLLOWER across 15 shared markets, FOLLOWER
    #     consistently ~10s and exactly +2 blocks after LEADER (same side).
    for j in range(15):
        mkt = f"copy-{j}"
        l_ts = T0 + pd.Timedelta(days=20, minutes=j)
        l_blk = 40000 + j * 5
        rows.append(_row("LEADER", mkt, l_ts, l_blk, price=0.50))
        rows.append(_row("FOLLOWER", mkt, l_ts + pd.Timedelta(seconds=10), l_blk + 2, price=0.51))

    return pd.DataFrame(rows)


def test_full_pool_rejects_synchronized_keeps_confirmed_copychain():
    trades = _population()
    assert trades["wallet"].nunique() >= 500  # full pool scale

    cfg = StrategyConfig(leadlag_n_permutations=150, leadlag_significance=0.95,
                         leadlag_min_block_confirmations=3, leadlag_max_block_gap=5)

    # Raw (unguarded) detection finds the planted pair AND synchronized noise.
    raw = detect_followers(trades, max_lag_seconds=60, min_events=3)
    raw_pairs = set(zip(raw["leader"], raw["follower"]))
    assert ("LEADER", "FOLLOWER") in raw_pairs
    reactor_noise = [(a, b) for (a, b) in raw_pairs if a.startswith("RX") and b.startswith("RX")]
    assert len(reactor_noise) > 0  # naive detection hallucinates copying among reactors

    # The null model strongly REDUCES the synchronized noise (it is probabilistic:
    # ~5% slip through at 95% significance) — which is why on-chain block-gap
    # confirmation is the non-negotiable second guard.
    sig = detect_followers_significant(trades, max_lag_seconds=60, min_events=3, config=cfg, seed=1)
    sig_pairs = set(zip(sig["leader"], sig["follower"]))
    sig_noise = [(a, b) for (a, b) in sig_pairs if a.startswith("RX") and b.startswith("RX")]
    assert ("LEADER", "FOLLOWER") in sig_pairs
    assert len(sig_noise) < len(reactor_noise)  # null model cuts the noise down

    # Full guarded pipeline (null model + on-chain block-gap confirmation) is the
    # trustworthy result: ONLY the consistent-block-gap copy-chain survives.
    confirmed = confirmed_copy_chains(trades, max_lag_seconds=60, min_events=3, config=cfg, seed=1)
    assert not confirmed.empty
    assert set(zip(confirmed["leader"], confirmed["follower"])) == {("LEADER", "FOLLOWER")}
    row = confirmed.iloc[0]
    assert bool(row["block_confirmed"]) is True
    assert row["block_gap_median"] == 2.0          # consistent +2 block gap
    assert row["n_block_confirmations"] >= 3

    # Per-leader real-data trackability verdict, with the captured edge + block gap.
    verdict = trackability_verdict(trades, max_lag_seconds=60, min_events=3, config=cfg, seed=1)
    assert list(verdict["leader"]) == ["LEADER"]
    v = verdict.iloc[0]
    assert v["median_block_gap"] == 2.0
    assert abs(v["median_entry_delta"] - 0.01) < 1e-6   # follower paid 0.51 vs 0.50
    assert v["median_time_gap_seconds"] == 10.0

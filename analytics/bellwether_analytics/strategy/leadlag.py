"""Lead-lag copy detection + a permutation null model.

A follow event is a fill whose immediately-preceding different-wallet fill (same
side, within a lag window) is the "leader". Raw counts alone hallucinate copy
chains in liquid markets where many wallets react to the SAME public event at
nearly the same time. The null model guards against this: permute the timestamps
within each market many times to build a null distribution of follow counts; a
(leader, follower) pair survives only if its observed count exceeds the null at a
configurable significance. Synchronized reaction (no consistent leader) collapses
to chance under permutation and is rejected; a consistent copier does not.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from statistics import median
from typing import Optional

import numpy as np
import pandas as pd

from .archetypes import StrategyConfig

_EMPTY = ["leader", "follower", "follow_events", "n_markets", "follow_ratio", "median_gap_seconds"]


def _market_seqs(df: pd.DataFrame) -> dict:
    """market/outcome -> time-sorted list of (wallet, side, ts)."""
    seqs = {}
    for key, g in df.groupby(["market", "outcome"]):
        gs = g.sort_values("ts")
        seqs[key] = list(zip(gs["wallet"], gs["side"].astype(str).str.upper(), gs["ts"]))
    return seqs


def _count(seqs: dict, max_lag: float, same_side: bool):
    """Return (pair->count, pair->[gaps], pair->set(markets))."""
    events: Counter = Counter()
    gaps: dict = defaultdict(list)
    markets: dict = defaultdict(set)
    for (market, _outcome), seq in seqs.items():
        for i in range(1, len(seq)):
            b_w, b_s, b_t = seq[i]
            j = i - 1
            while j >= 0:
                a_w, a_s, a_t = seq[j]
                gap = (b_t - a_t).total_seconds()
                if gap > max_lag:
                    break
                if a_w != b_w and (not same_side or a_s == b_s):
                    events[(a_w, b_w)] += 1
                    gaps[(a_w, b_w)].append(gap)
                    markets[(a_w, b_w)].add(market)
                    break
                j -= 1
    return events, gaps, markets


def detect_followers(
    trades: pd.DataFrame,
    max_lag_seconds: float = 120.0,
    min_events: int = 3,
    same_side: bool = True,
) -> pd.DataFrame:
    """Raw (unguarded) follower pairs. Use detect_followers_significant for the
    null-model-filtered version."""
    if trades.empty:
        return pd.DataFrame(columns=_EMPTY)
    df = trades.copy()
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    follower_total = df.groupby("wallet").size().to_dict()
    events, gaps, markets = _count(_market_seqs(df), max_lag_seconds, same_side)

    rows = []
    for (leader, follower), n in events.items():
        if n < min_events:
            continue
        rows.append({
            "leader": leader, "follower": follower, "follow_events": n,
            "n_markets": len(markets[(leader, follower)]),
            "follow_ratio": n / max(follower_total.get(follower, 1), 1),
            "median_gap_seconds": float(median(gaps[(leader, follower)])),
        })
    if not rows:
        return pd.DataFrame(columns=_EMPTY)
    return pd.DataFrame(rows).sort_values("follow_events", ascending=False).reset_index(drop=True)


def detect_followers_significant(
    trades: pd.DataFrame,
    max_lag_seconds: float = 120.0,
    min_events: int = 3,
    same_side: bool = True,
    config: Optional[StrategyConfig] = None,
    seed: int = 0,
) -> pd.DataFrame:
    """Follower pairs that survive a within-market timestamp-permutation null model.

    Adds null_threshold (the significance-percentile of the permuted follow count)
    and p_value (share of permutations >= observed). Only pairs with observed >
    null_threshold are returned.
    """
    config = config or StrategyConfig()
    cols = _EMPTY + ["null_threshold", "p_value"]
    if trades.empty:
        return pd.DataFrame(columns=cols)

    df = trades.copy()
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    follower_total = df.groupby("wallet").size().to_dict()
    seqs = _market_seqs(df)
    observed, gaps, markets = _count(seqs, max_lag_seconds, same_side)
    candidates = [p for p, n in observed.items() if n >= min_events]
    if not candidates:
        return pd.DataFrame(columns=cols)

    # Per-market (wallet, side) rows + the timestamp pool to permute.
    rows_by_market = {k: [(w, s) for (w, s, _t) in seq] for k, seq in seqs.items()}
    ts_by_market = {k: [t for (_w, _s, t) in seq] for k, seq in seqs.items()}

    rng = np.random.default_rng(seed)
    null_counts: dict = {p: [] for p in candidates}
    for _ in range(config.leadlag_n_permutations):
        perm = {}
        for k in seqs:
            ts = list(ts_by_market[k])
            rng.shuffle(ts)
            perm[k] = sorted(
                ((w, s, t) for (w, s), t in zip(rows_by_market[k], ts)), key=lambda x: x[2]
            )
        nc, _g, _m = _count(perm, max_lag_seconds, same_side)
        for p in candidates:
            null_counts[p].append(nc.get(p, 0))

    rows = []
    for p in candidates:
        obs = observed[p]
        nd = np.asarray(null_counts[p], dtype=float)
        threshold = float(np.percentile(nd, config.leadlag_significance * 100))
        p_value = float((nd >= obs).mean())
        if obs <= threshold:
            continue
        leader, follower = p
        rows.append({
            "leader": leader, "follower": follower, "follow_events": obs,
            "n_markets": len(markets[p]),
            "follow_ratio": obs / max(follower_total.get(follower, 1), 1),
            "median_gap_seconds": float(median(gaps[p])),
            "null_threshold": threshold, "p_value": p_value,
        })
    if not rows:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(rows).sort_values("follow_events", ascending=False).reset_index(drop=True)


def confirm_block_gaps(
    trades: pd.DataFrame, pairs: pd.DataFrame, config: Optional[StrategyConfig] = None
) -> pd.DataFrame:
    """On-chain confirmation: for each (leader, follower) pair, measure the block
    gap (follower's fill block - leader's fill block) per shared market with on-chain
    block data. A pair is block_confirmed only when the gap is positive, small
    (<= max_block_gap), CONSISTENT (std <= max_block_gap_std), and observed across
    >= min_block_confirmations markets. Adds block_gap_median/std, n_block_confirmations,
    block_confirmed. block_confirmed is NA when no on-chain block data exists."""
    config = config or StrategyConfig()
    out = pairs.copy()
    out["block_gap_median"] = np.nan
    out["block_gap_std"] = np.nan
    out["n_block_confirmations"] = 0
    out["block_confirmed"] = pd.NA
    if out.empty or "block_number" not in trades.columns:
        return out

    df = trades[trades["block_number"].notna()].copy()
    if df.empty:
        return out  # no on-chain data -> block_confirmed stays NA
    df["block_number"] = df["block_number"].astype("int64")

    for i, row in out.iterrows():
        leader, follower = row["leader"], row["follower"]
        L = df[df["wallet"] == leader]
        F = df[df["wallet"] == follower]
        gaps = []
        for market, lg in L.groupby("market"):
            l_block = int(lg["block_number"].min())
            fg = F[(F["market"] == market) & (F["block_number"] >= l_block)]
            if fg.empty:
                continue
            gaps.append(int(fg["block_number"].min()) - l_block)
        if not gaps:
            continue
        g = np.asarray(gaps, dtype=float)
        med, std = float(np.median(g)), float(g.std())
        out.at[i, "block_gap_median"] = med
        out.at[i, "block_gap_std"] = std
        out.at[i, "n_block_confirmations"] = len(gaps)
        out.at[i, "block_confirmed"] = bool(
            len(gaps) >= config.leadlag_min_block_confirmations
            and 0 < med <= config.leadlag_max_block_gap
            and std <= config.leadlag_max_block_gap_std
        )
    return out


def confirmed_copy_chains(
    trades: pd.DataFrame,
    max_lag_seconds: float = 120.0,
    min_events: int = 3,
    same_side: bool = True,
    config: Optional[StrategyConfig] = None,
    seed: int = 0,
) -> pd.DataFrame:
    """Full guarded pipeline: significance null model -> on-chain block-gap
    confirmation. When on-chain block data is present, only block_confirmed pairs
    are returned; otherwise the significance-filtered pairs pass through (block
    confirmation pending an on-chain backfill)."""
    sig = detect_followers_significant(
        trades, max_lag_seconds=max_lag_seconds, min_events=min_events,
        same_side=same_side, config=config, seed=seed,
    )
    if sig.empty:
        return sig
    confirmed = confirm_block_gaps(trades, sig, config=config)
    has_block_data = "block_number" in trades.columns and trades["block_number"].notna().any()
    if has_block_data:
        return confirmed[confirmed["block_confirmed"] == True].reset_index(drop=True)  # noqa: E712
    return confirmed

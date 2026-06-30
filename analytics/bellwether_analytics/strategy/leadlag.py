"""Lead-lag copy detection: wallets that systematically trade just after another.

For each market+outcome, fills are ordered by time; a follow event is a fill whose
immediately-preceding different-wallet fill (same side, within a lag window) is the
"leader". Pairs with many follow events across markets are candidate copy chains —
the same follow-the-leader strategy run over and over.
"""

from __future__ import annotations

from collections import Counter, defaultdict

import pandas as pd


def detect_followers(
    trades: pd.DataFrame,
    max_lag_seconds: float = 120.0,
    min_events: int = 3,
    same_side: bool = True,
) -> pd.DataFrame:
    """Return candidate (leader, follower) pairs with follow_events, n_markets, and
    follow_ratio (follow_events / follower's total trades). Sorted by follow_events."""
    empty = pd.DataFrame(columns=["leader", "follower", "follow_events", "n_markets", "follow_ratio"])
    if trades.empty:
        return empty

    df = trades.copy()
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    follower_total = df.groupby("wallet").size().to_dict()

    pair_events: Counter = Counter()
    pair_markets: dict[tuple[str, str], set] = defaultdict(set)

    for (market, _outcome), g in df.groupby(["market", "outcome"]):
        gs = g.sort_values("ts")
        seq = list(zip(gs["wallet"], gs["side"].astype(str).str.upper(), gs["ts"]))
        for i in range(1, len(seq)):
            b_w, b_s, b_t = seq[i]
            j = i - 1
            while j >= 0:
                a_w, a_s, a_t = seq[j]
                if (b_t - a_t).total_seconds() > max_lag_seconds:
                    break
                if a_w != b_w and (not same_side or a_s == b_s):
                    pair_events[(a_w, b_w)] += 1
                    pair_markets[(a_w, b_w)].add(market)
                    break
                j -= 1

    rows = []
    for (leader, follower), n in pair_events.items():
        if n < min_events:
            continue
        rows.append(
            {
                "leader": leader,
                "follower": follower,
                "follow_events": n,
                "n_markets": len(pair_markets[(leader, follower)]),
                "follow_ratio": n / max(follower_total.get(follower, 1), 1),
            }
        )
    if not rows:
        return empty
    return pd.DataFrame(rows).sort_values("follow_events", ascending=False).reset_index(drop=True)

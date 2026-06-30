"""Unsupervised cross-check of the rule-based archetypes (diagnostic only).

Clusters the behavioral feature vectors and compares the clusters to the rule
labels. Disagreements flag where StrategyConfig thresholds may be brittle. The
explainable rule-based classifier remains the system of record — this only
recommends, never auto-applies.

k-means (numpy, no sklearn dependency) is the always-available baseline; HDBSCAN
is used instead when it is importable.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

_FEATURES = [
    "trades_per_day", "median_gap_seconds", "avg_notional", "net_direction",
    "roundtrip_ratio", "top_family_share", "split_merge_ratio", "taker_ratio",
]


def feature_matrix(features: pd.DataFrame) -> tuple[np.ndarray, pd.Index, list[str]]:
    cols = [c for c in _FEATURES if c in features.columns]
    X = features[cols].apply(pd.to_numeric, errors="coerce").fillna(0.0).to_numpy(dtype=float)
    mean = X.mean(axis=0)
    std = X.std(axis=0)
    std[std == 0] = 1.0
    return (X - mean) / std, features.index, cols


def _kmeans(X: np.ndarray, k: int, seed: int = 0, iters: int = 100) -> np.ndarray:
    rng = np.random.default_rng(seed)
    k = max(1, min(k, len(X)))
    centroids = X[rng.choice(len(X), size=k, replace=False)].copy()
    labels = np.zeros(len(X), dtype=int)
    for _ in range(iters):
        d = ((X[:, None, :] - centroids[None, :, :]) ** 2).sum(axis=2)
        new_labels = d.argmin(axis=1)
        new_centroids = np.array([
            X[new_labels == j].mean(axis=0) if (new_labels == j).any() else centroids[j]
            for j in range(k)
        ])
        if np.array_equal(new_labels, labels) and np.allclose(new_centroids, centroids):
            labels = new_labels
            break
        labels, centroids = new_labels, new_centroids
    return labels


def cluster_wallets(
    features: pd.DataFrame, k: Optional[int] = None, seed: int = 0
) -> pd.Series:
    """Cluster label per wallet. Uses HDBSCAN if available, else k-means."""
    if features.empty:
        return pd.Series(dtype=int, name="cluster")
    X, index, _cols = feature_matrix(features)

    try:  # optional, no hard dependency
        import hdbscan  # type: ignore

        labels = hdbscan.HDBSCAN(min_cluster_size=max(2, len(X) // 10)).fit_predict(X)
    except Exception:
        labels = _kmeans(X, k or min(len(features), len(_FEATURES)) or 2, seed)
    return pd.Series(labels, index=index, name="cluster")


def compare_to_rules(clusters: pd.Series, archetypes: pd.Series) -> dict:
    """Contingency table (cluster x rule archetype), agreement score, and the list
    of wallets where the cluster's dominant archetype disagrees with the rule."""
    df = pd.DataFrame({"cluster": clusters, "archetype": archetypes}).dropna()
    if df.empty:
        return {"contingency": pd.DataFrame(), "agreement": float("nan"), "disagreements": []}
    contingency = pd.crosstab(df["cluster"], df["archetype"])

    dominant = contingency.idxmax(axis=1).to_dict()  # cluster -> majority archetype
    agree = sum(
        1 for _, r in df.iterrows() if r["archetype"] == dominant.get(r["cluster"])
    )
    agreement = agree / len(df)

    disagreements = [
        {"wallet": w, "cluster": int(r["cluster"]), "rule_archetype": r["archetype"],
         "cluster_majority": dominant.get(r["cluster"])}
        for w, r in df.iterrows()
        if r["archetype"] != dominant.get(r["cluster"])
    ]
    return {"contingency": contingency, "agreement": agreement, "disagreements": disagreements}


def recommend_thresholds(features: pd.DataFrame, comparison: dict) -> list[str]:
    """Cheap, explainable hints: for the archetypes involved in disagreements, the
    features whose values are most spread (candidate threshold boundaries)."""
    recs: list[str] = []
    dis = comparison.get("disagreements", [])
    if not dis:
        return ["clusters agree with rules; no threshold changes suggested"]
    involved = {d["rule_archetype"] for d in dis} | {d["cluster_majority"] for d in dis}
    _X, _idx, cols = feature_matrix(features)
    sub = features.loc[[d["wallet"] for d in dis], cols].apply(pd.to_numeric, errors="coerce")
    spread = sub.std().sort_values(ascending=False)
    top = [c for c in spread.index[:3]]
    recs.append(
        f"{len(dis)} wallet(s) disagree across {sorted(involved)}; "
        f"review thresholds on: {', '.join(top)}"
    )
    return recs

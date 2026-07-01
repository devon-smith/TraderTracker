"""Rank demonstrably-skilled (not lucky) strategists on EXTERNAL-FACT markets.

This is *analysis on a new pool*, not new detection machinery: it reuses the
existing resolution/P&L engine (`core.position_settlements`), market-family
normalization (`strategy.recurrence.market_family`), and the significance /
shuffled-control philosophy from `candidates.validation`.

Target markets resolve against a KNOWABLE EXTERNAL FACT — elections, policy,
sports series, crypto-event resolution, geopolitics, pop-culture-with-depth.
Edge here is information / modeling / discipline, NOT latency, so all
updown/intraday market families are excluded up front.

The funnel, applied per (account, category):

  0. EXCLUDE updown/latency families entirely.
  1. ELIGIBILITY   — account traded >= `min_markets` DISTINCT resolved markets
                     (independent events, not one market repeatedly).
  2. PERSISTENCE   — split resolved history into sub-periods; require net-positive
                     edge in MOST of them (the primary not-luck test).
  3. CLASSIFY      — by entry price vs the market's eventual convergence:
                       predictor       entered while uncertain (median entry < 0.65)
                       momentum_rider  entered after the move (0.65..0.85)
                       favorite_farmer only ever high-prob (>= 0.85) — no edge
  4. SKILL TEST    — type-appropriate:
                       predictor       must BEAT the entry-price-implied win rate
                                       at significance (Poisson-binomial z, p<0.05)
                       momentum_rider  persistence + positive ROI (can't beat the
                                       market by construction, so not required)
                       favorite_farmer FLAGGED no-edge and DROPPED
  5. RANK survivors WITHIN type by P&L (opportunity size) and % return (edge
     quality). Both reported.

Controls: `null_control` redraws each position's outcome from Bernoulli(entry
price) — the market-is-calibrated, no-skill null — and shows the survivor set
collapses to chance. `edge_source_hint` flags INFORMATION (entered before the
public signal / against the market) vs MODELING (entered after) as a hook for
later reverse-engineering; it is a FLAG ONLY, not an analysis.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from ..core import position_settlements
from ..strategy.recurrence import market_family

# Families whose edge is latency, not information — excluded from this study.
LATENCY_MARKERS = (
    "updown", "up-or-down", "up-or-dn", "-5m", "5m-", "-15m", "15m-",
    "-30m", "30m-", "-1h", "1h-", "-4h", "4h-", "hourly", "intraday",
)

# Categories whose resolution is a knowable external fact (from `categorize.py`).
EXTERNAL_FACT_CATEGORIES = ("politics", "economics", "sports", "crypto", "entertainment", "geopolitics")

PREDICTOR = "predictor"
MOMENTUM_RIDER = "momentum_rider"
FAVORITE_FARMER = "favorite_farmer"
LONGSHOT = "longshot"


@dataclass
class SkillConfig:
    min_markets: int = 10          # eligibility: distinct resolved markets in category
    n_periods: int = 3             # persistence sub-periods
    persistence_min: float = 0.5   # "most" sub-periods net-positive (strictly greater)
    predictor_min_entry: float = 0.15   # below this => longshot/dust (no forecasting edge)
    predictor_max_entry: float = 0.65   # median entry in [min,max) => predictor
    farmer_min_entry: float = 0.85      # median entry at/above this => favorite-farmer
    skill_alpha: float = 0.05      # FDR q for the significance gate (Benjamini-Hochberg)
    info_max_entry: float = 0.5    # predictor entering below this leans INFORMATION
    null_draws: int = 40           # market-calibrated null resamples


def _phi(z: float) -> float:
    """Standard-normal CDF (stdlib only — no scipy dependency)."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def is_latency_family(family: str | None) -> bool:
    """True for updown/intraday families whose edge is speed, not information."""
    if not isinstance(family, str) or not family:
        return False
    fam = family.lower()
    return any(m in fam for m in LATENCY_MARKERS)


def exclude_latency(trades: pd.DataFrame) -> pd.DataFrame:
    """Drop every trade whose market-family is an updown/intraday latency family."""
    if trades.empty or "slug" not in trades.columns:
        return trades
    fam = trades["slug"].map(market_family)
    return trades[~fam.map(is_latency_family)]


def _position_frame(trades: pd.DataFrame, config: SkillConfig) -> pd.DataFrame:
    """One row per resolved (account, market) — the account's DOMINANT position (the
    outcome it committed the most capital to) — carrying entry price (= the market's
    implied probability at entry), the settled outcome, realized P&L, capital,
    category, family, and timing. Collapsing to the dominant bet drops dust/hedge
    positions that would otherwise pull the median entry toward 0. Latency removed."""
    t = exclude_latency(trades)
    settle = position_settlements(t)
    if settle.empty:
        return pd.DataFrame()
    settle = settle[settle["net_shares"] > 0].copy()
    if settle.empty:
        return pd.DataFrame()
    # one row per (wallet, market): the outcome with the most capital committed
    settle = settle.sort_values("buy_cost").groupby(["wallet", "market"], as_index=False).tail(1)
    settle["entry_price"] = (settle["net_cost"] / settle["net_shares"]).clip(1e-6, 1 - 1e-6)
    settle["won"] = settle["payout"].astype(float)

    meta_cols = [c for c in ("market", "category", "slug") if c in t.columns]
    meta = t[meta_cols].drop_duplicates("market")
    settle = settle.merge(meta, on="market", how="left")
    if "category" not in settle.columns:
        settle["category"] = "unknown"
    settle["category"] = settle["category"].fillna("unknown")
    settle["family"] = settle["slug"].map(market_family) if "slug" in settle.columns else "unknown"

    # Entry timing within the market's observed life (proxy for before/after signal).
    settle["resolved_at"] = pd.to_datetime(settle["resolved_at"], utc=True)
    settle["first_ts"] = pd.to_datetime(settle["first_ts"], utc=True)
    opens = settle.groupby("market")["first_ts"].transform("min")
    span = (settle["resolved_at"] - opens).dt.total_seconds()
    settle["entry_fraction"] = np.where(
        span > 0, (settle["first_ts"] - opens).dt.total_seconds() / span, np.nan
    )
    return settle


def _classify_type(median_entry: float, config: SkillConfig) -> str:
    if median_entry >= config.farmer_min_entry:
        return FAVORITE_FARMER
    if median_entry >= config.predictor_max_entry:
        return MOMENTUM_RIDER
    if median_entry >= config.predictor_min_entry:
        return PREDICTOR
    return LONGSHOT  # sub-0.15 median: longshot/dust farming, not a forecasting edge


def _pnl_z(sub: pd.DataFrame) -> tuple[float, float]:
    """One-sided test that realized P&L beats the market-calibrated null (outcomes ~
    Bernoulli(entry_price), i.e. random entry at the same prices). Under that null a
    position's P&L has mean 0 and variance net_shares^2 * p(1-p). Returns (z, p).
    This is the 'better than random entry into moving markets' test for momentum."""
    p = sub["entry_price"].to_numpy(dtype=float)
    ns = sub["net_shares"].to_numpy(dtype=float)
    var = float(np.sum(ns * ns * p * (1.0 - p)))
    if var <= 0:
        return 0.0, 1.0
    z = float(sub["realized_pnl"].sum()) / math.sqrt(var)
    return z, 1.0 - _phi(z)


def _bh_reject(pvals: list[float], q: float) -> list[bool]:
    """Benjamini-Hochberg FDR: reject the largest set with p_(k) <= (k/m) q. Controls
    false discoveries across the many per-account tests, so a no-skill null yields ~0
    survivors instead of the ~q*m false positives a raw per-account threshold gives."""
    m = len(pvals)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: pvals[i])
    cut = -1.0
    for rank, i in enumerate(order, start=1):
        if pvals[i] <= (rank / m) * q:
            cut = pvals[i]
    return [p <= cut for p in pvals]


def _persistence(sub: pd.DataFrame, config: SkillConfig) -> float:
    """Fraction of equal-count time sub-periods with net-positive realized P&L."""
    g = sub.sort_values("resolved_at")
    n = min(config.n_periods, len(g))
    if n <= 0:
        return 0.0
    chunks = np.array_split(np.arange(len(g)), n)
    positive = 0
    used = 0
    for idx in chunks:
        if len(idx) == 0:
            continue
        used += 1
        if float(g.iloc[idx]["realized_pnl"].sum()) > 0:
            positive += 1
    return positive / used if used else 0.0


def _predictor_skill(sub: pd.DataFrame) -> tuple[float, float]:
    """Poisson-binomial one-sided test: does the account win MORE than its entry
    prices imply? Returns (z, p). Entry price = the market's own probability, so
    beating it is a genuine forecasting edge (not merely win_rate > 55%)."""
    p = sub["entry_price"].to_numpy(dtype=float)
    wins = float(sub["won"].sum())
    expected = float(p.sum())
    var = float(np.sum(p * (1.0 - p)))
    if var <= 0:
        return 0.0, 1.0
    z = (wins - expected) / math.sqrt(var)
    return z, 1.0 - _phi(z)


def _funnel_rows(pos: pd.DataFrame, config: SkillConfig, rng: Optional[np.random.Generator] = None):
    """Run the eligibility -> persistence -> type -> skill funnel over every
    (wallet, category) group, then apply a Benjamini-Hochberg FDR gate across the
    tested accounts so a no-skill null does not manufacture survivors. If `rng` is
    given, outcomes are redrawn from Bernoulli(entry_price) first — the
    market-calibrated no-skill null."""
    if pos.empty:
        return []
    work = pos
    if rng is not None:
        work = pos.copy()
        work["won"] = rng.binomial(1, work["entry_price"].to_numpy(dtype=float)).astype(float)
        work["realized_pnl"] = work["net_shares"] * work["won"] - work["net_cost"]

    rows = []
    for (wallet, category), sub in work.groupby(["wallet", "category"]):
        n_markets = int(sub["market"].nunique())
        if n_markets < config.min_markets:  # eligibility (independent events)
            continue
        realized_pnl = float(sub["realized_pnl"].sum())
        buy_cost = float(sub["buy_cost"].sum())
        roi = realized_pnl / buy_cost if buy_cost > 0 else float("nan")
        median_entry = float(sub["entry_price"].median())
        persistence = _persistence(sub, config)
        persistence_pass = persistence > config.persistence_min
        stype = _classify_type(median_entry, config)

        # type-appropriate skill statistic
        if stype == PREDICTOR:
            skill_test = "binomial_vs_entry"          # beat the entry-price-implied win rate
            z, pval = _predictor_skill(sub)
        elif stype == MOMENTUM_RIDER:
            skill_test = "pnl_vs_random_entry"         # beat random entry into moving markets
            z, pval = _pnl_z(sub)
        else:  # favorite_farmer / longshot — no edge by construction
            skill_test, z, pval = "none", float("nan"), 1.0

        # a survivor candidate: a testable type, persistent, and net-positive.
        candidate = bool(stype in (PREDICTOR, MOMENTUM_RIDER) and persistence_pass and realized_pnl > 0)

        mean_frac = float(sub["entry_fraction"].mean(skipna=True)) if "entry_fraction" in sub else float("nan")
        information = stype == PREDICTOR and (
            median_entry < config.info_max_entry or (mean_frac == mean_frac and mean_frac < 0.34)
        )
        rows.append({
            "wallet": wallet, "category": category, "n_markets": n_markets, "type": stype,
            "median_entry": median_entry, "persistence": persistence,
            "persistence_pass": persistence_pass, "skill_test": skill_test, "skill_z": z,
            "skill_p": pval, "_candidate": candidate, "realized_pnl": realized_pnl, "roi": roi,
            "edge_source_hint": "information" if information else "modeling",
        })

    # FDR across the candidate accounts' type-appropriate p-values.
    cand_idx = [i for i, r in enumerate(rows) if r["_candidate"]]
    reject = _bh_reject([rows[i]["skill_p"] for i in cand_idx], config.skill_alpha)
    passed = {cand_idx[j] for j, ok in enumerate(reject) if ok}
    for i, r in enumerate(rows):
        r["skill_pass"] = i in passed
        r["survived"] = i in passed
        if r["survived"]:
            r["drop_reason"] = ""
        elif r["type"] in (FAVORITE_FARMER, LONGSHOT):
            r["drop_reason"] = f"{r['type']} (win rate ~ entry-implied; no excess edge)"
        elif not r["persistence_pass"]:
            r["drop_reason"] = f"failed persistence ({r['persistence']:.2f} of sub-periods positive)"
        elif r["realized_pnl"] <= 0:
            r["drop_reason"] = "net-negative on resolved history"
        else:
            r["drop_reason"] = f"did not clear FDR skill gate ({r['skill_test']} p={r['skill_p']:.3f})"
        del r["_candidate"]
    return rows


def rank_strategists(trades: pd.DataFrame, config: Optional[SkillConfig] = None) -> pd.DataFrame:
    """Full funnel over every eligible (wallet, category). Returns one row per
    eligible account with its distinct-resolved-market count, sub-period
    persistence, entry-timing type, type-appropriate skill result, realized P&L,
    % return, survival verdict + drop reason, and the information/modeling hint.
    Sorted survivors-first, then by P&L."""
    config = config or SkillConfig()
    pos = _position_frame(trades, config)
    rows = _funnel_rows(pos, config)
    cols = ["wallet", "category", "n_markets", "type", "median_entry", "persistence",
            "persistence_pass", "skill_test", "skill_z", "skill_p", "skill_pass", "realized_pnl",
            "roi", "survived", "drop_reason", "edge_source_hint"]
    if not rows:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(rows)[cols]
    return df.sort_values(["survived", "realized_pnl"], ascending=[False, False]).reset_index(drop=True)


def rank_within_type(funnel: pd.DataFrame) -> pd.DataFrame:
    """Survivors only, ranked WITHIN each type by P&L (opportunity magnitude) and
    % return (edge quality) — both reported, per the deliverable."""
    if funnel.empty:
        return funnel
    surv = funnel[funnel["survived"]].copy()
    if surv.empty:
        return surv
    surv["pnl_rank"] = surv.groupby("type")["realized_pnl"].rank(ascending=False, method="min")
    surv["return_rank"] = surv.groupby("type")["roi"].rank(ascending=False, method="min")
    return surv.sort_values(["type", "realized_pnl"], ascending=[True, False]).reset_index(drop=True)


def null_control(trades: pd.DataFrame, config: Optional[SkillConfig] = None, seed: int = 0) -> dict:
    """Market-calibrated no-skill null: redraw every position's outcome from
    Bernoulli(entry_price) and re-run the funnel `null_draws` times. A no-skill
    null must NOT reproduce the real survivor set. Returns real vs mean-null
    survivor / predictor-beat counts."""
    config = config or SkillConfig()
    pos = _position_frame(trades, config)
    real = _funnel_rows(pos, config)
    real_df = pd.DataFrame(real)
    real_survivors = int(real_df["survived"].sum()) if not real_df.empty else 0
    real_predictors = (
        int(((real_df["type"] == PREDICTOR) & real_df["skill_pass"]).sum()) if not real_df.empty else 0
    )

    rng = np.random.default_rng(seed)
    n_surv, n_pred = [], []
    for _ in range(config.null_draws):
        nd = pd.DataFrame(_funnel_rows(pos, config, rng=rng))
        n_surv.append(int(nd["survived"].sum()) if not nd.empty else 0)
        n_pred.append(int(((nd["type"] == PREDICTOR) & nd["skill_pass"]).sum()) if not nd.empty else 0)
    return {
        "real_survivors": real_survivors,
        "null_survivors_mean": float(np.mean(n_surv)) if n_surv else 0.0,
        "null_survivors_max": int(np.max(n_surv)) if n_surv else 0,
        "real_predictors_beat_market": real_predictors,
        "null_predictors_beat_market_mean": float(np.mean(n_pred)) if n_pred else 0.0,
        "n_eligible": int(len(real_df)),
        "null_draws": config.null_draws,
    }


def category_recon(trades: pd.DataFrame, config: Optional[SkillConfig] = None) -> pd.DataFrame:
    """Step-0 recon per external-fact category (latency families excluded): number
    of resolved markets, the resolved-market time span, the distribution of
    'how many distinct resolved markets each account traded', how many accounts
    clear eligibility, and a studyable/thin flag. Thin categories (e.g. Spotify/TV)
    are flagged 'no studyable population' rather than forced.

    Computed directly from resolved trades (no P&L settlement) so it stays cheap on
    a large real pool — recon is about counts and spans, not P&L."""
    config = config or SkillConfig()
    cols = ["category", "n_resolved_markets", "span_start", "span_end", "n_accounts",
            "max_markets_per_account", "median_markets_per_account", "n_eligible_accounts",
            "studyable", "note"]
    if trades.empty:
        return pd.DataFrame(columns=cols)
    t = exclude_latency(trades).copy()
    t["resolved_at"] = pd.to_datetime(t["resolved_at"], utc=True, errors="coerce")
    res = t[t["resolution"].notna() & t["resolved_at"].notna()]
    if res.empty:
        return pd.DataFrame(columns=cols)
    res = res.assign(category=res["category"].fillna("unknown") if "category" in res else "unknown")

    rows = []
    for category, sub in res.groupby("category"):
        per_acct = sub.groupby("wallet")["market"].nunique()
        n_markets = int(sub["market"].nunique())
        n_eligible = int((per_acct >= config.min_markets).sum())
        studyable = bool(n_eligible >= 1 and n_markets >= config.min_markets)
        note = "" if studyable else "no studyable population (too thin for a specialist cohort)"
        rows.append({
            "category": category,
            "n_resolved_markets": n_markets,
            "span_start": sub["resolved_at"].min(),
            "span_end": sub["resolved_at"].max(),
            "n_accounts": int(sub["wallet"].nunique()),
            "max_markets_per_account": int(per_acct.max()),
            "median_markets_per_account": float(per_acct.median()),
            "n_eligible_accounts": n_eligible,
            "studyable": studyable,
            "note": note,
        })
    return pd.DataFrame(rows)[cols].sort_values("n_resolved_markets", ascending=False).reset_index(drop=True)

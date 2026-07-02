"""External-fact skill funnel: eligibility -> persistence -> type -> skill -> rank.

Reuses the resolution/P&L engine (core.performance.position_settlements). No new
detection logic — this is analysis over resolved-market history.

Per (account, category):
  1. ELIGIBILITY : >= MIN_MARKETS distinct resolved markets (reported per account).
  2. PERSISTENCE : net-positive P&L in most time sub-periods (primary not-luck test).
  3. CLASSIFY    : by typical entry price -> predictor / momentum-rider / favorite-farmer.
  4. SKILL       : predictor beats entry-implied win rate (Poisson-binomial z, p<0.05);
                   momentum needs persistence + positive ROI; favorite-farmer dropped.
  5. RANK        : survivors within type by P&L and % return.
Plus a shuffled-label null control and an INFORMATION-vs-MODELING flag.

Usage: python scripts/factfunnel.py
"""

from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd
from bellwether_analytics.core.performance import position_settlements
from bellwether_analytics.core.queries import sync_dsn
from bellwether_analytics.skill import beat_market_p, calibrated_null_counts, classify_by_entry
from sqlalchemy import create_engine, text

POOL = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".cache", "factpool.json"))
MIN_MARKETS = 10
N_SUBPERIODS = 3
SIG = 0.05

CATS = {
    "geopolitics": ["war", "ceasefire", "strike-iran", "invasion", "nato", "nuclear", "hostage",
                    "forces-enter", "regime", "supreme-leader", "khamenei", "netanyahu", "zelenskyy",
                    "iran", "israel", "ukraine", "russia", "gaza", "taiwan", "hamas", "houthi"],
    "politics": ["election", "president", "senate", "congress", "house-race", "governor", "primary",
                 "nominee", "nomination", "mayor", "parliament", "referendum", "policy", "fed-",
                 "rate-cut", "rate-hike", "shutdown", "sanction", "tariff", "supreme-court",
                 "cabinet", "approval", "inaugurat", "-out-by", "out-as", "-out-in", "resign",
                 "impeach", "prime-minister", "poilievre", "epstein", "tiktok", "banned", "pardon"],
    "sports": ["nba", "nfl", "mlb", "nhl", "premier-league", "epl", "ucl", "champions-league",
               "world-cup", "super-bowl", "finals", "playoff", "world-series", "-cup-", "-series-",
               "grand-prix", "masters", "la-liga", "conference", "-win-the", "fifwc", "betis",
               "hornets", "-vs-", "wins-the", "relegat", "bundesliga", "serie-a"],
    "crypto_event": ["bitcoin", "ethereum", "solana", "-eth-", "-btc-", "token", "airdrop",
                     "listing", "etf", "mainnet", "-launch", "fdv", "all-time-high", "coinbase"],
    "pop_culture": ["spotify", "streams", "box-office", "grammy", "oscar", "emmy", "billboard",
                    "netflix", "movie", "album", "award", "stranger-things", "-season-", "gta"],
}


def classify_market(slug: str) -> str:
    s = (slug or "").lower()
    for cat, kws in CATS.items():
        if any(k in s for k in kws):
            return cat
    return "other"


def _coverage(eng, cands) -> dict[str, float]:
    """Per account: resolved / total distinct non-updown markets traded. Low coverage
    means eligibility/skill is being judged on a truncated (under-enriched) history —
    lets the authoritative run distinguish real signal from a resolution-coverage artifact."""
    sql = text(
        "SELECT w.external_id, "
        "count(DISTINCT m.id) FILTER (WHERE m.resolution IS NOT NULL) AS resolved, "
        "count(DISTINCT m.id) AS total "
        "FROM trade t JOIN market m ON m.id=t.market_id JOIN wallet w ON w.id=t.wallet_id "
        "WHERE w.external_id = ANY(:cands) "
        "AND m.slug NOT LIKE '%updown%' AND m.slug NOT LIKE '%up-or-down%' "
        "GROUP BY w.external_id"
    )
    with eng.connect() as c:
        return {r[0]: (r[1] / r[2] if r[2] else 0.0) for r in c.execute(sql, {"cands": cands})}


def _load(eng) -> pd.DataFrame:
    cands = list(json.load(open(POOL))["candidates"])
    sql = text(
        "SELECT w.external_id AS wallet, m.external_id AS market, m.slug AS slug, "
        "t.outcome AS outcome, t.side::text AS side, t.size AS size, t.price AS price, "
        "t.notional AS notional, t.ts AS ts, m.category AS category, "
        "m.resolution AS resolution, m.resolved_at AS resolved_at "
        "FROM trade t JOIN market m ON m.id=t.market_id JOIN wallet w ON w.id=t.wallet_id "
        "WHERE w.external_id = ANY(:cands) AND m.resolution IS NOT NULL "
        "AND m.slug NOT LIKE '%updown%' AND m.slug NOT LIKE '%up-or-down%' "
        "AND t.price > 0 AND t.price < 1"
    )
    with eng.connect() as c:
        df = pd.read_sql(sql, c, params={"cands": cands}, parse_dates=["ts", "resolved_at"])
    return df


def _positions(df: pd.DataFrame) -> pd.DataFrame:
    """One row per resolved (wallet, market, outcome): entry_price, payout, pnl, buy_cost."""
    settle = position_settlements(df)
    if settle.empty:
        return settle
    buys = df[df["side"].astype(str).str.upper() == "BUY"].copy()
    buys["pv"] = buys["price"] * buys["size"]
    ep = (buys.groupby(["wallet", "market", "outcome"])
          .apply(lambda g: g["pv"].sum() / g["size"].sum() if g["size"].sum() else np.nan,
                 include_groups=False)
          .rename("entry_price").reset_index())
    out = settle.merge(ep, on=["wallet", "market", "outcome"], how="inner")
    out = out[(out["entry_price"] > 0) & (out["entry_price"] < 1) & (out["buy_cost"] > 0)]
    return out


def _persistence(pos: pd.DataFrame) -> tuple[bool, int, int]:
    """Net-positive realized P&L in a majority of time sub-periods."""
    if pos["resolved_at"].nunique() < N_SUBPERIODS:
        periods = pos.assign(_p=pd.qcut(pos["first_ts"].rank(method="first"),
                                        min(N_SUBPERIODS, len(pos)), labels=False))
    else:
        periods = pos.assign(_p=pd.qcut(pos["resolved_at"].rank(method="first"),
                                        N_SUBPERIODS, labels=False))
    sums = periods.groupby("_p")["realized_pnl"].sum()
    pos_periods = int((sums > 0).sum())
    return pos_periods > len(sums) / 2, pos_periods, int(len(sums))


def main() -> None:
    eng = create_engine(sync_dsn(None))
    df = _load(eng)
    cov = _coverage(eng, list(json.load(open(POOL))["candidates"]))
    eng.dispose()
    df["fam_category"] = df["slug"].map(classify_market)
    print(f"[funnel] loaded {len(df)} resolved fact trades; "
          f"{df['wallet'].nunique()} accounts; {df['market'].nunique()} markets")

    pos = _positions(df)
    # attach category from slug via the market->category map
    cat_map = df.drop_duplicates("market").set_index("market")["fam_category"]
    pos["category"] = pos["market"].map(cat_map)

    # eligibility distribution (per account, per category)
    elig = (pos.groupby(["wallet", "category"])["market"].nunique()
            .rename("n_markets").reset_index())
    print("\n[eligibility] distinct resolved markets per (account, category) — distribution:")
    for cat, g in elig.groupby("category"):
        bins = [(g["n_markets"] >= 10).sum(), (g["n_markets"].between(5, 9)).sum(),
                (g["n_markets"].between(1, 4)).sum()]
        print(f"  {cat:12s} accounts: >=10 mkts={bins[0]:4d}  5-9={bins[1]:4d}  1-4={bins[2]:4d}")

    rows = []
    for (wallet, cat), g in pos.groupby(["wallet", "category"]):
        n_markets = g["market"].nunique()
        if n_markets < MIN_MARKETS or cat in ("other", "pop_culture"):
            continue
        persist_ok, pp, npp = _persistence(g)
        typ = classify_by_entry(g["entry_price"].to_numpy())
        pnl = float(g["realized_pnl"].sum())
        cost = float(g["buy_cost"].sum())
        roi = pnl / cost if cost > 0 else np.nan
        obs, exp, pval = beat_market_p(g["entry_price"].to_numpy(), g["payout"].to_numpy())
        med_entry = float(g["entry_price"].median())
        rows.append({
            "wallet": wallet, "category": cat, "type": typ, "n_markets": n_markets,
            "persist_ok": persist_ok, "persist": f"{pp}/{npp}", "pnl": pnl, "roi": roi,
            "wins_obs": obs, "wins_exp_mkt": exp, "skill_p": pval, "med_entry": med_entry,
            "coverage": cov.get(wallet, 0.0),
            "info_flag": "INFORMATION" if med_entry < 0.5 else "MODELING",
        })
    res = pd.DataFrame(rows)
    if res.empty:
        print("\n[funnel] no accounts reached eligibility (>=10 distinct resolved markets in a category).")
        return

    # skill verdict by type
    def survives(r):
        if not r["persist_ok"]:
            return False
        if r["type"] == "predictor":
            return r["skill_p"] < SIG and r["wins_obs"] > r["wins_exp_mkt"]
        if r["type"] == "momentum_rider":
            return r["roi"] > 0
        return False  # favorite_farmer dropped

    res["survives"] = res.apply(survives, axis=1)
    print(f"\n[funnel] eligible (account,category) cells: {len(res)}  "
          f"| types: {res['type'].value_counts().to_dict()}")
    print(f"[funnel] favorite-farmers dropped: {(res['type']=='favorite_farmer').sum()}")

    surv = res[res["survives"]].copy()
    for typ in ("predictor", "momentum_rider"):
        t = surv[surv["type"] == typ].sort_values(["pnl", "roi"], ascending=False)
        print(f"\n===== SURVIVING {typ.upper()}S ({len(t)}) — ranked by P&L then %return =====")
        for _, r in t.head(20).iterrows():
            print(f"  {r['wallet'][:12]} {r['category']:11s} mkts={r['n_markets']:3d} "
                  f"persist={r['persist']} pnl=${r['pnl']:>10.0f} roi={r['roi']:>6.1%} "
                  f"p={r['skill_p']:.3f} entry={r['med_entry']:.2f} cov={r['coverage']:.0%} "
                  f"[{r['info_flag']}]")

    # No-skill null control. The correct null for a "beat the market-implied prob"
    # test is per-position outcome ~ Bernoulli(entry_price): a calibrated market with
    # zero account skill. (A permutation of realized labels is WRONG here — it imposes
    # the pool's marginal win rate, which carries a favorite-longshot/selection bias
    # that inflates the test; we report that gap separately as a diagnostic.)
    preds = pos.merge(res[res["type"] == "predictor"][["wallet", "category"]],
                      on=["wallet", "category"])
    # diagnostic: pool-wide realized win rate vs entry-implied among predictor positions
    gap = float(preds["payout"].mean() - preds["entry_price"].mean())
    print(f"\n[diagnostic] predictor positions: mean realized win={preds['payout'].mean():.3f} "
          f"vs mean entry-implied={preds['entry_price'].mean():.3f}  (pool gap={gap:+.3f})")

    pred_accounts = [g["entry_price"].to_numpy() for _, g in preds.groupby(["wallet", "category"])
                     if g["market"].nunique() >= MIN_MARKETS]
    null_counts = calibrated_null_counts(pred_accounts, n_sims=50, seed=0, sig=SIG)
    n_pred_cells = int((res["type"] == "predictor").sum())
    real_pred = int((surv["type"] == "predictor").sum())
    exp_fp = SIG * n_pred_cells
    print(f"[null control] {n_pred_cells} predictor cells; calibrated-market null survivors: "
          f"mean={np.mean(null_counts):.1f} max={max(null_counts)} (expect ~{exp_fp:.1f} at {SIG:.0%})")
    verdict = "PASS (real > null)" if real_pred > np.mean(null_counts) else "AT-CHANCE (no edge beyond calibration)"
    print(f"[null control] real predictor survivors={real_pred} -> {verdict}")


if __name__ == "__main__":
    main()

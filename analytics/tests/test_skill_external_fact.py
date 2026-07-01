"""External-fact skill funnel: eligibility -> persistence -> type -> skill test,
with a market-calibrated null control. Pure fixtures, no DB.

The synthetic pool is engineered so each funnel branch is exercised:
  PRED   predictor    — enters uncertain (0.45), wins far above the implied rate
  MOMO   momentum     — enters after the move (0.72), persistent + positive ROI,
                        does NOT beat the market (correct by construction)
  FARM   fav-farmer   — only high-prob (0.92) entries -> dropped, no edge
  NOOB   ineligible   — 5 distinct markets (< 10) -> excluded
  REPEAT one market    — same market 20x -> 1 distinct market -> excluded
  SPOT   thin category — 3 entertainment markets -> no studyable population
  SCALP  latency       — btc-updown-5m families -> excluded up front
"""

import pandas as pd
from bellwether_analytics.skill import (
    SkillConfig,
    category_recon,
    exclude_latency,
    is_latency_family,
    null_control,
    rank_strategists,
    rank_within_type,
)

T0 = pd.Timestamp("2026-01-01T00:00:00Z")


def _buy(wallet, market, slug, category, outcome, price, resolution, i, size=100.0):
    resolved_at = T0 + pd.Timedelta(days=i)
    return dict(
        wallet=wallet, market=market, slug=slug, category=category, outcome=outcome,
        side="BUY", size=size, price=price, notional=size * price,
        ts=resolved_at - pd.Timedelta(days=1), resolution=resolution, resolved_at=resolved_at,
    )


def _account(wallet, category, slug_stem, entry, win_flags):
    """One BUY per distinct market; win_flags[i] decides resolution."""
    rows = []
    for i, won in enumerate(win_flags):
        res = "YES" if won else "NO"
        rows.append(_buy(wallet, f"{wallet}-m{i}", f"{slug_stem}-{i}", category, "YES", entry, res, i))
    return rows


def _fixture():
    rows = []
    # PRED: 12 political markets @0.45, 10 wins (losers spread so each third stays +)
    pred_wins = [1, 1, 1, 0, 1, 1, 1, 0, 1, 1, 1, 1]
    rows += _account("PRED", "politics", "election", 0.45, pred_wins)
    # MOMO: 12 sports markets @0.72, 9 wins, 3W1L per third -> persistent + positive ROI
    momo_wins = [1, 1, 1, 0, 1, 1, 1, 0, 1, 1, 1, 0]
    rows += _account("MOMO", "sports", "nba-final", 0.72, momo_wins)
    # FARM: 12 economics markets @0.92, 11 wins -> favorite-farmer, dropped
    farm_wins = [1] * 11 + [0]
    rows += _account("FARM", "economics", "fed-decision", 0.92, farm_wins)
    # NOOB: only 5 political markets -> ineligible
    rows += _account("NOOB", "politics", "senate-race", 0.5, [1, 0, 1, 0, 1])
    # REPEAT: one political market traded 20x -> 1 distinct market -> ineligible
    for _ in range(20):
        rows.append(_buy("REPEAT", "REPEAT-m0", "governor-2026", "politics", "YES", 0.4, "YES", 0))
    # SPOT: 3 entertainment markets -> thin, no studyable population
    rows += _account("SPOT", "entertainment", "spotify-streams", 0.5, [1, 0, 1])
    # SCALP: 15 btc-updown-5m latency markets -> excluded before the funnel
    rows += _account("SCALP", "crypto", "btc-updown-5m", 0.5, [1, 0] * 7 + [1])
    return pd.DataFrame(rows)


def test_is_latency_family():
    assert is_latency_family("btc-updown-5m")
    assert is_latency_family("eth-up-or-down")
    assert not is_latency_family("election-event")
    assert not is_latency_family("nba-final")


def test_exclude_latency_drops_updown_only():
    trades = _fixture()
    kept = exclude_latency(trades)
    assert (kept["wallet"] == "SCALP").sum() == 0          # updown scalper gone
    assert (kept["wallet"] == "PRED").sum() == 12          # external-fact untouched


def test_category_recon_flags_thin_and_excludes_latency():
    recon = category_recon(_fixture())
    cats = set(recon["category"])
    assert "crypto" not in cats                            # updown-only crypto excluded entirely
    politics = recon[recon["category"] == "politics"].iloc[0]
    assert politics["studyable"] and politics["n_eligible_accounts"] == 1   # PRED
    ent = recon[recon["category"] == "entertainment"].iloc[0]
    assert not ent["studyable"] and "no studyable population" in ent["note"]


def test_eligibility_excludes_thin_and_single_market_accounts():
    funnel = rank_strategists(_fixture())
    assert set(funnel["wallet"]) == {"PRED", "MOMO", "FARM"}   # NOOB/REPEAT/SPOT/SCALP excluded
    assert int(funnel.set_index("wallet").loc["PRED", "n_markets"]) == 12


def test_predictor_survives_beating_the_market():
    funnel = rank_strategists(_fixture()).set_index("wallet")
    pred = funnel.loc["PRED"]
    assert pred["type"] == "predictor"
    assert pred["skill_p"] < 0.05        # beat the entry-price-implied win rate
    assert pred["persistence"] == 1.0
    assert pred["realized_pnl"] > 0 and pred["roi"] > 0
    assert pred["survived"]
    assert pred["edge_source_hint"] == "information"   # entered below 0.5


def test_momentum_survives_on_persistence_and_roi_not_beating_market():
    funnel = rank_strategists(_fixture()).set_index("wallet")
    momo = funnel.loc["MOMO"]
    assert momo["type"] == "momentum_rider"
    assert momo["skill_p"] > 0.05        # can't beat the market by construction
    assert momo["persistence_pass"] and momo["roi"] > 0
    assert momo["survived"]
    assert momo["edge_source_hint"] == "modeling"


def test_favorite_farmer_is_dropped():
    funnel = rank_strategists(_fixture()).set_index("wallet")
    farm = funnel.loc["FARM"]
    assert farm["type"] == "favorite_farmer"
    assert not farm["survived"]
    assert "favorite-farmer" in farm["drop_reason"]


def test_rank_within_type_reports_pnl_and_return():
    survivors = rank_within_type(rank_strategists(_fixture()))
    assert set(survivors["wallet"]) == {"PRED", "MOMO"}
    for _, r in survivors.iterrows():
        assert r["pnl_rank"] == 1        # one survivor per type here
        assert r["return_rank"] == 1


def test_null_control_collapses_the_edge():
    trades = _fixture()
    out = null_control(trades, config=SkillConfig(null_draws=60), seed=7)
    assert out["real_survivors"] >= 2
    assert out["null_survivors_mean"] < out["real_survivors"]
    assert out["real_predictors_beat_market"] >= 1
    # a no-skill null beats the market only at ~the significance level, not reliably
    assert out["null_predictors_beat_market_mean"] < 1.0

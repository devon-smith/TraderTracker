"""External-fact skill funnel: eligibility -> persistence -> type -> type-appropriate
skill test, FDR-gated so a no-skill null yields ~no survivors. Pure fixtures, no DB.

The synthetic pool exercises every branch:
  PRED   predictor      — enters uncertain (0.45), wins far above implied -> survives
  MOMO   momentum       — enters after the move (0.70), captures MORE than random
                          entry into moving markets (P&L beats the null) -> survives
  LUCK   momentum(luck) — enters 0.70, positive ROI but within noise -> DROPPED
                          (persistence + positive ROI alone is not skill)
  FARM   fav-farmer     — only high-prob (0.92) -> dropped, no edge
  LONG   longshot       — sub-0.15 entries (dust/longshot) -> dropped, no edge
  NOOB   ineligible     — 5 distinct markets (< 10) -> excluded
  REPEAT one market     — same market 20x -> 1 distinct market -> excluded
  SPOT   thin category  — 3 entertainment markets -> no studyable population
  SCALP  latency        — btc-updown-5m families -> excluded up front
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


def _buy(wallet, market, slug, category, price, resolution, i, size=100.0):
    resolved_at = T0 + pd.Timedelta(days=i)
    return dict(
        wallet=wallet, market=market, slug=slug, category=category, outcome="YES",
        side="BUY", size=size, price=price, notional=size * price,
        ts=resolved_at - pd.Timedelta(days=1), resolution=resolution, resolved_at=resolved_at,
    )


def _account(wallet, category, stem, entry, win_flags):
    return [_buy(wallet, f"{wallet}-m{i}", f"{stem}-{i}", category, entry,
                 "YES" if won else "NO", i) for i, won in enumerate(win_flags)]


def _fixture():
    rows = []
    rows += _account("PRED", "politics", "election", 0.45,
                     [1, 1, 1, 0, 1, 1, 1, 0, 1, 1, 1, 1])            # 10/12 >> 0.45 implied
    rows += _account("MOMO", "sports", "nba-final", 0.70, [1] * 13 + [0])  # 13/14 >> 0.70
    rows += _account("LUCK", "economics", "cpi-print", 0.70,
                     [1, 1, 1, 0, 1, 1, 1, 0, 1, 1, 1, 0])            # 9/12 ~ 0.70 (noise)
    rows += _account("FARM", "economics", "fed-decision", 0.92, [1] * 11 + [0])
    rows += _account("LONG", "politics", "longshot-senate", 0.05, [1, 0] * 5)
    rows += _account("NOOB", "politics", "senate-race", 0.5, [1, 0, 1, 0, 1])
    for _ in range(20):
        rows.append(_buy("REPEAT", "REPEAT-m0", "governor-2026", "politics", 0.4, "YES", 0))
    rows += _account("SPOT", "entertainment", "spotify-streams", 0.5, [1, 0, 1])
    rows += _account("SCALP", "crypto", "btc-updown-5m", 0.5, [1, 0] * 7 + [1])
    return pd.DataFrame(rows)


def test_is_latency_family():
    assert is_latency_family("btc-updown-5m")
    assert is_latency_family("eth-up-or-down")
    assert not is_latency_family("election-event")


def test_exclude_latency_drops_updown_only():
    kept = exclude_latency(_fixture())
    assert (kept["wallet"] == "SCALP").sum() == 0
    assert (kept["wallet"] == "PRED").sum() == 12


def test_category_recon_flags_thin_and_excludes_latency():
    recon = category_recon(_fixture())
    assert "crypto" not in set(recon["category"])          # updown-only crypto excluded
    politics = recon[recon["category"] == "politics"].iloc[0]
    assert politics["studyable"] and politics["n_eligible_accounts"] >= 1
    ent = recon[recon["category"] == "entertainment"].iloc[0]
    assert not ent["studyable"] and "no studyable population" in ent["note"]


def test_eligibility_excludes_thin_and_single_market_accounts():
    funnel = rank_strategists(_fixture())
    assert set(funnel["wallet"]) == {"PRED", "MOMO", "LUCK", "FARM", "LONG"}
    assert int(funnel.set_index("wallet").loc["PRED", "n_markets"]) == 12


def test_predictor_survives_beating_the_market():
    f = rank_strategists(_fixture()).set_index("wallet")
    pred = f.loc["PRED"]
    assert pred["type"] == "predictor" and pred["skill_test"] == "binomial_vs_entry"
    assert pred["skill_p"] < 0.05 and pred["persistence"] == 1.0
    assert pred["survived"] and pred["edge_source_hint"] == "information"


def test_momentum_survives_only_when_it_beats_random_entry():
    f = rank_strategists(_fixture()).set_index("wallet")
    momo, luck = f.loc["MOMO"], f.loc["LUCK"]
    assert momo["type"] == "momentum_rider" and momo["skill_test"] == "pnl_vs_random_entry"
    assert momo["skill_p"] < 0.05 and momo["survived"]
    # LUCK: positive ROI + persistence but within noise -> NOT skill, dropped
    assert luck["type"] == "momentum_rider" and luck["roi"] > 0 and luck["persistence_pass"]
    assert not luck["survived"] and luck["skill_p"] > 0.05


def test_favorite_farmer_and_longshot_dropped():
    f = rank_strategists(_fixture()).set_index("wallet")
    assert f.loc["FARM", "type"] == "favorite_farmer" and not f.loc["FARM", "survived"]
    assert f.loc["LONG", "type"] == "longshot" and not f.loc["LONG", "survived"]


def test_rank_within_type_reports_pnl_and_return():
    survivors = rank_within_type(rank_strategists(_fixture()))
    assert set(survivors["wallet"]) == {"PRED", "MOMO"}
    for _, r in survivors.iterrows():
        assert r["pnl_rank"] == 1 and r["return_rank"] == 1


def test_null_control_collapses_the_edge():
    out = null_control(_fixture(), config=SkillConfig(null_draws=80), seed=7)
    assert out["real_survivors"] >= 2
    assert out["null_survivors_mean"] < 1.0            # FDR gate: no-skill null yields ~none
    assert out["real_predictors_beat_market"] >= 1

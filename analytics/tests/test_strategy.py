import pandas as pd
from bellwether_analytics.strategy import (
    classify,
    detect_followers,
    extract_features,
    market_family,
    strategy_templates,
)

T0 = pd.Timestamp("2026-01-01T00:00:00Z")


def _t(wallet, market, slug, side, notional, ts, outcome="YES", category="crypto"):
    price = 0.5
    return dict(wallet=wallet, market=market, slug=slug, category=category, outcome=outcome,
                side=side, size=notional / price, price=price, notional=notional, ts=ts,
                resolution=None, resolved_at=pd.NaT)


def test_market_family_collapses_variable_suffix():
    assert market_family("btc-updown-5m-1782846000") == "btc-updown-5m"
    assert market_family("btc-updown-5m-1782846300") == "btc-updown-5m"
    assert market_family("fifwc-fra-swe-2026-06-30-fra") == "fifwc-fra-swe-fra"
    assert market_family(None) == "unknown"


def test_scalper_vs_market_maker_vs_accumulator():
    rows = []
    # SCALPER: 60 rapid one-sided-ish fills, all in the btc-updown-5m family, short gaps
    for i in range(60):
        slug = f"btc-updown-5m-{1000 + i}"
        side = "BUY" if i % 2 == 0 else "SELL"
        rows.append(_t("SCALP", f"m{i}", slug, side, 50, T0 + pd.Timedelta(seconds=30 * i)))
    # MARKET_MAKER: balanced buy/sell, heavy round-tripping in same markets, active
    for i in range(40):
        mkt = f"mm{i % 5}"  # 5 markets, repeated -> round trips
        side = "BUY" if i % 2 == 0 else "SELL"
        rows.append(_t("MM", mkt, f"election-{i % 5}", side, 100, T0 + pd.Timedelta(hours=i),
                       category="politics"))
    # ACCUMULATOR: one-directional buys, distinct markets, slower
    for i in range(30):
        rows.append(_t("ACC", f"a{i}", f"sports-game-{i}", "BUY", 500,
                       T0 + pd.Timedelta(hours=6 * i), category="sports"))

    feats = extract_features(pd.DataFrame(rows))
    labels = classify(feats)["archetype"].to_dict()

    assert labels["SCALP"] == "scalper"
    assert labels["MM"] == "market_maker"
    assert labels["ACC"] == "accumulator"


def test_arbitrageur_from_split_merge_events():
    trades = pd.DataFrame([_t("ARB", "m1", "x-1", "BUY", 100, T0)])
    events = pd.DataFrame([
        dict(wallet="ARB", event_type="SPLIT", value=50.0),
        dict(wallet="ARB", event_type="MERGE", value=40.0),
    ])
    feats = extract_features(trades, events)
    assert classify(feats).loc["ARB", "archetype"] == "arbitrageur"


def test_strategy_templates_counts_wallets_per_family_archetype():
    rows = []
    # two scalpers running the SAME btc-updown-5m template -> a repeated strategy
    for w in ("S1", "S2"):
        for i in range(60):
            side = "BUY" if i % 2 == 0 else "SELL"
            rows.append(_t(w, f"{w}m{i}", f"btc-updown-5m-{i}", side, 50,
                           T0 + pd.Timedelta(seconds=30 * i)))
    trades = pd.DataFrame(rows)
    feats = extract_features(trades)
    arche = classify(feats)["archetype"]
    templates = strategy_templates(trades, arche, min_wallets=2)
    top = templates.iloc[0]
    assert top["archetype"] == "scalper"
    assert top["family"] == "btc-updown-5m"
    assert top["n_wallets"] == 2


def _oc(wallet, market, slug, side, notional, ts, is_taker, outcome="YES", category="crypto"):
    row = _t(wallet, market, slug, side, notional, ts, outcome, category)
    row["is_taker"] = is_taker
    return row


def test_aggressor_taker_ratio_separates_maker_from_taker():
    base = []
    # MAKER: balanced, round-tripping across 5 repeated markets, all maker fills.
    for i in range(40):
        base.append(_oc("MAKER", f"mm{i % 5}", f"election-{i % 5}", "BUY" if i % 2 == 0 else "SELL",
                        100, T0 + pd.Timedelta(hours=i), is_taker=False, category="politics"))
    feats = extract_features(pd.DataFrame(base))
    assert feats.loc["MAKER", "has_aggressor_data"]
    assert feats.loc["MAKER", "taker_ratio"] == 0.0
    labeled = classify(feats)
    assert labeled.loc["MAKER", "archetype"] == "market_maker"
    assert "taker_ratio" in labeled.loc["MAKER", "reason"]


def test_aggressor_gating_blocks_market_maker_when_taker_heavy():
    rows = []
    # Same balanced/round-trip features, but every fill is an aggressive taker.
    for i in range(40):
        rows.append(_oc("TK", f"mm{i % 5}", f"election-{i % 5}", "BUY" if i % 2 == 0 else "SELL",
                        100, T0 + pd.Timedelta(hours=i), is_taker=True, category="politics"))
    feats = extract_features(pd.DataFrame(rows))
    assert feats.loc["TK", "taker_ratio"] == 1.0
    # High taker_ratio must disqualify market_maker (it is not providing liquidity).
    assert classify(feats).loc["TK", "archetype"] != "market_maker"


def test_rest_only_wallet_has_no_aggressor_data_but_still_classifies():
    rows = [_t("R", f"m{i}", f"sports-game-{i}", "BUY", 500, T0 + pd.Timedelta(hours=6 * i),
               category="sports") for i in range(30)]
    feats = extract_features(pd.DataFrame(rows))  # no is_taker column
    assert feats.loc["R", "has_aggressor_data"] == False  # noqa: E712
    assert classify(feats).loc["R", "archetype"] == "accumulator"  # graceful fallback


def test_detect_followers_finds_consistent_copier():
    rows = []
    # LEADER trades first in each market; FOLLOWER copies ~10s later, same side.
    for i in range(5):
        mkt = f"mk{i}"
        rows.append(_t("LEADER", mkt, f"f-{i}", "BUY", 100, T0 + pd.Timedelta(minutes=i)))
        rows.append(_t("FOLLOWER", mkt, f"f-{i}", "BUY", 100,
                       T0 + pd.Timedelta(minutes=i, seconds=10)))
        # an unrelated wallet much later -> not a follow
        rows.append(_t("NOISE", mkt, f"f-{i}", "BUY", 100, T0 + pd.Timedelta(minutes=i, seconds=600)))
    pairs = detect_followers(pd.DataFrame(rows), max_lag_seconds=60, min_events=3)
    assert not pairs.empty
    top = pairs.iloc[0]
    assert top["leader"] == "LEADER"
    assert top["follower"] == "FOLLOWER"
    assert top["follow_events"] == 5

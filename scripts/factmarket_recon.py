"""Step 0 recon: the resolved external-fact market universe on Polymarket.

Builds a deduped set of RESOLVED, Gamma-served markets (decisive outcome), EXCLUDES
updown/latency families, classifies each into an external-fact category, and reports
per category: # resolved markets, time span, and volume depth. This defines which
categories have a studyable specialist population before we pull participants.

Writes the market set to .cache/factmarkets.json for the participant-pull step.
"""

from __future__ import annotations

import json
import os
import re
import statistics

import httpx
from bellwether_ingestion.polymarket.categorize import gamma_market_fields

G = "https://gamma-api.polymarket.com"
STATE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".cache", "factmarkets.json"))

EXCLUDE = re.compile(r"updown|up-or-down|-1[05]m-|hourly|-et-\d")  # latency/updown families

# External-fact category keywords (checked against slug + question, lowercased).
CATS = {
    "geopolitics": ["war", "ceasefire", "strike-iran", "invasion", "nato", "nuclear", "hostage",
                    "peace-deal", "military", "missile", "coup", "forces-enter", "regime",
                    "supreme-leader", "khamenei", "netanyahu", "zelenskyy", "iran", "israel",
                    "ukraine", "russia", "gaza", "taiwan", "hamas", "houthi", "ceasefire"],
    "politics": ["election", "president", "senate", "congress", "house-race", "governor", "primary",
                 "nominee", "nomination", "mayor", "parliament", "referendum", "policy", "fed-",
                 "rate-cut", "rate-hike", "shutdown", "sanction", "tariff", "supreme-court",
                 "cabinet", "approval", "inaugurat", "-out-by", "out-as", "-out-in", "resign",
                 "impeach", "prime-minister", "poilievre", "epstein", "tiktok", "banned",
                 "go-live", "confirmed-as", "pardon", "poll"],
    "sports": ["nba", "nfl", "mlb", "nhl", "premier-league", "epl", "ucl", "champions-league",
               "world-cup", "super-bowl", "finals", "playoff", "world-series", "-cup-", "-series-",
               "grand-prix", "masters", "la-liga", "conference", "-win-the", "fifwc", "betis",
               "hornets", "-vs-", "wins-the", "relegat", "bundesliga", "serie-a"],
    "crypto_event": ["bitcoin", "ethereum", "solana", "-eth-", "-btc-", "token", "airdrop",
                     "listing", "etf", "mainnet", "-launch", "fdv", "all-time-high", "flippening",
                     "coinbase", "binance", "hyperliquid", "reach-"],
    "pop_culture": ["spotify", "streams", "box-office", "grammy", "oscar", "emmy", "billboard",
                    "rotten-tomatoes", "netflix", "movie", "album", "tv-", "rating", "award",
                    "song-of", "time-person", "stranger-things", "-season-", "die-in", "-die-",
                    "grand-theft-auto", "gta"],
}


def _classify(m: dict) -> str:
    text = ((m.get("slug") or "") + " " + (m.get("question") or "")).lower()
    for cat, kws in CATS.items():
        if any(k in text for k in kws):
            return cat
    return "other"


def _unwrap(x):
    x = x["data"] if isinstance(x, dict) and "data" in x else x
    return [m for m in x if isinstance(m, dict)] if isinstance(x, list) else []


def main() -> None:
    c = httpx.Client(timeout=40, headers={"User-Agent": "bellwether/0.2"})
    markets: dict[str, dict] = {}
    for order in ("volumeNum", "endDate", "volume24hr", "liquidityNum"):
        b = _unwrap(c.get(f"{G}/markets", params={
            "closed": "true", "limit": 500, "order": order, "ascending": "false"}).json())
        for m in b:
            cid = m.get("conditionId")
            if cid and cid not in markets:
                markets[cid] = m
    print(f"[recon] collected {len(markets)} distinct closed markets from Gamma")

    # keep resolved (decisive outcome), non-updown, with real volume
    rows = []
    for cid, m in markets.items():
        slug = m.get("slug") or ""
        if EXCLUDE.search(slug):
            continue
        f = gamma_market_fields(m)
        if f["resolution"] is None:
            continue
        vol = m.get("volumeNum") or 0
        rows.append({
            "conditionId": cid, "slug": slug, "question": m.get("question"),
            "category": _classify(m), "volume": vol,
            "endDate": (m.get("endDate") or "")[:10], "resolution": f["resolution"],
        })

    by_cat: dict[str, list] = {}
    for r in rows:
        by_cat.setdefault(r["category"], []).append(r)

    print(f"[recon] {len(rows)} resolved non-updown markets\n")
    print(f"{'category':14s} {'#mkts':>6s} {'span (endDate)':>26s} {'medVol':>10s} {'>=50k':>6s}")
    for cat in sorted(by_cat, key=lambda k: -len(by_cat[k])):
        ms = by_cat[cat]
        ends = sorted(x["endDate"] for x in ms if x["endDate"])
        vols = [x["volume"] for x in ms]
        span = f"{ends[0]}..{ends[-1]}" if ends else "n/a"
        deep = sum(1 for v in vols if v >= 50_000)
        print(f"{cat:14s} {len(ms):6d} {span:>26s} {statistics.median(vols):10.0f} {deep:6d}")

    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w") as fh:
        json.dump(rows, fh)
    print(f"\n[recon] wrote {len(rows)} markets -> {STATE}")


if __name__ == "__main__":
    main()

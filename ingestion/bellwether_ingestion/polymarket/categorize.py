"""Normalize a Polymarket (Gamma) market into canonical market fields.

Gamma's top-level `category` is frequently null and `tags` aren't in the basic
/markets response, so category is resolved in layers:
  1. the market's `category` field, if present;
  2. the first tag label, if tags are present;
  3. a keyword scan over the slug + question (Polymarket slugs are very regular).

Resolution is derived from `closed` + `outcomePrices` (the outcome whose price
settled to ~1 is the winner).
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Optional

# Checked in priority order; first category with a keyword hit wins.
CATEGORY_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("crypto", ("btc", "bitcoin", "eth", "ethereum", "solana", "crypto", "doge",
                "xrp", "updown", "binance", "coinbase", "stablecoin")),
    ("economics", ("fed", "fomc", "interest-rate", "rate-cut", "rate-hike", "cpi",
                   "inflation", "gdp", "recession", "nfp", "unemployment", "powell", "jobs-report")),
    ("politics", ("election", "president", "senate", "congress", "biden", "trump",
                  "governor", "primary", "democrat", "republican", "gop", "mamdani",
                  "mayor", "parliament", "prime-minister", "nominee", "approval", "poll")),
    ("sports", ("nfl", "nba", "mlb", "nhl", "ucl", "epl", "fifa", "fifwc", "worldcup",
                "world-cup", "soccer", "tennis", "ufc", "-f1-", "ncaa", "superbowl",
                "super-bowl", "-vs-", "premier-league", "la-liga", "champions",
                "playoff", "wins-the", "-game", "match")),
    ("entertainment", ("oscar", "grammy", "movie", "box-office", "rotten", "album",
                       "spotify", "netflix", "rotten-tomatoes")),
]


def normalize_category(market: dict) -> str:
    cat = market.get("category")
    if cat:
        return str(cat).lower()
    tags = market.get("tags")
    if tags and isinstance(tags, list) and tags:
        first = tags[0]
        label = first.get("label") if isinstance(first, dict) else first
        if label:
            return str(label).lower()
    hay = f"{market.get('slug', '')} {market.get('question', '')}".lower()
    for category, keywords in CATEGORY_KEYWORDS:
        if any(k in hay for k in keywords):
            return category
    return "other"


def _loads(x) -> list:
    if isinstance(x, str):
        try:
            return json.loads(x)
        except Exception:
            return []
    return x or []


def _parse_dt(s: Optional[str]) -> Optional[dt.datetime]:
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None


def gamma_market_fields(market: dict) -> dict:
    outcomes = _loads(market.get("outcomes"))
    prices = [float(p) for p in _loads(market.get("outcomePrices") or [])]
    closed = bool(market.get("closed"))

    resolution: Optional[str] = None
    resolved_at: Optional[dt.datetime] = None
    if closed:
        resolved_at = _parse_dt(market.get("closedTime")) or _parse_dt(market.get("endDate"))
        if outcomes and prices and len(prices) == len(outcomes):
            mx = max(prices)
            if mx >= 0.99 and prices.count(mx) == 1:
                resolution = outcomes[prices.index(mx)]

    return {
        "external_id": market.get("conditionId"),
        "title": market.get("question"),
        "slug": market.get("slug"),
        "category": normalize_category(market),
        "raw_category": market.get("category"),
        "created_at": _parse_dt(market.get("createdAt")),
        "resolved_at": resolved_at,
        "resolution": resolution,
        "is_multi_outcome": len(outcomes) != 2,
    }

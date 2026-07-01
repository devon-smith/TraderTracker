"""Seed a REAL external-fact candidate pool from recent RESOLVED Gamma markets and
run the skill funnel on it (Step 0 of the external-fact skill goal).

Why market-level trades (not per-wallet history): the Data API's
`/trades?market=<conditionId>` returns every fill in a market with size, price,
timestamp, side and outcome — enough to settle P&L directly — and it only takes a
few pages per market. Restricting the universe to RESOLVED markets means every
row is scoreable, and accounts accumulate their distinct-resolved-market counts
naturally across the universe. No DB required: the skill funnel operates on a
trades DataFrame.

Pipeline:
  1. enumerate recent, high-volume RESOLVED Gamma markets in the target
     external-fact categories, excluding updown/latency families;
  2. pull market-level trades for each (bounded pages, threaded);
  3. assemble a resolved trades DataFrame and cache it;
  4. run category_recon + rank_strategists + rank_within_type + null_control.

Usage:
  python scripts/external_fact_pool.py build    # pull + cache the pool
  python scripts/external_fact_pool.py report   # run recon + funnel on the cache
  python scripts/external_fact_pool.py all       # build then report
"""

from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx
import pandas as pd
from bellwether_ingestion.polymarket.categorize import gamma_market_fields

CACHE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".cache", "external_fact_trades.parquet"))

DATA_API = os.environ.get("POLYMARKET_DATA_API", "https://data-api.polymarket.com")
GAMMA_API = os.environ.get("POLYMARKET_GAMMA_API", "https://gamma-api.polymarket.com")

# Gamma's native categories that resolve against a knowable external fact.
TARGET_CATEGORIES = {
    "politics", "sports", "economics", "crypto", "business", "tech",
    "us-current-affairs", "world", "geopolitics", "pop-culture", "entertainment",
}
LATENCY_SLUG_MARKERS = ("updown", "up-or-down", "-5m", "-15m", "-30m", "-1h", "-4h", "hourly")

# Tunables (kept modest to be a good API citizen; raise on the VM).
N_MARKET_PAGES = 5          # Gamma market pages (100/page) to scan for the universe
MAX_MARKETS = 220           # cap on resolved markets in the universe
TRADE_PAGES = 6             # market-level trade pages per market (500/page)
MIN_VOLUME = 20000.0        # depth floor: skip thin markets
WORKERS = 8


def _client() -> httpx.Client:
    return httpx.Client(timeout=30.0, headers={"User-Agent": "bellwether/0.2"})


def _is_latency(slug: str | None) -> bool:
    s = (slug or "").lower()
    return any(m in s for m in LATENCY_SLUG_MARKERS)


def _resolved_universe(c: httpx.Client) -> list[dict]:
    """Recent, high-volume RESOLVED external-fact markets, latency excluded."""
    seen: dict[str, dict] = {}
    for page in range(N_MARKET_PAGES):
        params = {"closed": "true", "limit": 100, "offset": page * 100,
                  "order": "volumeNum", "ascending": "false"}
        raw = c.get(f"{GAMMA_API}/markets", params=params).json()
        rows = raw["data"] if isinstance(raw, dict) and "data" in raw else raw
        if not rows:
            break
        for m in rows:
            f = gamma_market_fields(m)
            cid, slug = f["external_id"], f["slug"]
            vol = m.get("volumeNum") or 0
            if not (cid and f["resolution"] and slug):
                continue
            if f["category"] not in TARGET_CATEGORIES or _is_latency(slug):
                continue
            if vol < MIN_VOLUME or cid in seen:
                continue
            seen[cid] = {"conditionId": cid, "slug": slug, "category": f["category"],
                         "resolution": f["resolution"], "resolved_at": f["resolved_at"], "volume": vol}
        time.sleep(0.2)
    universe = sorted(seen.values(), key=lambda r: r["volume"], reverse=True)[:MAX_MARKETS]
    return universe


def _market_trades(c: httpx.Client, m: dict) -> list[dict]:
    """All captured fills for one resolved market as canonical trade rows."""
    out = []
    for page in range(TRADE_PAGES):
        try:
            raw = c.get(f"{DATA_API}/trades",
                        params={"market": m["conditionId"], "limit": 500, "offset": page * 500}).json()
        except Exception:  # noqa: BLE001
            break
        batch = raw["data"] if isinstance(raw, dict) and "data" in raw else raw
        if not batch:
            break
        for t in batch:
            size = t.get("size")
            price = t.get("price")
            if size is None or price is None:
                continue
            out.append({
                "wallet": t.get("proxyWallet"),
                "market": m["conditionId"],
                "category": m["category"],
                "slug": m["slug"],
                "outcome": t.get("outcome"),
                "side": t.get("side"),
                "size": float(size),
                "price": float(price),
                "notional": float(size) * float(price),
                "ts": pd.to_datetime(t.get("timestamp"), unit="s", utc=True),
                "resolution": m["resolution"],
                "resolved_at": pd.to_datetime(m["resolved_at"], utc=True),
            })
        if len(batch) < 500:
            break
    return out


def build() -> pd.DataFrame:
    c = _client()
    universe = _resolved_universe(c)
    import collections
    per_cat = collections.Counter(m["category"] for m in universe)
    print(f"[build] resolved external-fact universe: {len(universe)} markets, categories={dict(per_cat)}")

    rows: list[dict] = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(_market_trades, _client(), m): m for m in universe}
        for i, fu in enumerate(as_completed(futs), 1):
            try:
                rows.extend(fu.result())
            except Exception as e:  # noqa: BLE001
                print(f"  market fail: {e}")
            if i % 25 == 0:
                print(f"  {i}/{len(universe)} markets, {len(rows)} trades, {time.time()-t0:.0f}s")
    df = pd.DataFrame(rows).dropna(subset=["wallet", "outcome", "side"])
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    try:
        df.to_parquet(CACHE)
    except Exception:  # noqa: BLE001 -- pyarrow may be absent
        df.to_pickle(CACHE.replace(".parquet", ".pkl"))
    print(f"[build] {len(df)} trades, {df['wallet'].nunique()} wallets, "
          f"{df['market'].nunique()} markets -> cache")
    return df


SPEC_CACHE = CACHE.replace(".parquet", "_specialists.parquet")


def _load_cache(path: str = CACHE) -> pd.DataFrame:
    if os.path.exists(path):
        return pd.read_parquet(path)
    pkl = path.replace(".parquet", ".pkl")
    if os.path.exists(pkl):
        return pd.read_pickle(pkl)
    raise SystemExit(f"no cache at {path} — run the prior step first")


def _save(df: pd.DataFrame, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        df.to_parquet(path)
    except Exception:  # noqa: BLE001 -- pyarrow may be absent
        df.to_pickle(path.replace(".parquet", ".pkl"))


def build_specialists(cache_min_markets: int = 10, max_pages: int = 80) -> pd.DataFrame:
    """Market-level /trades is recency-biased (only near-resolution fills), which
    starves the entry-timing classification. Fix it where it matters: for the
    eligible cross-market specialists, pull each wallet's OWN history (which carries
    its true entry fills at the price it actually entered) and keep the fills that
    fall on our resolved universe markets. Bounded to the candidate set, so cheap."""
    from bellwether_ingestion.polymarket.data_api import DataAPIClient

    pool = _load_cache(CACHE)
    meta = {r["market"]: r for _, r in
            pool.drop_duplicates("market")[["market", "category", "slug", "resolution", "resolved_at"]].iterrows()}
    gc = pool.groupby(["wallet", "category"])["market"].nunique()
    cand = sorted(gc[gc >= cache_min_markets].index.get_level_values("wallet").unique())
    print(f"[specialists] pulling own-history for {len(cand)} candidate wallets "
          f"(>= {cache_min_markets} distinct markets), {len(meta)} universe markets")

    def _one(w: str) -> list[dict]:
        d = DataAPIClient()
        rows = []
        try:
            for t in d.iter_trades(user=w, max_pages=max_pages):
                mm = meta.get(t.conditionId)
                if mm is None or t.size is None or t.price is None:
                    continue
                rows.append({
                    "wallet": w, "market": t.conditionId, "category": mm["category"], "slug": mm["slug"],
                    "outcome": t.outcome, "side": t.side, "size": float(t.size), "price": float(t.price),
                    "notional": float(t.size) * float(t.price),
                    "ts": pd.to_datetime(t.timestamp, unit="s", utc=True),
                    "resolution": mm["resolution"], "resolved_at": pd.to_datetime(mm["resolved_at"], utc=True),
                })
        except Exception:  # noqa: BLE001
            pass
        finally:
            d.close()
        return rows

    out: list[dict] = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = [ex.submit(_one, w) for w in cand]
        for i, fu in enumerate(as_completed(futs), 1):
            out.extend(fu.result())
            if i % 50 == 0:
                print(f"  {i}/{len(cand)} wallets, {len(out)} universe fills, {time.time()-t0:.0f}s")
    df = pd.DataFrame(out).dropna(subset=["wallet", "outcome", "side"])
    _save(df, SPEC_CACHE)
    print(f"[specialists] {len(df)} fills, {df['wallet'].nunique()} wallets, "
          f"{df['market'].nunique()} markets -> specialist cache")
    return df


def report() -> None:
    from bellwether_analytics.skill import (
        SkillConfig,
        category_recon,
        null_control,
        rank_strategists,
        rank_within_type,
    )

    df = _load_cache()
    pd.set_option("display.width", 170)
    pd.set_option("display.max_columns", 25)
    print(f"\n=== REAL external-fact pool: {len(df)} trades, {df['wallet'].nunique()} wallets, "
          f"{df['market'].nunique()} resolved markets ===")
    print(f"span: {df['resolved_at'].min()} .. {df['resolved_at'].max()}\n")

    print("=== Step 0 — studyable population per category (market-level census) ===")
    cfg = SkillConfig()
    recon = category_recon(df, cfg)
    print(recon.to_string(index=False))

    # Funnel on the SPECIALIST frame (per-wallet own-history -> true entry prices).
    # Market-level /trades only returns near-resolution fills, so it can't drive the
    # entry-timing classification; the specialist cache carries real entries.
    if os.path.exists(SPEC_CACHE) or os.path.exists(SPEC_CACHE.replace(".parquet", ".pkl")):
        sub = _load_cache(SPEC_CACHE)
        print(f"\n[funnel] specialist frame: {len(sub)} fills, {sub['wallet'].nunique()} wallets "
              f"(true own-history entries)")
    else:
        gc = df.groupby(["wallet", "category"])["market"].nunique()
        cand = gc[gc >= cfg.min_markets].index.get_level_values("wallet").unique()
        sub = df[df["wallet"].isin(cand)].copy()
        print(f"\n[funnel] no specialist cache — falling back to recency-biased market-level "
              f"({len(cand)} candidates). Run `specialists` for true entries.")
    funnel = rank_strategists(sub, cfg)
    print(f"\n=== Funnel: {len(funnel)} eligible accounts (>= {cfg.min_markets} distinct "
          f"resolved markets in a category) ===")
    if not funnel.empty:
        show = funnel[["wallet", "category", "n_markets", "type", "median_entry", "persistence",
                       "skill_p", "realized_pnl", "roi", "survived", "edge_source_hint"]].copy()
        show["wallet"] = show["wallet"].str.slice(0, 12) + "…"
        print(show.head(40).to_string(index=False))

    survivors = rank_within_type(funnel)
    print(f"\n=== Ranked survivors within type: {len(survivors)} ===")
    if not survivors.empty:
        s = survivors[["type", "wallet", "category", "n_markets", "persistence", "skill_p",
                       "realized_pnl", "roi", "pnl_rank", "return_rank", "edge_source_hint"]].copy()
        s["wallet"] = s["wallet"].str.slice(0, 12) + "…"
        print(s.to_string(index=False))
        by_type = survivors.groupby("type").size().to_dict()
        print("\nsurvivors by type:", by_type)

    print("\n=== Null control (market-calibrated, no-skill) ===")
    print(null_control(sub, cfg))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    if cmd in ("build", "all"):
        build()
    if cmd in ("specialists", "all"):
        build_specialists()
    if cmd in ("report", "all"):
        report()

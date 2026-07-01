"""Seed a co-trading candidate-wallet pool for bellwether's first real run.

Rationale: cross-account detection (templates, copy-chains) only finds signal
where wallets *share the same books*. A random volume cut is too diffuse. So we
seed from (a) the high-frequency recurring crypto up/down families (the same
wallets return to consecutive 5m/15m markets) and (b) the top holders + active
traders of the N highest-volume RESOLVED markets across categories (so P&L can
score them).

This is ingestion orchestration only — it reuses the existing Data API / Gamma
clients and `load_wallet`. No new detection logic.

Usage:
  python scripts/seed_cotrading_pool.py discover   # build+persist candidate set
  python scripts/seed_cotrading_pool.py load       # load full history for the set
  python scripts/seed_cotrading_pool.py enrich      # gamma resolution for source markets
"""

from __future__ import annotations

import collections
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from bellwether_ingestion.polymarket.data_api import DataAPIClient
from bellwether_ingestion.polymarket.gamma import GammaClient
from bellwether_ingestion.polymarket.loader import run_load_wallet

STATE = os.path.join(os.path.dirname(__file__), "..", ".cache", "seed_pool.json")
STATE = os.path.abspath(STATE)

# Recurring high-frequency families we want the same wallets to return to.
UPDOWN_RE = re.compile(r"(btc|eth|sol|xrp|doge|bitcoin)[-_].*(updown|up-or-down)")

# Categories we want resolved source markets to span (matched against slug/question).
CATEGORY_HINTS = {
    "politics": ["election", "president", "senate", "governor", "primary", "trump", "biden", "mayor"],
    "sports": ["mlb", "nba", "nfl", "wnba", "fifwc", "ucl", "epl", "nhl", "vs-", "-vs-"],
    "crypto": ["bitcoin", "btc", "ethereum", "eth", "solana", "crypto", "price"],
}


_MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"


def _family(slug: str) -> str:
    s = re.sub(rf"-({_MONTHS})-\d+.*$", "", slug)
    s = re.sub(r"-\d{4}-\d{2}-\d{2}.*$", "", s)
    s = re.sub(r"-\d{9,}$", "", s)          # unix-ts suffix on updown markets
    s = re.sub(r"-\d+(am|pm)(-et)?$", "", s)
    s = re.sub(r"-\d+$", "", s)
    return s


def _unwrap(x):
    x = x["data"] if isinstance(x, dict) and "data" in x else x
    return [m for m in x if isinstance(m, dict)] if isinstance(x, list) else []


def discover(target: int = 500, n_resolved: int = 20) -> dict:
    d = DataAPIClient()
    g = GammaClient()
    wallets: dict[str, dict] = {}          # proxy -> {sources:set}
    source_conds: dict[str, dict] = {}     # conditionId -> {slug, family, kind}

    def add_wallet(proxy, source):
        if not proxy:
            return
        wallets.setdefault(proxy, {"sources": set()})["sources"].add(source)

    # --- (a) recurring crypto up/down families from the live global trade feed ---
    fam_wallets: collections.defaultdict = collections.defaultdict(set)
    scanned = 0
    for off in range(0, 12000, 500):
        try:
            batch = _unwrap(d._get("/trades", {"limit": 500, "offset": off}))
        except Exception:  # noqa: BLE001 -- API caps deep offset with a 400
            break
        if not batch:
            break
        scanned += len(batch)
        for t in batch:
            slug = t.get("slug") or t.get("eventSlug") or ""
            if UPDOWN_RE.search(slug):
                fam = _family(slug)
                proxy = t.get("proxyWallet")
                add_wallet(proxy, f"updown:{fam}")
                fam_wallets[fam].add(proxy)
                cid = t.get("conditionId")
                if cid:
                    source_conds[cid] = {"slug": slug, "family": fam, "kind": "updown"}
    print(f"[discover] scanned {scanned} recent trades; updown families: "
          + ", ".join(f"{k}={len(v)}" for k, v in sorted(fam_wallets.items(), key=lambda kv: -len(kv[1]))[:8]))

    # --- (b) top-volume RESOLVED markets across categories: holders + active traders ---
    resolved = _unwrap(g.markets(closed=True, limit=500))
    resolved = [m for m in resolved if (m.get("volumeNum") or 0) > 0 and m.get("conditionId")]
    resolved.sort(key=lambda m: m.get("volumeNum") or 0, reverse=True)

    picked: list[dict] = []
    per_cat: collections.Counter = collections.Counter()
    cap_per_cat = max(3, n_resolved // 2)
    for m in resolved:
        text = ((m.get("slug") or "") + " " + (m.get("question") or "")).lower()
        cat = next((c for c, kws in CATEGORY_HINTS.items() if any(k in text for k in kws)), "other")
        if per_cat[cat] >= cap_per_cat:
            continue
        per_cat[cat] += 1
        picked.append(m)
        if len(picked) >= n_resolved:
            break
    print(f"[discover] picked {len(picked)} resolved source markets by category: {dict(per_cat)}")

    for m in picked:
        cid = m["conditionId"]
        source_conds[cid] = {"slug": m.get("slug"), "family": _family(m.get("slug") or ""),
                             "kind": "resolved", "volume": m.get("volumeNum")}
        # top holders (per outcome token)
        try:
            for tok in d.holders(cid, limit=100):
                for h in (tok.get("holders") or []):
                    add_wallet(h.get("proxyWallet"), f"holder:{m.get('slug')}")
        except Exception as e:  # noqa: BLE001
            print(f"  holders fail {cid[:12]}: {e}")
        # active non-holders via market-level trades
        try:
            for t in _unwrap(d._get("/trades", {"market": cid, "limit": 500})):
                add_wallet(t.get("proxyWallet"), f"trader:{m.get('slug')}")
        except Exception as e:  # noqa: BLE001
            print(f"  trades fail {cid[:12]}: {e}")

    out = {
        "wallets": {w: sorted(meta["sources"])[:6] for w, meta in wallets.items()},
        "source_conds": source_conds,
        "n_wallets": len(wallets),
        "target": target,
    }
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w") as f:
        json.dump(out, f)
    print(f"[discover] UNION distinct wallets = {len(wallets)} (target {target}); "
          f"source markets = {len(source_conds)} -> {STATE}")
    return out


def load(max_workers: int = 8, limit: int | None = None) -> None:
    with open(STATE) as f:
        st = json.load(f)
    addrs = list(st["wallets"])
    if limit:
        addrs = addrs[:limit]
    print(f"[load] loading full history for {len(addrs)} wallets, {max_workers} workers")
    t0 = time.time()
    done = fail = tot_tr = tot_ev = 0

    def _one(a):
        # max_markets=0 -> stub markets keyed by conditionId (fast); enrich() adds
        # resolution metadata to the source markets afterwards.
        return a, run_load_wallet(a, max_markets=0, max_trade_pages=200, max_activity_pages=50)

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = [ex.submit(_one, a) for a in addrs]
        for fu in as_completed(futs):
            try:
                a, (ntr, nev) = fu.result()
                tot_tr += ntr
                tot_ev += nev
                done += 1
            except Exception as e:  # noqa: BLE001
                fail += 1
                if fail <= 10:
                    print(f"  load fail: {e}")
            if (done + fail) % 25 == 0:
                print(f"  {done+fail}/{len(addrs)}  ok={done} fail={fail} "
                      f"trades={tot_tr} events={tot_ev}  {time.time()-t0:.0f}s")
    print(f"[load] DONE ok={done} fail={fail} trades={tot_tr} events={tot_ev} in {time.time()-t0:.0f}s")


def enrich() -> None:
    """Give the source markets full Gamma metadata (resolution) so P&L can score."""
    import asyncio

    from bellwether_ingestion.db import make_engine, make_sessionmaker, repo
    from bellwether_ingestion.polymarket.categorize import gamma_market_fields

    with open(STATE) as f:
        st = json.load(f)
    conds = list(st["source_conds"])
    g = GammaClient()
    eng = make_engine()
    Session = make_sessionmaker(eng)

    async def _go():
        n = 0
        async with Session() as s:
            for cid in conds:
                try:
                    gm = g.market_by_condition(cid)
                    if gm:
                        await repo.upsert_market(s, "polymarket", gamma_market_fields(gm))
                        n += 1
                except Exception as e:  # noqa: BLE001
                    print(f"  enrich fail {cid[:12]}: {e}")
            await s.commit()
        await eng.dispose()
        print(f"[enrich] refreshed {n}/{len(conds)} source markets with Gamma metadata")

    asyncio.run(_go())


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "discover"
    if cmd == "discover":
        discover()
    elif cmd == "load":
        lim = int(sys.argv[2]) if len(sys.argv) > 2 else None
        load(limit=lim)
    elif cmd == "enrich":
        enrich()
    else:
        print(__doc__)

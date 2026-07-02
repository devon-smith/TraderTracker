"""Stage B: build the external-fact specialist candidate pool.

From the recon market set (.cache/factmarkets.json), pull each market's top holders
and active traders, and find accounts that RECUR across many fact markets in a
category (the specialist signal). Load full REST history for those candidates so the
funnel can compute per-account distinct-resolved-market counts, P&L, and skill.

Reuses DataAPIClient + run_load_wallet. No new detection logic.

Usage: python scripts/factpool_build.py [min_seed_markets]   # default 3
"""

from __future__ import annotations

import collections
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from bellwether_ingestion.polymarket.data_api import DataAPIClient
from bellwether_ingestion.polymarket.loader import run_load_wallet

STATE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".cache", "factmarkets.json"))
POOL = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".cache", "factpool.json"))


def _unwrap(x):
    x = x["data"] if isinstance(x, dict) and "data" in x else x
    return [m for m in x if isinstance(m, dict)] if isinstance(x, list) else []


def main() -> None:
    min_seed = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    markets = json.load(open(STATE))
    d = DataAPIClient()

    # account -> category -> set(conditionId) of SEED markets they participated in
    acct: dict[str, dict[str, set]] = collections.defaultdict(lambda: collections.defaultdict(set))

    def note(proxy, cat, cid):
        if proxy:
            acct[proxy][cat].add(cid)

    t0 = time.time()
    for i, m in enumerate(markets):
        cid, cat = m["conditionId"], m["category"]
        try:
            for tok in d.holders(cid, limit=100):
                for h in (tok.get("holders") or []):
                    note(h.get("proxyWallet"), cat, cid)
        except Exception:  # noqa: BLE001
            pass
        try:
            for t in _unwrap(d._get("/trades", {"market": cid, "limit": 500})):
                note(t.get("proxyWallet"), cat, cid)
        except Exception:  # noqa: BLE001
            pass
        if (i + 1) % 50 == 0:
            print(f"  pulled {i+1}/{len(markets)} markets, {len(acct)} accounts, {time.time()-t0:.0f}s")

    # candidate = appears in >= min_seed distinct seed markets in ANY single category
    candidates = {}
    for a, cats in acct.items():
        best_cat, best_n = max(((c, len(s)) for c, s in cats.items()), key=lambda x: x[1])
        if best_n >= min_seed:
            candidates[a] = {"top_category": best_cat, "seed_markets": best_n,
                             "by_cat": {c: len(s) for c, s in cats.items()}}
    print(f"[build] {len(acct)} total accounts; {len(candidates)} recur in >= {min_seed} seed markets")
    by_top = collections.Counter(v["top_category"] for v in candidates.values())
    print(f"[build] candidate specialists by top category: {dict(by_top)}")

    with open(POOL, "w") as fh:
        json.dump({"min_seed": min_seed, "candidates": candidates}, fh)

    # load full history for candidates
    addrs = list(candidates)
    print(f"[build] loading full history for {len(addrs)} candidates...")
    done = fail = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(run_load_wallet, a, max_markets=0) for a in addrs]
        for fu in as_completed(futs):
            try:
                fu.result()
                done += 1
            except Exception:  # noqa: BLE001
                fail += 1
            if (done + fail) % 50 == 0:
                print(f"  loaded {done+fail}/{len(addrs)} ok={done} fail={fail}")
    print(f"[build] DONE loaded ok={done} fail={fail} -> {POOL}")


if __name__ == "__main__":
    main()

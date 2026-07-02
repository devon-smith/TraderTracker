"""Enrich resolution on the fact-pool candidates' non-updown markets via CLOB.

Gamma won't serve older markets by conditionId, but the CLOB market endpoint
returns the winning outcome for any conditionId. For every non-updown market a
candidate traded that still lacks a resolution, fetch CLOB, take the winning
outcome + settle time, and bulk-update. Category is derived from slug in the
funnel, so we only stamp resolution/resolved_at here.
"""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
from bellwether_analytics.core.queries import sync_dsn
from sqlalchemy import create_engine, text

POOL = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".cache", "factpool.json"))
CLOB = "https://clob.polymarket.com"


def _targets(eng, cands):
    with eng.connect() as c:
        rows = c.execute(text(
            "SELECT DISTINCT m.id, m.external_id FROM market m "
            "JOIN trade t ON t.market_id = m.id JOIN wallet w ON w.id = t.wallet_id "
            "WHERE w.external_id = ANY(:cands) AND m.resolution IS NULL "
            "AND m.slug NOT LIKE '%updown%' AND m.slug NOT LIKE '%up-or-down%'"
        ), {"cands": cands}).all()
    return rows


def main() -> None:
    cands = list(json.load(open(POOL))["candidates"])
    eng = create_engine(sync_dsn(None))
    targets = _targets(eng, cands)
    print(f"[enrich] {len(targets)} non-updown markets to resolve via CLOB")

    client = httpx.Client(timeout=20, headers={"User-Agent": "bellwether/0.2"},
                          limits=httpx.Limits(max_connections=20))
    _RETRY = {429, 500, 502, 503, 504}

    def fetch(row):
        """Returns (mid, outcome, end_iso) if resolved; ('open', ) style sentinels
        otherwise. Retries transient throttling/errors so we don't silently drop a
        resolvable market (the bug that made the first enrich under-resolve)."""
        mid, cid = row
        for attempt in range(5):
            try:
                r = client.get(f"{CLOB}/markets/{cid}")
                if r.status_code in _RETRY:
                    time.sleep(min(2 ** attempt * 0.4, 8.0))
                    continue
                if r.status_code != 200:
                    return ("skip", mid)  # 404/etc — genuinely not on CLOB
                j = r.json()
                if not j.get("closed"):
                    return ("open", mid)
                for tok in j.get("tokens", []):
                    if tok.get("winner"):
                        return (mid, tok.get("outcome"), j.get("end_date_iso"))
                return ("no_winner", mid)
            except Exception:  # noqa: BLE001 -- transient; retry
                time.sleep(min(2 ** attempt * 0.4, 8.0))
        return ("fail", mid)  # exhausted retries

    results = []
    stats = {"open": 0, "no_winner": 0, "skip": 0, "fail": 0}
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=10) as ex:
        for i, res in enumerate(ex.map(fetch, targets)):
            if res and len(res) == 3:
                results.append(res)
            elif res:
                stats[res[0]] = stats.get(res[0], 0) + 1
            if (i + 1) % 5000 == 0:
                print(f"  {i+1}/{len(targets)} resolved={len(results)} "
                      f"open={stats['open']} fail={stats['fail']} {time.time()-t0:.0f}s")
    print(f"[enrich] fetch done: resolved={len(results)} open={stats['open']} "
          f"no_winner={stats['no_winner']} skip={stats['skip']} fail={stats['fail']}")

    with eng.begin() as c:
        c.execute(text("CREATE TEMP TABLE _r (id bigint PRIMARY KEY, res text, end_iso text) ON COMMIT DROP"))
        for i in range(0, len(results), 5000):
            chunk = results[i:i + 5000]
            c.execute(text("INSERT INTO _r VALUES (:id,:r,:e) ON CONFLICT DO NOTHING"),
                      [{"id": m, "r": o, "e": e or ""} for m, o, e in chunk])
        c.execute(text(
            "UPDATE market m SET resolution = _r.res, "
            "resolved_at = COALESCE(m.resolved_at, CAST(NULLIF(_r.end_iso,'') AS timestamptz), now()) "
            "FROM _r WHERE m.id = _r.id AND m.resolution IS NULL"
        ))
    eng.dispose()
    print(f"[enrich] resolved {len(results)}/{len(targets)} markets in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()

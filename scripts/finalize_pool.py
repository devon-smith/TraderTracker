"""Finalize the seed co-trading pool:

  reseed  — add active holders/traders of RECENT resolved (Gamma-indexed) markets
            as fresh candidate wallets, and upsert those markets WITH resolution.
  prune   — delete zero-trade shell wallets (the stale 2020-21 holders).
  clob    — bounded resolution backfill: for the top-N most-traded markets, fetch
            the winning outcome from the CLOB API and set market.resolution.

Ingestion orchestration only — reuses the existing clients / loader / repo.
"""

from __future__ import annotations

import asyncio
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import httpx
from bellwether_ingestion.db import make_engine, make_sessionmaker, repo
from bellwether_ingestion.polymarket.categorize import gamma_market_fields
from bellwether_ingestion.polymarket.data_api import DataAPIClient
from bellwether_ingestion.polymarket.gamma import GammaClient
from bellwether_ingestion.polymarket.loader import run_load_wallet
from sqlalchemy import text

CLOB = "https://clob.polymarket.com"


def _unwrap(x):
    x = x["data"] if isinstance(x, dict) and "data" in x else x
    return [m for m in x if isinstance(m, dict)] if isinstance(x, list) else []


def reseed(n_markets: int = 40) -> None:
    """Recent CLOSED Gamma markets with a decisive outcome -> resolved anchors;
    pull their holders + active traders as fresh candidate wallets and load them."""
    g, d = GammaClient(), DataAPIClient()
    eng = make_engine()
    Session = make_sessionmaker(eng)

    # Recent closed markets that actually carry a decisive resolution.
    mk = _unwrap(g.markets(closed=True, limit=500))
    resolved = []
    for m in mk:
        f = gamma_market_fields(m)
        if f["resolution"] is not None and (m.get("volumeNum") or 0) > 20000:
            resolved.append((m, f))
    resolved.sort(key=lambda mf: -(mf[0].get("volumeNum") or 0))
    resolved = resolved[:n_markets]
    print(f"[reseed] {len(resolved)} recent resolved anchors with decisive outcome")

    wallets: set[str] = set()

    async def _upsert_markets():
        async with Session() as s:
            for _, f in resolved:
                await repo.upsert_market(s, "polymarket", f)
            await s.commit()
    asyncio.run(_upsert_markets())

    for m, _ in resolved:
        cid = m["conditionId"]
        try:
            for tok in d.holders(cid, limit=100):
                for h in (tok.get("holders") or []):
                    if h.get("proxyWallet"):
                        wallets.add(h["proxyWallet"])
        except Exception:  # noqa: BLE001
            pass
        try:
            for t in _unwrap(d._get("/trades", {"market": cid, "limit": 500})):
                if t.get("proxyWallet"):
                    wallets.add(t["proxyWallet"])
        except Exception:  # noqa: BLE001
            pass
    print(f"[reseed] {len(wallets)} candidate wallets from resolved anchors; loading...")

    asyncio.run(eng.dispose())
    done = fail = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(run_load_wallet, a, max_markets=0) for a in wallets]
        for fu in as_completed(futs):
            try:
                fu.result()
                done += 1
            except Exception:  # noqa: BLE001
                fail += 1
    print(f"[reseed] loaded ok={done} fail={fail}")


def prune() -> None:
    eng = make_engine()

    async def _go():
        async with eng.connect() as c:
            shell = ("SELECT id FROM wallet w WHERE NOT EXISTS "
                     "(SELECT 1 FROM trade t WHERE t.wallet_id = w.id)")
            # clear the FK-referencing position_events first (holders' REDEEM rows
            # with no trades), then the shell wallets themselves.
            ev = await c.execute(text(f"DELETE FROM position_event WHERE wallet_id IN ({shell})"))
            res = await c.execute(text(f"DELETE FROM wallet WHERE id IN ({shell})"))
            await c.commit()
            print(f"[prune] deleted {res.rowcount} zero-trade shell wallets "
                  f"(+{ev.rowcount} orphan position_events)")
        await eng.dispose()
    asyncio.run(_go())


def clob(top_n: int = 3000, workers: int = 16) -> None:
    async def _targets():
        eng = make_engine()
        async with eng.connect() as c:
            rows = (await c.execute(text(
                "SELECT m.id, m.external_id FROM market m "
                "JOIN trade t ON t.market_id = m.id "
                "WHERE m.resolution IS NULL "
                "GROUP BY m.id, m.external_id ORDER BY count(*) DESC LIMIT :n"
            ), {"n": top_n})).all()
        await eng.dispose()
        return rows
    targets = asyncio.run(_targets())
    print(f"[clob] resolving top {len(targets)} traded markets via CLOB")

    client = httpx.Client(timeout=15, headers={"User-Agent": "bellwether/0.2"})

    def _fetch(mid_cid):
        mid, cid = mid_cid
        try:
            r = client.get(f"{CLOB}/markets/{cid}")
            if r.status_code != 200:
                return None
            j = r.json()
            if not j.get("closed"):
                return None
            for tok in j.get("tokens", []):
                if tok.get("winner"):
                    return (mid, tok.get("outcome"), j.get("end_date_iso"))
        except Exception:  # noqa: BLE001
            return None
        return None

    results = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, res in enumerate(ex.map(_fetch, targets)):
            if res:
                results.append(res)
            if (i + 1) % 500 == 0:
                print(f"  {i+1}/{len(targets)} resolved={len(results)} {time.time()-t0:.0f}s")

    async def _apply():
        eng = make_engine()
        async with eng.connect() as c:
            for mid, outcome, end_iso in results:
                await c.execute(text(
                    "UPDATE market SET resolution = :r, "
                    "resolved_at = COALESCE(resolved_at, CAST(NULLIF(:e, '') AS timestamptz), now()) "
                    "WHERE id = :id AND resolution IS NULL"
                ), {"r": outcome, "e": end_iso or "", "id": mid})
            await c.commit()
        await eng.dispose()
    asyncio.run(_apply())
    print(f"[clob] set resolution on {len(results)} markets in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "reseed":
        reseed()
    elif cmd == "prune":
        prune()
    elif cmd == "clob":
        clob(int(sys.argv[2]) if len(sys.argv) > 2 else 3000)
    else:
        print(__doc__)

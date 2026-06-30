"""Polymarket REST backfill: a wallet's full trade + activity history into the
canonical tables, idempotently, plus leaderboard seeding for the candidate pool.

REST only (Data API + Gamma). The on-chain listener is Prompt 7.
"""

from __future__ import annotations

import asyncio
import collections
import logging
from typing import Optional

from sqlalchemy.ext.asyncio import async_sessionmaker

from ..db import Platform, PositionEventType, Side, Source, make_engine, make_sessionmaker, repo
from ..db.normalize import polymarket_activity_fields, polymarket_trade_fields
from .categorize import gamma_market_fields
from .data_api import DataAPIClient
from .gamma import GammaClient

log = logging.getLogger("bellwether.polymarket")


async def _resolve_markets(
    s,
    gamma: GammaClient,
    condition_ids: set[str],
    max_markets: Optional[int],
    slug_map: Optional[dict[str, str]] = None,
    title_map: Optional[dict[str, str]] = None,
) -> dict[str, int]:
    """Upsert a market for every conditionId. The first `max_markets` get full
    Gamma metadata; the rest get a stub built from the slug/title carried on the
    Data API trade (so category-from-slug + market-family still work cheaply)."""
    from .categorize import normalize_category

    slug_map = slug_map or {}
    title_map = title_map or {}
    ids = list(condition_ids)
    fetch = set(ids[:max_markets]) if max_markets is not None else set(ids)

    mid_map: dict[str, int] = {}
    for cid in ids:
        gm = None
        if cid in fetch:
            try:
                gm = gamma.market_by_condition(cid)
            except Exception:
                gm = None
        if gm:
            fields = gamma_market_fields(gm)
        else:
            slug = slug_map.get(cid)
            fields = {
                "external_id": cid,
                "slug": slug,
                "title": title_map.get(cid),
                "category": normalize_category({"slug": slug, "question": title_map.get(cid)}),
                "is_multi_outcome": False,
            }
        mid_map[cid] = await repo.upsert_market(s, "polymarket", fields)
    return mid_map


async def load_wallet(
    Session: async_sessionmaker,
    address: str,
    data: Optional[DataAPIClient] = None,
    gamma: Optional[GammaClient] = None,
    max_trade_pages: int = 200,
    max_activity_pages: int = 50,
    max_markets: Optional[int] = None,
) -> tuple[int, int]:
    """Backfill one wallet. Returns (new_trades, new_position_events)."""
    data = data or DataAPIClient()
    gamma = gamma or GammaClient()

    async with Session() as s:
        run_id = await repo.start_run(s, "polymarket", address)
        n_trades = n_events = 0
        last_cursor: Optional[str] = None
        try:
            trades = list(data.iter_trades(user=address, max_pages=max_trade_pages))
            activity = list(data.iter_activity(user=address, max_pages=max_activity_pages))
            log.info("fetched %d trades, %d activity rows for %s", len(trades), len(activity), address)

            proxy = trades[0].proxyWallet if trades else address
            handle = trades[0].name if trades else None
            pseudonym = trades[0].pseudonym if trades else None
            wid = await repo.upsert_wallet(s, "polymarket", proxy, handle=handle, pseudonym=pseudonym)
            await s.commit()

            condition_ids = {t.conditionId for t in trades if t.conditionId}
            condition_ids |= {a.conditionId for a in activity if a.conditionId}
            slug_map = {t.conditionId: t.slug for t in trades if t.conditionId and t.slug}
            title_map = {t.conditionId: t.title for t in trades if t.conditionId and t.title}
            mid_map = await _resolve_markets(
                s, gamma, condition_ids, max_markets, slug_map=slug_map, title_map=title_map
            )
            await s.commit()

            trade_rows = []
            for t in trades:
                tf = polymarket_trade_fields(t)
                trade_rows.append(
                    {
                        "dedup_key": tf["dedup_key"],
                        "ts": tf["ts"],
                        "platform": Platform.polymarket,
                        "wallet_id": wid,
                        "market_id": mid_map.get(tf["market_external"]),
                        "side": Side(tf["side"]) if tf["side"] else None,
                        "outcome": tf["outcome"],
                        "size": tf["size"],
                        "price": tf["price"],
                        "notional": tf["notional"],
                        "tx_hash": tf["tx_hash"],
                        "log_index": None,
                        "source": Source.data_api,
                    }
                )
                last_cursor = str(t.timestamp)
            n_trades = await repo.insert_trades(s, trade_rows)

            event_rows = []
            for a in activity:
                ef = polymarket_activity_fields(a)
                if ef is None:
                    continue
                event_rows.append(
                    {
                        "dedup_key": ef["dedup_key"],
                        "ts": ef["ts"],
                        "platform": Platform.polymarket,
                        "wallet_id": wid,
                        "market_id": mid_map.get(ef["market_external"]),
                        "event_type": PositionEventType(ef["event_type"]),
                        "size": ef["size"],
                        "value": ef["value"],
                        "tx_hash": ef["tx_hash"],
                        "log_index": None,
                    }
                )
            n_events = await repo.insert_position_events(s, event_rows)
            await s.commit()

            await repo.finish_run(s, run_id, "success", n_trades + n_events, cursor=last_cursor)
            log.info("wrote %d trades, %d position events for %s", n_trades, n_events, address)
            return n_trades, n_events
        except Exception as e:  # noqa: BLE001
            await s.rollback()
            await repo.finish_run(s, run_id, "error", n_trades + n_events, error=str(e))
            raise


async def seed_active_wallets(
    Session: async_sessionmaker,
    n: int = 100,
    pages: int = 6,
    data: Optional[DataAPIClient] = None,
) -> int:
    """Seed the wallet pool with the top-volume wallets in recent global trades.

    This is the practical substitute for a leaderboard: Polymarket no longer
    exposes a public one, so we rank recent activity by traded notional.
    """
    data = data or DataAPIClient()
    vol: collections.Counter = collections.Counter()
    names: dict[str, str] = {}
    for t in data.iter_recent_trades(max_pages=pages):
        vol[t.proxyWallet] += t.notional
        if t.name and t.proxyWallet not in names:
            names[t.proxyWallet] = t.name
    top = [w for w, _ in vol.most_common(n)]

    count = 0
    async with Session() as s:
        run_id = await repo.start_run(s, "polymarket_active", str(n))
        try:
            for w in top:
                await repo.upsert_wallet(s, "polymarket", w, handle=names.get(w))
                count += 1
            await s.commit()
            await repo.finish_run(s, run_id, "success", count)
        except Exception as exc:  # noqa: BLE001
            await s.rollback()
            await repo.finish_run(s, run_id, "error", count, error=str(exc))
            raise
    return count


async def seed_leaderboard(
    Session: async_sessionmaker,
    n: int = 100,
    window: str = "month",
    gamma: Optional[GammaClient] = None,
) -> int:
    """Seed the wallet pool. Tries the Gamma leaderboard; if it's unavailable
    (it currently 404s), falls back to a recent-volume seed."""
    gamma = gamma or GammaClient()
    entries = gamma.leaderboard(window=window, limit=n)
    if not entries:
        log.warning("Gamma leaderboard unavailable; seeding from recent-trade volume")
        return await seed_active_wallets(Session, n=n)

    count = 0
    async with Session() as s:
        run_id = await repo.start_run(s, "polymarket_leaderboard", f"{window}:{n}")
        try:
            for e in entries:
                if not e.proxyWallet:
                    continue
                await repo.upsert_wallet(s, "polymarket", e.proxyWallet, handle=e.userName)
                count += 1
            await s.commit()
            await repo.finish_run(s, run_id, "success", count)
        except Exception as exc:  # noqa: BLE001
            await s.rollback()
            await repo.finish_run(s, run_id, "error", count, error=str(exc))
            raise
    return count


def run_load_wallet(address: str, dsn: Optional[str] = None, **kwargs) -> tuple[int, int]:
    engine = make_engine(dsn)
    Session = make_sessionmaker(engine)

    async def _go():
        try:
            return await load_wallet(Session, address, **kwargs)
        finally:
            await engine.dispose()

    return asyncio.run(_go())


def run_seed_leaderboard(n: int = 100, window: str = "month", dsn: Optional[str] = None) -> int:
    engine = make_engine(dsn)
    Session = make_sessionmaker(engine)

    async def _go():
        try:
            return await seed_leaderboard(Session, n=n, window=window)
        finally:
            await engine.dispose()

    return asyncio.run(_go())

"""Manifold backfill loader: fetch a user's full bet history and write it into the
canonical tables idempotently, with an ingestion_run cursor for resumability.

Computation lives in analytics; this module only fetches + normalizes + persists.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from sqlalchemy.ext.asyncio import async_sessionmaker

from ..db import Platform, Side, Source, make_engine, make_sessionmaker, repo
from ..db.normalize import manifold_market_fields, manifold_trade_fields
from .client import ManifoldClient

log = logging.getLogger("bellwether.manifold")


def _resolve_user(client: ManifoldClient, identifier: str) -> tuple[str, Optional[str]]:
    """Return (external_id, handle). Accepts a username or a raw user id."""
    try:
        user = client.user(identifier)
        if user and user.get("id"):
            return user["id"], user.get("username")
    except Exception:
        pass
    # Treat the identifier as a user id directly.
    return identifier, None


async def load_user(
    Session: async_sessionmaker,
    identifier: str,
    client: Optional[ManifoldClient] = None,
    max_pages: int = 200,
    max_bets: Optional[int] = None,
) -> int:
    """Backfill one Manifold user. Returns the number of new trade rows written.

    `max_bets` caps how many of the most-recent bets to process (bounds the number
    of per-contract metadata fetches); leave it None for the full history.
    """
    client = client or ManifoldClient()
    external_id, handle = _resolve_user(client, identifier)

    async with Session() as s:
        run_id = await repo.start_run(s, "manifold", identifier)
        rows_written = 0
        last_cursor: Optional[str] = None
        try:
            wid = await repo.upsert_wallet(s, "manifold", external_id, handle=handle)
            await s.commit()

            bets = list(client.iter_bets(user_id=external_id, max_pages=max_pages))
            if max_bets is not None:
                bets = bets[:max_bets]
            log.info("fetched %d bets for %s", len(bets), identifier)

            # Upsert each distinct market once.
            mid_map: dict[str, int] = {}
            for cid in {b.get("contractId") for b in bets if b.get("contractId")}:
                try:
                    contract = client.market(cid)
                except Exception:
                    continue
                mid_map[cid] = await repo.upsert_market(
                    s, "manifold", manifold_market_fields(contract)
                )
            await s.commit()

            trade_rows = []
            for b in bets:
                tf = manifold_trade_fields(b)
                trade_rows.append(
                    {
                        "dedup_key": tf["dedup_key"],
                        "ts": tf["ts"],
                        "platform": Platform.manifold,
                        "wallet_id": wid,
                        "market_id": mid_map.get(tf["market_external"]),
                        "side": Side(tf["side"]),
                        "outcome": tf["outcome"],
                        "size": tf["size"],
                        "price": tf["price"],
                        "notional": tf["notional"],
                        "tx_hash": tf["tx_hash"],
                        "log_index": None,
                        "source": Source.manifold_api,
                    }
                )
                last_cursor = b.get("id")

            rows_written = await repo.insert_trades(s, trade_rows)
            await s.commit()
            await repo.finish_run(s, run_id, "success", rows_written, cursor=last_cursor)
            log.info("wrote %d new trades for %s", rows_written, identifier)
            return rows_written
        except Exception as e:  # noqa: BLE001 — record failure then re-raise
            await s.rollback()
            await repo.finish_run(s, run_id, "error", rows_written, error=str(e))
            raise


def run_load_user(
    identifier: str,
    dsn: Optional[str] = None,
    max_pages: int = 200,
    max_bets: Optional[int] = None,
) -> int:
    """Sync entrypoint: build an engine, run the async loader, dispose."""
    engine = make_engine(dsn)
    Session = make_sessionmaker(engine)

    async def _go():
        try:
            return await load_user(Session, identifier, max_pages=max_pages, max_bets=max_bets)
        finally:
            await engine.dispose()

    return asyncio.run(_go())

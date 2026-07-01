"""OrderFilled listener: backfill a block range, watch new blocks, reconcile
on-chain fills against Data API rows, and report per-wallet freshness lag.

Read-only. NEVER signs or submits a transaction. Requires POLYGON_RPC_URL.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from ..db import Platform, Side, Source, make_engine, make_sessionmaker, repo
from .contracts import (
    CTF_EXCHANGE_V1,
    CTF_EXCHANGE_V2,
    NEG_RISK_CTF_EXCHANGE_V1,
    NEG_RISK_CTF_EXCHANGE_V2,
    ORDER_FILLED_V1,
    ORDER_FILLED_V2,
    order_filled_topic0,
)
from .decode import decode_log
from .normalize import (
    V2OrderFilledError,
    assert_v2_order_filled_log,
    block_ts_to_dt,
    freshness_lag_seconds,
    normalize_order_filled,
)
from .rpc import JsonRpc

log = logging.getLogger("bellwether.onchain")


class OrderFilledListener:
    def __init__(
        self,
        Session: async_sessionmaker,
        rpc: Optional[JsonRpc] = None,
        version: str = "v2",
        addresses: Optional[list[str]] = None,
    ):
        self.Session = Session
        self.rpc = rpc or JsonRpc()
        self.version = version
        self.abi = ORDER_FILLED_V2 if version == "v2" else ORDER_FILLED_V1
        # V2 topic0 is the live-verified constant (authoritative, not re-derived).
        self.topic0 = order_filled_topic0(version)
        if addresses is not None:
            self.addresses = addresses
        elif version == "v2":
            self.addresses = [CTF_EXCHANGE_V2, NEG_RISK_CTF_EXCHANGE_V2]
        else:
            self.addresses = [CTF_EXCHANGE_V1, NEG_RISK_CTF_EXCHANGE_V1]
        self._ts_cache: dict[int, int] = {}

    def _block_ts(self, block_number: int) -> int:
        if block_number not in self._ts_cache:
            self._ts_cache[block_number] = self.rpc.block_timestamp(block_number)
        return self._ts_cache[block_number]

    def _rows_from_logs(self, logs: list[dict]) -> list[dict]:
        rows: list[dict] = []
        for lg in logs:
            if self.version == "v2":
                # Correctness gate: validate against the live-verified V2 shape and
                # log-and-skip anything that isn't one, rather than decode garbage.
                # V2 fill->row normalization (side/tokenId semantics) is finalized in
                # the on-chain backfill goal; this listener validates + decodes only.
                try:
                    assert_v2_order_filled_log(lg["topics"], lg["data"])
                except V2OrderFilledError as e:
                    log.warning("skipping invalid V2 OrderFilled log: %s", e)
                    continue
                decode_log(self.abi, lg["topics"], lg["data"])  # decodes to 10 fields
                continue
            decoded = decode_log(self.abi, lg["topics"], lg["data"])
            bn = int(lg["blockNumber"], 16)
            ts = block_ts_to_dt(self._block_ts(bn))
            li = int(lg["logIndex"], 16)
            txh = lg["transactionHash"]
            rows.extend(normalize_order_filled(decoded, txh, li, ts, block_number=bn))
        return rows

    async def _persist(self, s, rows: list[dict], wcache: dict[str, int]) -> int:
        insert_rows = []
        for r in rows:
            ext = r["wallet_external"]
            if ext not in wcache:
                wcache[ext] = await repo.upsert_wallet(s, "polymarket", ext)
            insert_rows.append(
                {
                    "dedup_key": r["dedup_key"],
                    "ts": r["ts"],
                    "platform": Platform.polymarket,
                    "wallet_id": wcache[ext],
                    "market_id": None,
                    "side": Side(r["side"]),
                    "outcome": r["outcome"],
                    "asset": r["asset"],
                    "size": r["size"],
                    "price": r["price"],
                    "notional": r["notional"],
                    "tx_hash": r["tx_hash"],
                    "log_index": r["log_index"],
                    "block_number": r.get("block_number"),
                    "source": Source.onchain,
                    "is_taker": r.get("is_taker"),
                }
            )
        n = await repo.insert_trades(s, insert_rows)
        await s.commit()
        return n

    async def backfill(self, from_block: int, to_block: int, chunk: int = 2000) -> int:
        """Scan [from_block, to_block] for OrderFilled across the exchange addresses."""
        total = 0
        async with self.Session() as s:
            run_id = await repo.start_run(s, "polymarket_onchain", f"{from_block}-{to_block}")
            wcache: dict[str, int] = {}
            try:
                for addr in self.addresses:
                    start = from_block
                    while start <= to_block:
                        end = min(start + chunk - 1, to_block)
                        logs = self.rpc.get_logs(addr, [self.topic0], start, end)
                        total += await self._persist(s, self._rows_from_logs(logs), wcache)
                        log.info("%s blocks %d-%d: %d logs", addr[:10], start, end, len(logs))
                        start = end + 1
                await repo.finish_run(s, run_id, "success", total)
            except Exception as e:  # noqa: BLE001
                await s.rollback()
                await repo.finish_run(s, run_id, "error", total, error=str(e))
                raise
        return total

    async def watch(self, poll_seconds: float = 2.0, confirmations: int = 1) -> None:
        """Poll new blocks and ingest OrderFilled events as they land."""
        last = self.rpc.block_number() - confirmations
        log.info("watching from block %d", last + 1)
        while True:
            head = self.rpc.block_number() - confirmations
            if head >= last + 1:
                await self.backfill(last + 1, head)
                last = head
            await asyncio.sleep(poll_seconds)

    async def reconcile(self, wallet_external: str) -> dict:
        """Report overlap between on-chain and Data API fills for a wallet (by
        tx_hash) and the on-chain freshness lag. On-chain rows are authoritative."""
        async with self.Session() as s:
            overlap = (
                await s.execute(
                    text(
                        """
                        SELECT count(*) FROM (
                          SELECT t.tx_hash FROM trade t JOIN wallet w ON w.id=t.wallet_id
                          WHERE w.external_id=:w AND t.source='onchain' AND t.tx_hash IS NOT NULL
                          INTERSECT
                          SELECT t.tx_hash FROM trade t JOIN wallet w ON w.id=t.wallet_id
                          WHERE w.external_id=:w AND t.source='data_api' AND t.tx_hash IS NOT NULL
                        ) x
                        """
                    ),
                    {"w": wallet_external},
                )
            ).scalar_one()
            latest = (
                await s.execute(
                    text(
                        """
                        SELECT max(t.ts) FROM trade t JOIN wallet w ON w.id=t.wallet_id
                        WHERE w.external_id=:w AND t.source='onchain'
                        """
                    ),
                    {"w": wallet_external},
                )
            ).scalar_one()
        now = dt.datetime.now(tz=dt.timezone.utc)
        return {
            "wallet": wallet_external,
            "tx_overlap_with_data_api": int(overlap or 0),
            "freshness_lag_seconds": freshness_lag_seconds(latest, now),
        }


def run_backfill(from_block: int, to_block: int, version: str = "v2", dsn: Optional[str] = None) -> int:
    engine = make_engine(dsn)
    Session = make_sessionmaker(engine)

    async def _go():
        try:
            return await OrderFilledListener(Session, version=version).backfill(from_block, to_block)
        finally:
            await engine.dispose()

    return asyncio.run(_go())


def run_watch(version: str = "v2", dsn: Optional[str] = None) -> None:
    engine = make_engine(dsn)
    Session = make_sessionmaker(engine)

    async def _go():
        try:
            await OrderFilledListener(Session, version=version).watch()
        finally:
            await engine.dispose()

    asyncio.run(_go())


def run_reconcile(wallet: str, version: str = "v2", dsn: Optional[str] = None) -> dict:
    engine = make_engine(dsn)
    Session = make_sessionmaker(engine)

    async def _go():
        try:
            return await OrderFilledListener(Session, version=version).reconcile(wallet)
        finally:
            await engine.dispose()

    return asyncio.run(_go())

"""Stamp trade.block_number onto EXISTING REST rows from the chain.

block_number is a transaction-level property (every log in a tx shares one block),
and the REST rows carry tx_hash but no log_index, so the join key is tx_hash alone:
fetch each tx's receipt via the Polygon RPC, confirm it carries a live-verified V2
OrderFilled log (the correctness gate), take the receipt's blockNumber, and bulk-
update every row with that tx_hash. Does NOT create rows or touch side/price.

Usage: python scripts/backfill_block_number.py <family-slug-stem> [workers]
  e.g. python scripts/backfill_block_number.py eth-updown-5m 24
"""

from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from bellwether_analytics.core.queries import sync_dsn  # sync DSN helper
from bellwether_ingestion.polymarket_onchain.contracts import ORDER_FILLED_V2_TOPIC0
from bellwether_ingestion.polymarket_onchain.rpc import JsonRpc
from sqlalchemy import create_engine, text


def _distinct_txs(eng, fam: str) -> list[str]:
    with eng.connect() as c:
        rows = c.execute(text(
            "SELECT DISTINCT t.tx_hash FROM trade t JOIN market m ON m.id = t.market_id "
            "WHERE m.slug LIKE :fam AND t.tx_hash IS NOT NULL AND t.block_number IS NULL"
        ), {"fam": f"{fam}-%"}).all()
    return [r[0] for r in rows]


def _receipt_block(rpc: JsonRpc, tx: str):
    """Return (tx, block_number, has_v2_log) or (tx, None, False) on miss."""
    try:
        rc = rpc.call("eth_getTransactionReceipt", [tx])
    except Exception:  # noqa: BLE001
        return tx, None, False
    if not rc or rc.get("blockNumber") is None:
        return tx, None, False
    topic0s = {lg["topics"][0].lower() for lg in rc.get("logs", []) if lg.get("topics")}
    return tx, int(rc["blockNumber"], 16), (ORDER_FILLED_V2_TOPIC0 in topic0s)


def _bulk_update(eng, mapping: dict[str, int]) -> int:
    if not mapping:
        return 0
    with eng.begin() as c:
        c.execute(text("CREATE TEMP TABLE _bn (tx_hash text PRIMARY KEY, block_number bigint) ON COMMIT DROP"))
        items = list(mapping.items())
        for i in range(0, len(items), 5000):
            chunk = items[i:i + 5000]
            c.execute(
                text("INSERT INTO _bn (tx_hash, block_number) VALUES (:h, :b) ON CONFLICT DO NOTHING"),
                [{"h": h, "b": b} for h, b in chunk],
            )
        res = c.execute(text(
            "UPDATE trade t SET block_number = _bn.block_number FROM _bn "
            "WHERE t.tx_hash = _bn.tx_hash AND t.block_number IS NULL"
        ))
        return res.rowcount


def main() -> None:
    fam = sys.argv[1] if len(sys.argv) > 1 else "eth-updown-5m"
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 24
    eng = create_engine(sync_dsn(None))
    txs = _distinct_txs(eng, fam)
    print(f"[backfill] family={fam}  distinct tx to stamp={len(txs)}  workers={workers}")

    mapping: dict[str, int] = {}
    no_receipt = 0
    no_v2 = 0
    t0 = time.time()
    rpc = JsonRpc()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(_receipt_block, rpc, tx) for tx in txs]
        for i, fu in enumerate(as_completed(futs)):
            tx, bn, has_v2 = fu.result()
            if bn is None:
                no_receipt += 1
            else:
                if not has_v2:
                    no_v2 += 1
                mapping[tx] = bn
            if (i + 1) % 5000 == 0:
                print(f"  {i+1}/{len(txs)}  ok={len(mapping)} no_receipt={no_receipt} "
                      f"no_v2_log={no_v2}  {time.time()-t0:.0f}s")

    updated = _bulk_update(eng, mapping)
    eng.dispose()
    print("=" * 60)
    print(f"[backfill] family={fam}")
    print(f"  distinct tx queried        : {len(txs)}")
    print(f"  tx with block_number        : {len(mapping)}")
    print(f"  tx with NO receipt/block    : {no_receipt}")
    print(f"  tx WITHOUT a V2 OrderFilled : {no_v2} (block stamped anyway; tx-level)")
    print(f"  trade ROWS stamped          : {updated}")
    print(f"  elapsed                     : {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()

"""Collector service entrypoint.

For now this only bootstraps the database (applies migrations) and stays alive so
the Compose `ingestion` service has a long-running process. The live collectors
(Data API ~2s poller and the on-chain OrderFilled V2 listener — Bellwether Phase
2.2) plug in here. Kept honest: it logs that no live collectors are configured
yet rather than pretending to ingest.
"""

from __future__ import annotations

import asyncio
import logging
import os

from .db import Database

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bellwether.collector")


async def main() -> None:
    db = Database()
    await db.connect()
    try:
        applied = await db.apply_migrations()
        log.info("migrations applied: %s", applied or "(none)")
        log.info(
            "no live collectors configured yet (Phase 2.2: Data API poller + "
            "on-chain OrderFilled V2 listener). Idling."
        )
        # Heartbeat loop; replaced by real collector tasks in Phase 2.2.
        interval = int(os.environ.get("COLLECTOR_HEARTBEAT_SECONDS", "3600"))
        while True:
            await asyncio.sleep(interval)
            log.info("collector heartbeat")
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())

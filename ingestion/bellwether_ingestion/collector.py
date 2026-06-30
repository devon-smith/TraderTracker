"""Collector service entrypoint.

For now this only bootstraps the database (applies Alembic migrations) and stays
alive so the Compose `ingestion` service has a long-running process. The live
collectors (Data API ~2s poller and the on-chain OrderFilled V2 listener —
Bellwether Phase 2.2 / Prompt 7) plug in here.
"""

from __future__ import annotations

import asyncio
import logging
import os

from .db import upgrade_head

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bellwether.collector")


async def main() -> None:
    upgrade_head()
    log.info("migrations applied (alembic upgrade head)")
    log.info(
        "no live collectors configured yet (Phase 2.2: Data API poller + "
        "on-chain OrderFilled V2 listener). Idling."
    )
    interval = int(os.environ.get("COLLECTOR_HEARTBEAT_SECONDS", "3600"))
    while True:
        await asyncio.sleep(interval)
        log.info("collector heartbeat")


if __name__ == "__main__":
    asyncio.run(main())

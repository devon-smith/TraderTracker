"""CLI (read-only; requires POLYGON_RPC_URL):
  python -m bellwether_ingestion.polymarket_onchain backfill <from_block> <to_block>
  python -m bellwether_ingestion.polymarket_onchain watch
  python -m bellwether_ingestion.polymarket_onchain reconcile <wallet>
"""

from __future__ import annotations

import argparse
import logging
import sys

from .listener import run_backfill, run_reconcile, run_watch


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="bellwether_ingestion.polymarket_onchain")
    sub = p.add_subparsers(dest="cmd", required=True)

    bf = sub.add_parser("backfill", help="Scan a block range for OrderFilled")
    bf.add_argument("from_block", type=int)
    bf.add_argument("to_block", type=int)
    bf.add_argument("--version", default="v2", choices=["v1", "v2"])
    bf.add_argument("--dsn", default=None)

    w = sub.add_parser("watch", help="Poll new blocks and ingest OrderFilled")
    w.add_argument("--version", default="v2", choices=["v1", "v2"])
    w.add_argument("--dsn", default=None)

    rc = sub.add_parser("reconcile", help="Report onchain-vs-DataAPI overlap + freshness")
    rc.add_argument("wallet")
    rc.add_argument("--version", default="v2", choices=["v1", "v2"])
    rc.add_argument("--dsn", default=None)

    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    try:
        if args.cmd == "backfill":
            n = run_backfill(args.from_block, args.to_block, version=args.version, dsn=args.dsn)
            print(f"ingested {n} on-chain trade rows")
            return 0
        if args.cmd == "watch":
            run_watch(version=args.version, dsn=args.dsn)
            return 0
        if args.cmd == "reconcile":
            print(run_reconcile(args.wallet, version=args.version, dsn=args.dsn))
            return 0
    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())

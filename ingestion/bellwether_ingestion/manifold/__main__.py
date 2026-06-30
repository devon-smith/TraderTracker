"""CLI: python -m bellwether_ingestion.manifold load-user <username_or_id>"""

from __future__ import annotations

import argparse
import logging
import sys

from .loader import run_load_user


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bellwether_ingestion.manifold")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("load-user", help="Backfill a Manifold user's bet history")
    p.add_argument("identifier", help="Manifold username or user id")
    p.add_argument("--max-pages", type=int, default=200)
    p.add_argument("--max-bets", type=int, default=None, help="Cap most-recent bets processed")
    p.add_argument("--dsn", default=None, help="Override DATABASE_URL")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.cmd == "load-user":
        n = run_load_user(
            args.identifier, dsn=args.dsn, max_pages=args.max_pages, max_bets=args.max_bets
        )
        print(f"wrote {n} new trades for {args.identifier}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())

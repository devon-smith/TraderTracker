"""CLI:
  python -m bellwether_ingestion.polymarket load-wallet <address>
  python -m bellwether_ingestion.polymarket seed-leaderboard <n>
"""

from __future__ import annotations

import argparse
import logging
import sys

from .loader import run_load_wallet, run_seed_leaderboard


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bellwether_ingestion.polymarket")
    sub = parser.add_subparsers(dest="cmd", required=True)

    lw = sub.add_parser("load-wallet", help="Backfill a wallet's trade + activity history")
    lw.add_argument("address", help="EOA or proxy wallet address")
    lw.add_argument("--max-trade-pages", type=int, default=200)
    lw.add_argument("--max-markets", type=int, default=None, help="Cap distinct markets fetched")
    lw.add_argument("--dsn", default=None)

    sl = sub.add_parser("seed-leaderboard", help="Seed wallets from the Gamma leaderboard")
    sl.add_argument("n", type=int, nargs="?", default=100)
    sl.add_argument("--window", default="month", help="day | week | month | all")
    sl.add_argument("--dsn", default=None)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.cmd == "load-wallet":
        nt, ne = run_load_wallet(
            args.address, dsn=args.dsn,
            max_trade_pages=args.max_trade_pages, max_markets=args.max_markets,
        )
        print(f"wrote {nt} trades, {ne} position events for {args.address}")
        return 0
    if args.cmd == "seed-leaderboard":
        c = run_seed_leaderboard(args.n, window=args.window, dsn=args.dsn)
        print(f"seeded {c} wallets from the {args.window} leaderboard")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())

# TraderTracker

Operationalizes the feasibility study on tracking, scoring, and paper-trading
prediction-market wallets. Polymarket-first (where attribution is possible);
Kalshi-second (where it isn't, so we aggregate anonymous flow instead).

## What's in here

| Module | What it does |
|---|---|
| `tradertracker.polymarket.data_api` | Polymarket Data API client (`/trades`, `/positions`, `/activity`, `/holders`, `/value`) with pagination |
| `tradertracker.polymarket.gamma` | Gamma API client — leaderboard, markets, events |
| `tradertracker.polymarket.wallet_scoring` | Explainable wallet score: win rate, P&L, volume, category concentration |
| `tradertracker.kalshi.client` | Kalshi REST client with RSA-PSS request signing; public endpoints work unauth |
| `tradertracker.kalshi.flow` | Per-market, per-side flow aggregator over the anonymous `GetTrades` feed |
| `tradertracker.analytics.specialization` | Category breakdown for a wallet's trade history |
| `tradertracker.analytics.paper_trade` | Backtest copy-trades against a leader's history with a slippage model |
| `tradertracker.cli` | `tt` CLI |

## Install

```bash
pip install -e .
```

## CLI

```bash
tt poly leaderboard --window month --limit 25
tt poly wallet 0x... --pages 10
tt poly rank 0xA 0xB 0xC --min-trades 50 --min-win-rate 0.55
tt poly categories 0x...
tt poly paper 0x... --size-scale 0.05 --slippage-bps 200

tt kalshi flow --ticker KXFED --top 20
```

## What it deliberately does NOT do (yet)

- **No live trading.** The paper-trade simulator is a backtest; nothing places real orders.
- **No on-chain `OrderFilled` listener.** The Data API path is sufficient for
  research, ranking, and backtests. A live listener belongs behind a paid Polygon
  RPC (Alchemy/QuickNode) and the V2 contract `0xE111180000d2663C0091e4f400237545B87B996B` — see the V2 migration notes in the study.
- **No Kalshi account-level attribution.** The Kalshi public feed is anonymized
  by design; the `flow` module is the only honest "smart money" surface available.
- **No wallet clustering.** Chainalysis-style cross-wallet linkage is out of scope.

## Tests

```bash
pip install pytest
pytest -q
```

## Project layout

```
tradertracker/
  polymarket/   # Data API, Gamma, wallet scoring
  kalshi/       # RSA-PSS signed REST client, anonymous flow aggregator
  analytics/    # Category breakdown, paper-trade simulator
  cli.py        # `tt` entry point
tests/
```

See `.env.example` for configuration. Most Polymarket endpoints work
unauthenticated; Kalshi public endpoints (`GetTrades`, markets, orderbook) also
work without keys.

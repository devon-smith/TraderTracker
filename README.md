# Bellwether (repo: TraderTracker)

Prediction-market trader intelligence. Research-first: determine whether top
traders' edges are **trackable** (copyable fast enough to matter) or
**reverse-engineerable** (signal source inferable). Polymarket-first (attribution
is possible); Kalshi as anonymous flow (it isn't); Manifold as a zero-risk
prototype venue.

- **Plan:** `docs/BELLWETHER.md` (canonical) · `SCOPE.md` (lean module↔phase view)
- **Reconciliation & access notes:** `docs/RECONCILIATION.md`
- **Contributor guide:** `CLAUDE.md`

## Monorepo layout

```
ingestion/    Python `bellwether_ingestion` — clients, normalizers, DB (asyncpg)
analytics/    Python `bellwether_analytics` — scoring, paper-trade, flow, `tt` CLI
dashboard/    Next.js (App Router) + Prisma — read-only research UI
infra/        docker-compose (TimescaleDB), Caddy, Dockerfile, db/migrations
scripts/      deploy.sh, fetch_references.sh
references/   curated upstream repos (UNVERIFIED — see references/README.md)
docs/         BELLWETHER.md, RECONCILIATION.md
```

Dependency direction: **analytics → ingestion** (shared models in
`bellwether_ingestion.schemas`).

## Quickstart

```bash
# Python (workspace)
uv sync
# or pip:
pip install -e ./ingestion && pip install -e ./analytics --no-deps \
  && pip install typer rich python-dateutil
pytest -q                      # 11 tests

# Stack
cp .env.example .env
docker compose -f infra/docker-compose.yml up -d     # db + migrate + ingestion + dashboard
tt db init                     # apply canonical schema to $DATABASE_URL
```

## CLI

```bash
tt poly leaderboard --window month --limit 25
tt poly wallet 0x... --pages 10
tt poly rank 0xA 0xB 0xC --min-trades 50 --min-win-rate 0.55
tt poly categories 0x...
tt poly paper 0x... --slippage-bps 200
tt kalshi flow --top 20
tt db init
```

## What it deliberately does NOT do (yet)

- **No live trading.** The paper-trade simulator is a backtest.
- **No on-chain `OrderFilled` listener yet** (Phase 2.2 — needs a paid Polygon RPC
  + V2 contract `0xE111180000d2663C0091e4f400237545B87B996B`).
- **No Kalshi account attribution** — anonymized by design; flow aggregation only.
- **No wallet clustering.**

## Verification status

- Python: 11 tests pass; ruff clean.
- DB: canonical schema verified on TimescaleDB (extension + `trade` hypertable +
  idempotent re-apply + dedup + async insert round-trip).
- Compose: `docker compose config` valid.
- Dashboard: npm install + ESLint + SWC compile pass locally; full `next build`
  (needs the Prisma engine host) runs in CI — see `dashboard/README.md`.

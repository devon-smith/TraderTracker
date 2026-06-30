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
  && pip install typer rich python-dateutil pandas pyyaml
pytest -q                      # 31 pure tests (+1 DB-integration when DATABASE_URL is set)

# Stack
cp .env.example .env
docker compose -f infra/docker-compose.yml up -d     # db + migrate + ingestion + dashboard
tt db init                     # apply Alembic migrations to $DATABASE_URL
```

## Pipeline (Prompts 1→8 — the Phase 3 payoff)

```bash
# 0. ingest
tt manifold load <username>                          # Manifold (zero-risk prototype)
tt poly seed-leaderboard 200                          # seed wallet pool (recent-volume)
tt poly load 0x... --max-markets 200                  # Polymarket trades + activity
python -m bellwether_ingestion.polymarket_onchain backfill <from> <to>  # on-chain (needs RPC)

# 1. analyze + rank
tt analyze rank --platform polymarket --config config/ranking.yaml

# 2. candidate pool + validation (Phase 3)
tt candidates build --platform polymarket --min-resolved-trades 50 --min-win-rate 0.55
tt candidates validate 2026-03-01 --platform polymarket   # walk-forward + shuffled control

# legacy in-memory helpers
tt poly paper 0x... --slippage-bps 200                # paper-trade backtest
tt kalshi flow --top 20                               # anonymous Kalshi flow
```

Exploration notebooks: `analytics/notebooks/01_manifold_validation`,
`02_polymarket_pnl`, `03_candidate_pool`.

## What it deliberately does NOT do (yet)

- **No live trading.** Everything is paper/read-only; the on-chain listener never
  signs or submits a transaction.
- **On-chain listener needs a paid Polygon RPC** (`POLYGON_RPC_URL`) and the V2
  event ABI confirmed against the deployed contract — see
  `bellwether_ingestion.polymarket_onchain` (the decoder is unit-tested; the live
  path can't run without an RPC).
- **No Kalshi account attribution** — anonymized by design; flow aggregation only.
- **No wallet clustering.**

## Verification status

- Python: 31 pure tests + 1 DB-integration test; ruff clean.
- DB: Alembic schema verified on TimescaleDB (extension, all hypertables,
  idempotent re-apply, dedup IntegrityError, async insert round-trip).
- Live ingestion verified against api.manifold.markets and data-api/gamma
  (idempotent loads; correct categories + REDEEM/usdc P&L).
- On-chain decoder verified deterministically (encode → decode → maker/taker rows).
- Candidate pool persists to `candidate_score`; walk-forward edge>0 vs shuffled
  control on fixtures.
- Compose: `docker compose config` valid. Dashboard: npm install + ESLint + SWC
  compile pass locally; full `next build` runs in CI (`dashboard/README.md`).

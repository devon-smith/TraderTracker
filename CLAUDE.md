# Bellwether — agent & contributor guide

Prediction-market trader intelligence. Research-first: determine whether top
traders' edges are **trackable** (copyable fast enough to matter) or
**reverse-engineerable** (signal source inferable). Capital deployment is
optional validation, not the objective. Canonical plan: `docs/BELLWETHER.md`.

## Layout (monorepo)

```
ingestion/    Python pkg `bellwether_ingestion` — IO: clients, normalizers, DB
  bellwether_ingestion/
    schemas.py            canonical Trade/Position/Activity (shared models)
    polymarket/ kalshi/ manifold/   per-venue clients
    db/                   normalizers (pure) + asyncpg Database (pool/migrate/insert)
    collector.py          long-running collector service entrypoint
analytics/    Python pkg `bellwether_analytics` — computation (depends on ingestion)
    wallet_scoring, specialization, paper_trade, kalshi_flow, cli (`tt`)
dashboard/    Next.js (App Router) + Prisma — read-only research UI
infra/        docker-compose, Caddy, python.Dockerfile, db/migrations/*.sql
scripts/      deploy.sh, fetch_references.sh
references/   curated upstream repos (UNVERIFIED — see references/README.md)
docs/         BELLWETHER.md (plan), RECONCILIATION.md
```

Dependency direction is one-way: **analytics → ingestion**. Shared data shapes
live in `bellwether_ingestion.schemas` so analytics imports them without httpx.

## Dev

```bash
# install (workspace; uv) — or pip-editable both packages
uv sync
# or:
pip install -e ./ingestion && pip install -e ./analytics --no-deps && pip install typer rich python-dateutil

pytest -q                       # 11 tests (pure; no DB needed)
tt --help                       # CLI

# bring up the stack (db + migrate + ingestion + dashboard)
cp .env.example .env
docker compose -f infra/docker-compose.yml up -d
docker compose -f infra/docker-compose.yml --profile proxy up -d   # add Caddy

tt db init                      # apply migrations against $DATABASE_URL
```

## Hard constraints (don't regress these)

- **Polymarket is trackable; Kalshi is not.** Kalshi's public feed has no user
  id — only aggregate flow (`bellwether_analytics.kalshi_flow`). Never scope
  per-account Kalshi tracking.
- **Polymarket V2 (Apr 2026):** on-chain work targets CTF Exchange V2
  `0xE111180000d2663C0091e4f400237545B87B996B` + pUSD collateral.
- **Kalshi Data ToS** restricts ML-training/redistribution — gate before Phase 5.
- **Reference repos** (`references/`) are unverified and some sign transactions;
  audit line-by-line before importing, pin SHAs, never run their execution paths.
- **Everything is paper-mode.** No live order placement without an explicit,
  separately-approved gated execution phase.

## Migrations

SQL files in `infra/db/migrations/*.sql`, applied in lexical order by
`Database.apply_migrations` / `tt db init`. They run in a single transaction —
must be idempotent, no continuous aggregates (use plain views).

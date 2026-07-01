# Bellwether — Project Context & Handoff

> **Purpose of this file.** A complete, self-contained snapshot of the project so
> a fresh Claude Code session (now running on a **local VM** instead of the
> hosted sandbox) can pick up with zero prior conversation. Read this first, then
> `docs/BELLWETHER.md` (canonical plan) and `CLAUDE.md` (contributor rules).
>
> **Written:** 2026-07-01, at the boundary of moving from the hosted sandbox to a
> local VM. The move matters — see [§9 Environment: sandbox vs local VM](#9-environment-sandbox-vs-local-vm).
> The local VM is what finally unblocks **Goal 4** (the real end-to-end run).

---

## 1. What this project is

**Bellwether** (repo: `TraderTracker`) is a self-hosted prediction-market
**trader-intelligence** system. It is **research-first, not a trading bot**. The
question it exists to answer:

> Are top prediction-market traders' edges **trackable** (copyable fast enough to
> matter after latency + slippage) or **reverse-engineerable** (the signal source
> can be inferred from timing / order-flow)?

Capital deployment is *optional validation*, never the objective. The deliverable
is an analytics engine + research dashboard + a written verdict — not a money
printer.

**Venue asymmetry (a hard constraint, not a preference):**
- **Polymarket is trackable** — wallet activity is public (Data API) and on-chain
  (`OrderFilled` on the CTF Exchange). Attribution per account is possible.
- **Kalshi is NOT trackable** — the public feed is anonymized; there is no API
  path to per-account identity. Kalshi gets **aggregate flow signals only**, never
  per-account tracking.
- **Manifold** is a zero-risk prototype venue (free API, play money) used to
  validate the scoring/specialization/ranking math before pointing it at real
  money.

Everything is **paper-mode / read-only**. No live order placement, and the
on-chain listener **never signs or submits a transaction**.

---

## 2. Current status at a glance

| Item | State |
|---|---|
| Branch (develop here only) | `claude/prediction-market-tracking-study-oakly7` |
| Latest commit | `a2b215f` — "Seed co-trading candidate pool + fix two latent bulk-load bugs" |
| Tests | **53** collected — 52 pure (no DB) + 1 DB-integration (runs only when `DATABASE_URL` set). All green. |
| Lint | `ruff` clean across both Python packages |
| Migrations | `0001` → `0004` (latest adds `trade.block_number`) |
| Phases built | Phase 0–3 fully; Phase 3.5 strategy-detection layer; on-chain decoder + block-gap guard (unit-tested, not yet run live) |
| **First real run** | **Done (REST).** Seed co-trading pool built + verified against live Polymarket; archetype + null-model copy-chain runs produced real findings (below). |
| Biggest gap | **On-chain block-gap guard + resolution depth.** The statistical (null-model) copy-chain guard has run on real data; the *second* guard (on-chain block-gap) and deeper history still need the block_number backfill (Goal 4 / `contracts.py`). |

Work has been done as a sequence of numbered "Prompts" (P1–P16) plus several
`/goal` directives. All are complete and committed (see `git log --oneline`).

### 2a. First real run — seed co-trading pool (REST) & first findings

Built the first real candidate pool and ran the copy-chain-half of the analytics
on live data (scripts: `seed_cotrading_pool.py`, `finalize_pool.py`,
`overlap_report.py`, `archetype_report.py`, `copychain_report.py`).

- **Pool:** 768 co-trading wallets (701 with ≥50 trades), **1.67M trades**,
  470k position events. Seeded from recurring co-trading sources (crypto
  up/down families + holders/traders of recent resolved markets), *not* a random
  volume cut. Gamma `/leaderboard` is gone; seeded from the live `/trades` feed.
- **Overlap gate PASSED:** **96.9%** of the pool has ≥3 shared-market neighbors
  (196k pairs share ≥3 markets) — dense and recurring, the right shape for
  copy-chain detection, not a diffuse set.
- **Archetype distribution:** accumulator 40% · scalper 34% · mixed 12% ·
  market_maker 7% · arbitrageur 7% · hold_to_resolution 1%. Median 80 trades/day,
  net_direction 0.92 (directional, *not* two-sided market-making).
- **Null-model copy-chains (first of two guards):** in `eth-updown-5m` alone,
  **2,235 (leader→follower) pairs survived the permutation null model** (top pair
  1072 follows vs 254 null, p<0.001). Real lead-lag structure exists. Caveat:
  several top pairs are **bidirectional** (mutual co-reaction / shared signal,
  not confirmed one-way copying) — the on-chain block-gap guard is what
  disambiguates, and it's pending the block_number backfill.

**Two caveats that shape the next steps:**
1. **REST captures only the last ~3,500 trades/wallet** — for these
   high-frequency wallets that's the last few *hours*, so most markets are too
   recent to be resolved. Resolution linkage is real but thin (816 markets
   resolved via CLOB + Gamma anchors; 287k/1.67M trades scoreable). The
   **profitability run should wait** for a wider resolution window (CLOB is fast;
   or let markets settle) — a ranking off hours of data is where luck masquerades
   as edge.
2. **The 4GB sandbox OOMs the whole-pool pandas loads** (`tt strategy
   classify/leadlag`). The report scripts above work around it by batching
   per-wallet (archetype) or scoping to one family (copy-chains). The full
   cross-wallet copy-chain run over all families wants the larger local VM.

Two latent bulk-load bugs were fixed en route (both bite any real full-history
load): `repo.py` chunks inserts under asyncpg's 32767-param cap; `loader.py`
resolves markets in deterministic order so concurrent wallet loads don't deadlock.

---

## 3. Repository layout (monorepo)

```
ingestion/    Python pkg `bellwether_ingestion` — all IO: clients, normalizers, DB
  bellwether_ingestion/
    schemas.py            canonical Trade/Position/Activity dataclasses (shared shapes)
    polymarket/           Data API + Gamma clients, loader, categorize
    polymarket_onchain/   OrderFilled V2 decoder + listener + JSON-RPC (read-only)
    kalshi/               anonymized client (flow only)
    manifold/             prototype-venue client + loader
    db/                   SQLAlchemy 2.x models, async session, Alembic, repo, normalizers
    collector.py          long-running collector service entrypoint (currently an idler stub)
analytics/    Python pkg `bellwether_analytics` — computation (depends on ingestion)
  bellwether_analytics/
    core/                 P&L, performance, specialization (HHI), ranking, queries
    candidates/           pool builder, trackability pre-score, walk-forward validation
    strategy/             THE strategy-detection layer (see §6)
    experiments/          trackability_real (per-leader empirical copyability)
    kalshi_flow.py, paper_trade.py, wallet_scoring.py, specialization.py
    cli.py                the `tt` CLI (Typer)
    notebooks/            01_manifold_validation … 04_strategy_detection
dashboard/    Next.js (App Router) + Prisma — read-only research UI
infra/        docker-compose.yml (TimescaleDB), Caddy, python.Dockerfile, db/migrations
scripts/      deploy.sh, fetch_references.sh
references/   curated upstream repos (UNVERIFIED — never run their execution paths)
docs/         BELLWETHER.md (canonical plan), RECONCILIATION.md, this file
```

**Dependency direction is one-way: `analytics → ingestion`.** Shared data shapes
live in `bellwether_ingestion.schemas` so analytics imports models without pulling
in httpx. Never make ingestion import analytics.

---

## 4. How to run it (local VM)

### 4.1 Python (the analytics + ingestion core)

```bash
# workspace install (uv) — installs both editable packages
uv sync
# or pip:
pip install -e ./ingestion && pip install -e ./analytics --no-deps \
  && pip install typer rich python-dateutil pandas pyyaml matplotlib

pytest -q            # 52 pure tests; +1 DB-integration when DATABASE_URL is set
tt --help            # the CLI
```

### 4.2 The stack (DB + migrate + ingestion + dashboard)

```bash
cp .env.example .env                 # then fill in POLYGON_RPC_URL etc. (see §5)
docker compose -f infra/docker-compose.yml up -d          # db, migrate, ingestion, dashboard
docker compose -f infra/docker-compose.yml --profile proxy up -d   # + Caddy basic-auth (prod)

tt db init                           # apply Alembic migrations to $DATABASE_URL
```

Compose services (`infra/docker-compose.yml`):
- `db` — `timescale/timescaledb:latest-pg16`, volume `bellwether_pgdata`
- `migrate` — one-shot `tt db init`, then exits
- `ingestion` — long-running collector (currently idles; see §8 gap)
- `dashboard` — Next.js on `:3000`
- `caddy` — reverse proxy + basic-auth, `--profile proxy` only

### 4.3 The data pipeline (the Phase-3 payoff)

```bash
# 0. ingest
tt manifold load <username>                         # Manifold (zero-risk prototype)
tt poly seed-leaderboard 200                         # seed wallet pool (recent-volume fallback*)
tt poly load 0x... --max-markets 200                 # Polymarket trades + activity (REST)
python -m bellwether_ingestion.polymarket_onchain backfill <from> <to>   # on-chain (NEEDS RPC)

# 1. rank
tt analyze rank --platform polymarket --config config/ranking.yaml

# 2. candidate pool + validation (Phase 3)
tt candidates build --platform polymarket --min-resolved-trades 50 --min-win-rate 0.55
tt candidates validate 2026-03-01 --platform polymarket   # walk-forward + shuffled control

# 3. strategy detection (accounts -> recurring strategy templates)
tt strategy classify      --platform polymarket           # archetype per wallet + reason
tt strategy templates     --platform polymarket           # (archetype, family) run by many accounts
tt strategy recurrence    <wallet>                        # same cycle repeated over time
tt strategy leadlag       --platform polymarket           # copy chains (null-model filtered)
tt strategy copychains    --platform polymarket           # null model + block-gap + per-leader verdict
tt strategy profitability 2026-03-01 --platform polymarket  # templates ranked by out-of-sample P&L

# legacy in-memory helpers (no DB)
tt poly paper 0x... --slippage-bps 200                # paper-trade backtest
tt kalshi flow --top 20                               # anonymous Kalshi flow
```

\* **Gamma's public `/leaderboard` returns 404 (endpoint gone).** `seed-leaderboard`
falls back to a recent-volume scan. For real overlapping-wallet pools, seed from
liquid recurring markets / Top Holders (see §10 Goal 4).

---

## 5. Configuration / secrets (`.env`)

Copy `.env.example` → `.env` (gitignored). Keys that matter:

| Var | What | Notes |
|---|---|---|
| `DATABASE_URL` | Postgres/Timescale DSN | `localhost` for host dev; `db` inside compose |
| `POLYGON_RPC_URL` | **Paid** Polygon Mainnet RPC | **The single blocker for Goal 4.** Alchemy/QuickNode. Public RPCs are key-gated and were fully blocked in the sandbox. |
| `POLYMARKET_DATA_API` | `https://data-api.polymarket.com` | reachable |
| `POLYMARKET_GAMMA_API` | `https://gamma-api.polymarket.com` | reachable; `/leaderboard` is 404 |
| `POLYMARKET_CLOB_API` | `https://clob.polymarket.com` | only if we ever execute (we don't) |
| `MANIFOLD_API` | `https://api.manifold.markets` | reachable, no auth |
| `KALSHI_*` | flow only | public GetTrades needs no auth |
| Caddy / dashboard vars | basic-auth + ports | prod proxy |

---

## 6. The strategy-detection layer (the intellectual core)

`analytics/bellwether_analytics/strategy/` — answers "what **strategies** recur,
not just which accounts win." Accounts are what Polymarket exposes; the durable
signal is a **behavioral template run over and over** (across markets in a family,
across accounts, or as copy chains).

Pipeline and modules:

1. **`features.py` — `extract_features(trades, events)`**: per-wallet behavioral
   vector — cadence (trades/day), two-sidedness, round-trip ratio,
   split/merge/redeem mix, recurrence, and (from on-chain data) **`taker_ratio`**
   = fraction of fills where the wallet was the aggressor. *Gotcha fixed:* mixed
   on-chain+REST populations must coerce `is_taker` to float before the per-wallet
   mean (was a `LossySetitemError`; regression-tested).

2. **`archetypes.py` — `classify(features)`**: explainable **rule-based** archetype
   per wallet — `market_maker` / `arbitrageur` / `scalper` / `accumulator` /
   `hold_to_resolution` / `mixed`. `taker_ratio` gates scalper-vs-market-maker
   (a scalper crosses the spread; a market-maker rests). Every label carries a
   human-readable `reason`.

3. **`recurrence.py` — `strategy_templates`, `market_family`,
   `wallet_family_recurrence`**: collapses a slug's variable suffix
   (`btc-updown-5m-<ts>` → `btc-updown-5m`) so the *same strategy run repeatedly*
   is one row. Surfaces `(archetype, market-family)` templates run by ≥N distinct
   wallets.

4. **`recurrence_time.py` — `periodicity`, `cycle_motifs`,
   `recurrence_in_time_report`**: does one account run the same
   buy→accumulate→redeem cycle on a **regular cadence**? High regularity + many
   completed cycles = a templated strategy repeated in time.

5. **`leadlag.py` — copy-chain detection, guarded two ways** so shared reaction to
   public news isn't mistaken for copying:
   - `detect_followers` — raw "B fills shortly after A" pairs.
   - `detect_followers_significant` — **permutation null model**: shuffle
     timestamps within each market K times; keep only pairs whose follow-count
     beats the null threshold (rejects synchronized-info false positives).
   - `confirm_block_gaps` / `confirmed_copy_chains` — **on-chain block-gap
     confirmation**: a real follower lands a *small, consistent, positive* block
     gap after the leader, repeatedly (bounded gap, low std, across ≥N markets).
     This is the decisive second guard. Falls back to significance-only when block
     data is absent.

6. **`profitability.py` — `rank_templates(trades, split_ts, n_periods=3,
   shuffle=False)`**: the project's core question, reframed from "top accounts" to
   **feasible strategy TEMPLATES**. **Strictly out-of-sample**: fit
   archetype/family labels on the window *before* `split_ts`, measure realized P&L
   (from the existing `performance_by_wallet` engine) on the window *after*.
   Returns a ranked `(archetype, family)` table with median/mean/std P&L,
   `pct_profitable`, sharpe, **`persistence`** (fraction of OOS sub-periods with
   positive median P&L), and a capacity proxy (**`pnl_per_volume`**,
   `capacity_corr` = P&L vs position size). `shuffle=True` is the **control**: the
   label→P&L edge must vanish.

7. **`clustering.py` — `cluster_wallets`, `compare_to_rules`,
   `recommend_thresholds`**: unsupervised cross-check (k-means/HDBSCAN) of the rule
   archetypes; surfaces disagreements and suggests threshold tweaks. Diagnostic
   only.

8. **`experiments/trackability_real.py` — `rank_leaders`, `trackability_verdict`,
   `pair_copy_metrics`**: for confirmed copy-chains, what did **real followers
   actually capture**? Entry-price delta, time gap, block gap → per-leader
   empirical `copyable_score`.

**Validated at ≥500-wallet scale** (`analytics/tests/test_pool_scale.py`): 490
background + 10 synchronized reactors (same block, random order) + 1 planted
copy-chain (+10s / +2 blocks). Reactors are rejected by block-gap confirmation;
only the planted consistent-gap chain survives. This is the proof that the guard
works — synchronized public-news reaction does not masquerade as copying.

Notebook `analytics/notebooks/04_strategy_detection.ipynb` renders all of this end
to end, including per-archetype out-of-sample P&L boxplots + the ranked
feasible-templates table (needs `matplotlib>=3.7`, already in `analytics/pyproject.toml`).

---

## 7. Data model (canonical schema)

SQLAlchemy 2.x models in `ingestion/bellwether_ingestion/db/models.py` are the
**source of truth**. Alembic migration `0001` creates the TimescaleDB extension,
all tables/enums (via `metadata.create_all`), and the hypertables.

Tables: `wallet`, `market`, `trade`, `position_event`, `event`, `ingestion_run`,
`candidate_score` (derived ranking), `kalshi_flow` (derived).

**Hypertables** (partitioned on `ts`): `trade`, `position_event`, `event`.
`trade` and `position_event` use a natural **`(dedup_key, ts)` primary key** →
idempotent ingestion (ON CONFLICT) and a hard unique-violation for plain inserts.

`trade` carries the on-chain enrichment columns: `block_number` (bigint, on-chain
only — added in `0004`), `is_taker` (bool aggressor signal — added in `0003`),
plus `tx_hash`, `log_index`, `source` (`data_api` | `onchain` | `manifold_api`).

Migrations, in order:
- `0001_initial` — extension + tables + enums + hypertables
- `0002_derived_tables` — `candidate_score`, `kalshi_flow`
- `0003_trade_is_taker` — `ADD COLUMN IF NOT EXISTS is_taker` (idempotent; `create_all` already reflects it)
- `0004_trade_block_number` — `ADD COLUMN IF NOT EXISTS block_number`

Apply with `tt db init` (programmatic `upgrade_head`) or `alembic upgrade head`.

---

## 8. On-chain ingestion (`polymarket_onchain/`) — status & caveats

Read-only decoder for the CTF Exchange V2 `OrderFilled` event. **It never signs or
submits anything.** Components:
- `rpc.py` — `JsonRpc` over httpx. Raises a clear error if `POLYGON_RPC_URL` is
  unset ("needs a paid Polygon RPC (Alchemy/QuickNode); public endpoints are
  key-gated").
- `contracts.py` — CTF Exchange V2 `0xE111180000d2663C0091e4f400237545B87B996B`
  + NegRisk V2. **The `ORDER_FILLED_V2` ABI is marked UNVERIFIED / best-effort.**
- `decode.py` — ABI-driven log decode (eth-abi/eth-utils, no web3).
- `normalize.py` / `listener.py` — set `block_number` + `is_taker` on each trade.

**Two caveats before trusting live output:**
1. **No RPC = no live path.** The decoder is unit-tested (encode→decode symmetry,
   maker/taker rows) but the live listener has **never run** — the sandbox blocked
   all Polygon RPCs. The local VM + a paid RPC key is what changes this.
2. **The V2 event ABI must be confirmed** against the deployed contract (decode a
   couple of known fills by hand, or pull the verified ABI from Polygonscan)
   before believing any decoded block gap.

**Other known gaps:**
- `collector.py` is a **stub** — it applies migrations and idles with a heartbeat.
  The live Data-API ~2s poller and the on-chain listener are not yet wired into
  it (that's Phase 2.2 / Goal 5 hardening work).
- Dashboard's Prisma engine download (`binaries.prisma.sh`) was blocked in the
  sandbox; on a normal-egress VM `npm install` + `prisma generate` work fine.

---

## 9. Environment: sandbox vs local VM

This is *why* we're moving, so it's worth stating precisely. **In the hosted
sandbox, egress was locked down.** On a local VM with normal outbound internet,
these blockers disappear — which is exactly what unblocks Goal 4.

| Endpoint / capability | Hosted sandbox | Local VM (expected) |
|---|---|---|
| `data-api.polymarket.com`, `gamma-api.polymarket.com` | ✅ reachable | ✅ |
| `api.manifold.markets` | ✅ reachable | ✅ |
| Gamma `/leaderboard` | ❌ 404 (endpoint gone) | ❌ (still gone — code has a fallback) |
| **All public Polygon RPCs** (polygon-rpc/ankr/llamarpc) | ❌ key-gated / blocked | ✅ with a paid key (`POLYGON_RPC_URL`) |
| `api.github.com` | ❌ 403 org egress | ✅ |
| `binaries.prisma.sh` (Prisma engine) | ❌ blocked | ✅ |
| Reference repos (`references/`) | ❌ unfetchable (GitHub blocked) | ✅ fetchable — but still **audit line-by-line, pin SHAs, never run their execution paths** |

Consequence in the sandbox: on-chain ingestion + block-gap confirmation are
**unit-tested / synthetic only**. On the VM, with a paid RPC and open egress, the
first *real* end-to-end run (Goal 4) becomes possible.

Note: Polymarket **geo-blocks US users** — the VM's egress IP matters for the REST
calls. If the VM is US-hosted, plan accordingly.

---

## 10. What's next: Goal 4 and Goal 5

### Goal 4 — the first real end-to-end run (unblocked by the local VM)

Do a **broad, uncapped** Polymarket load of a ≥500-wallet pool over **resolved**
markets, with `block_number` populated, then run the full guarded pipeline and
write a findings note. It has two halves:

- **REST half (works the moment egress is open):** archetype distribution,
  `rank_templates` on real out-of-sample data, time-gap trackability. No RPC
  needed.
- **On-chain half (needs `POLYGON_RPC_URL`):** `confirmed_copy_chains` with real
  block numbers, per-leader `trackability_verdict`. This is the copy-chain half
  that stays simulated without an RPC.

**Physical prerequisites checklist:**
1. **Paid Polygon Mainnet RPC** (Alchemy/QuickNode free tier is enough) →
   set `POLYGON_RPC_URL`. *The one hard blocker.*
2. **Open egress** to the Polymarket APIs **and** the RPC provider (the VM gives
   this; the sandbox didn't).
3. **Persistent TimescaleDB with disk** sized for ≥500 wallets' histories →
   `docker compose up -d db` + `tt db init`. Not an ephemeral DB.
4. **Always-on runtime** — an uncapped load + on-chain backfill is hours; run the
   collector on the VM, not in a session that gets reclaimed.
5. **A seed source of overlapping wallets** — leaderboard is gone, so seed from
   liquid recurring markets / Top Holders (e.g. `btc-updown-5m-*`), because
   copy-chains only appear where leaders and followers share books.
6. **Confirm the V2 `OrderFilled` ABI** before trusting decoded block gaps (§8).
7. Keep the standing constraints: **paper-mode only**, listener never signs,
   zero-funds wallet if any on-chain interaction, Polymarket US geo-block.

**Recommended sequencing:** run the **REST-only half first** (de-risks the
pipeline on real data, surfaces loader/scale issues while the RPC key is being
provisioned), then re-run the copy-chain half once `POLYGON_RPC_URL` is live.

### Goal 5 — Phase-7 hardening (after Goal 4)

- **Collector resilience**: retries/backoff, resumable cursors (the
  `ingestion_run` table exists for this), RPC failover, graceful shutdown. Wire
  the real poller + listener into `collector.py` (currently a stub).
- **Observability**: freshness lag, job success/fail, RPC error rate, alerting.
- **Security audit**: line-by-line third-party review, pinned deps, allow-listed
  egress, dedicated zero-funds wallet, no unbounded token approvals (Revoke.cash).
- **Deploy runbook** + findings write-up in `docs/`.

---

## 11. Hard constraints & security posture (do not regress)

From `CLAUDE.md` and `SCOPE.md` — these are load-bearing:

- **Polymarket is trackable; Kalshi is not.** Never scope per-account Kalshi
  tracking. Kalshi = aggregate flow only (`bellwether_analytics.kalshi_flow`).
- **Everything is paper-mode.** No live order placement without an explicit,
  separately-approved gated execution phase. The on-chain listener is **read-only
  and must never sign or submit a transaction.**
- **Polymarket V2 (Apr 2026):** on-chain work targets CTF Exchange V2
  `0xE111180000d2663C0091e4f400237545B87B996B` + pUSD collateral. Pre-V2 tooling
  is invalid.
- **Kalshi Data ToS** restricts ML-training / redistribution — a hard legal gate
  before any modeling on Kalshi data; gate before Phase 5.
- **Reference repos (`references/`) are UNVERIFIED** and some sign transactions.
  Audit line-by-line before importing, pin SHAs, **never run their execution
  paths.** This repo category has documented key-theft malware.
- For any on-chain interaction: dedicated **zero-funds wallet**, capped token
  approvals (Revoke.cash). Treat `.env`, `secrets/`, signed-message material as
  private (all gitignored).
- **Survivorship guard**: ~16.8% of traders are net-positive by luck. Every
  performance claim needs walk-forward OOS validation + shuffled-label control +
  ≥50 resolved trades. (Built into `candidates/validation.py` and
  `strategy/profitability.py`.)

### Workflow rules (also load-bearing)
- Develop **only** on branch `claude/prediction-market-tracking-study-oakly7`.
  Never push to another branch without explicit permission.
- Do **not** open a PR unless explicitly asked.
- On the hosted sandbox, GitHub access was scoped to `devon-smith/tradertracker`
  only. On the local VM you'll use normal git/GitHub auth.

---

## 12. Verification status (what's actually been proven)

- **Python:** 52 pure tests + 1 DB-integration test (runs when `DATABASE_URL`
  set); `ruff` clean.
- **DB:** Alembic schema verified on TimescaleDB — extension, all hypertables,
  idempotent re-apply, dedup IntegrityError, async insert round-trip.
- **Live ingestion:** verified against `api.manifold.markets` and Polymarket
  Data/Gamma (idempotent loads; correct categories; REDEEM/usdc P&L).
- **On-chain decoder:** verified deterministically (encode → decode →
  maker/taker rows). **Live path NOT run** (no RPC in sandbox).
- **Candidate pool:** persists to `candidate_score`; walk-forward edge > 0 vs
  shuffled control on fixtures.
- **Strategy layer:** archetype separation, recurrence, null-model + block-gap
  copy-chain guard, out-of-sample template ranking with persistence + capacity +
  shuffled control — all unit-tested; ≥500-wallet scale test passes.
- **Compose:** `docker compose config` valid. **Dashboard:** `npm install` +
  ESLint + SWC compile pass locally; full `next build` runs in CI. Prisma engine
  download was blocked in the sandbox (works on a normal-egress VM).

**Bottom line:** the analytics + guards are proven on synthetic/fixture data and
live REST data. What has *not* happened is a real, at-scale, on-chain-confirmed
run — that is Goal 4, and it is what the local VM exists to enable.

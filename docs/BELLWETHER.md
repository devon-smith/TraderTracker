# Project Scope: Bellwether — Prediction-Market Trader Intelligence & Strategy Reverse-Engineering

> Working codename "Bellwether" (a bellwether leads the flock — the traders
> you're hunting are the ones others should follow). Rename freely.
>
> **Document status:** Living plan, v0.1. Refine as findings come in.
> **Primary author context:** Solo dev, Claude Code–driven, comfortable in
> TypeScript/Next.js/Prisma/Postgres/Docker/Hetzner and Python/Jupyter for ML.

> **Reconciliation note (added in-repo):** This is the expanded, canonical plan.
> The lean `SCOPE.md` at the repo root maps the *already-built* `tradertracker/`
> Python package onto a 5-phase view; see `docs/RECONCILIATION.md` for how the
> existing code lines up against the Bellwether phases below and for the
> repo-access finding that gates the reuse strategy.

## How to read this doc
This is a **research-first** plan, not a trading-bot plan. The goal is to
*determine* whether top traders' edges are **trackable** (copyable fast enough to
matter) or **reverse-engineerable** (you can infer the signal source) — capital
deployment is optional validation, not the objective. The phases are **staged so
value is front-loaded**: you have a working analytics pipeline by ~Phase 3 and
can stop at any phase boundary with a usable artifact. Phases 5–6 are genuinely
optional depending on what Phases 3–4 reveal.

## Project Overview
Bellwether is a self-hosted system that ingests per-trader activity from
prediction markets (Polymarket first, then Kalshi flow + Manifold), identifies
accounts that are both **performant** and **specialized** in specific market
categories, and then runs two structured experiments on the best candidates:
(A) can their trades be **tracked and copied** within a useful latency/slippage
budget, and (B) can their underlying **strategy or information source be
reverse-engineered** from timing and order-flow patterns. The deliverable is an
analytics engine + research dashboard + a written verdict on edge feasibility,
not a money printer.

## Goals & Success Criteria
1. **Coverage** — Ingest/refresh full Polymarket trade/position history for any
   wallet on demand, plus a maintained pool of ≥500 candidate wallets, with <2s
   polling freshness on tracked wallets. *Done when:* a single command returns a
   wallet's complete trade history, P&L, and category mix in <5s from cache.
2. **Candidate identification** — Ranked list of wallets that are (a)
   net-positive over ≥50 resolved trades, (b) ≥55% win rate, (c)
   category-concentrated (computed specialization score). *Done when:* the
   ranking is reproducible and back-tested against held-out resolved markets.
3. **Trackability verdict (Experiment A)** — For ≥10 candidate wallets, measure
   end-to-end detection→simulated-fill latency and modeled slippage in **paper
   mode**. *Done when:* you can state, per wallet, the net-of-slippage return a
   follower would have captured, and a yes/no on whether copying beats the decay.
4. **Reverse-engineering verdict (Experiment B)** — For ≥10 candidate wallets,
   quantify trade-timing alignment with external event feeds (economic calendar,
   sports stats, polling, news) and order-flow signatures. *Done when:* each
   wallet has a "likely-informed + likely-category-source" score with a
   confidence interval, validated on held-out markets.
5. **Kalshi reality check** — Aggregate Kalshi's anonymous flow into a
   per-market/per-side signal (NOT per-account tracking, which is impossible).
   *Done when:* the system demonstrates *why* per-account Kalshi tracking can't
   be done and provides the best available aggregate substitute.
6. **Operational** — Everything runs on a single Hetzner VPS under Docker
   Compose with automated refresh, monitoring, and a one-command deploy. *Done
   when:* `./deploy.sh` ships and the collector survives a reboot.

## Technical Architecture

**Shape:** A Python research/analytics core + a thin TypeScript/Next.js dashboard,
sharing one PostgreSQL/TimescaleDB database, all in Docker Compose on Hetzner.

**Components:**
- **Ingestion services (Python):** Polymarket historical loader; Polymarket live
  collector (Data API ~2s poll + on-chain `OrderFilled` V2 listener via paid
  Polygon RPC); Kalshi flow collector (anonymous feed + book over WebSocket);
  Manifold collector (prototype/validation harness).
- **Storage:** PostgreSQL + **TimescaleDB** (hypertables for trade time-series) +
  optional pgvector for market-text clustering. Prisma (dashboard reads);
  SQLAlchemy/asyncpg (Python services).
- **Analytics engine (Python):** performance metrics, category-specialization
  clustering, candidate ranking, and the two experiment pipelines (copy-latency
  simulator; timing/order-flow reverse-engineering). Jupyter for exploration;
  APScheduler for productionized jobs.
- **Dashboard (Next.js + D3):** wallet explorer, candidate leaderboard,
  specialization views, experiment results, Kalshi flow monitor. Read-only over
  the shared DB; Caddy basic-auth in front.
- **Scheduler/orchestration:** APScheduler (or in-container cron); a job table in
  Postgres for run history.

**Data flow:** RPC/API/WebSocket → ingestion normalizes into canonical
`trade`/`position`/`market`/`wallet` tables → analytics jobs compute
metrics/scores into derived tables → dashboard reads derived tables → experiments
read raw + derived and write results tables.

**Cross-cutting dependencies:**
- The **Polymarket V2 migration (Apr 2026)** invalidates pre-V2 on-chain tooling.
  Every on-chain task targets the V2 contract + pUSD collateral.
- The **Kalshi Data ToS ML/redistribution clause** is a hard legal gate blocking
  Phase 5 model-building and any data redistribution until cleared (Phase 0 task).
- **Resolved-market outcomes** gate *every* performance/specialization/experiment
  metric. The historical loader must capture resolution data.

## Detailed Roadmap

**Critical path:** Phase 0 → 2 → 3 → 4. Phase 1 (Manifold) runs in parallel with
late Phase 0 and de-risks Phase 3's analytics. Phase 5 (Kalshi) and the dashboard
half of Phase 6 can proceed in parallel with Phase 4. Phase 7 overlaps the back
half of everything. **Rough effort:** ~11–16 weeks focused solo part-time; usable
analytics pipeline by ~week 5.

### Phase 0 — Foundations, Setup & Legal Gating (~3–5 days)
**0.1 Repo/env/CI:** monorepo (`/ingestion`, `/analytics`, `/dashboard`,
`/infra`, `CLAUDE.md`, `PROMPTS.md`); Postgres+TimescaleDB in Compose; Python
tooling (uv/poetry, ruff/black/mypy, pre-commit); Next.js scaffold + Prisma;
minimal CI (lint/type/smoke); `deploy.sh` + Hetzner target (bake env vars into
images before any user switch).
**0.2 Legal/ToS gating (before writing collectors):** `LEGAL.md` per-platform
data-rights table; Kalshi posture decision (+ consent email if needed);
Polymarket US-block / read-vs-trade caveat.

### Phase 1 — Validation Harness on Manifold (~5–7 days, parallelizable)
Thin Manifold client (`/v0/bets`, `/v0/markets`, `/v0/users`); normalize bets
into canonical schema; performance metrics v0; category-specialization score v0
(Herfindahl over category volume); candidate ranking harness (config-driven
thresholds). **Exit criterion:** the same code that ranks Manifold users will,
with a swapped ingestion adapter, rank Polymarket wallets.

### Phase 2 — Polymarket Data Ingestion (~7–10 days, critical path)
**2.1 Read paths:** official CLOB client + Data/Gamma wrappers; historical wallet
loader (idempotent, keyed on proxy wallet, captures resolution); optional bulk
historical seed.
**2.2 Live + on-chain (V2):** Data API ~2s poller for tracked wallets (paid RPC);
on-chain `OrderFilled` listener on CTF Exchange V2
`0xE111180000d2663C0091e4f400237545B87B996B` (filter by maker); reconciliation +
freshness monitor (dedup across both sources).

### Phase 3 — Trader Analytics Engine (~8–12 days, critical path)
**3.1 Port/harden primitives:** swap Phase 1 primitives onto Polymarket; robust
P&L with SPLIT/MERGE/REDEEM/CONVERSION; category taxonomy + specialization
scoring (Gamma tags).
**3.2 Candidate identification:** pool builder (≥500 wallets, baseline filters);
trackability pre-score (cadence + market depth + hold time); walk-forward
validation (out-of-sample edge + shuffled-label control).
**3.3 Surfacing:** whale/alert stream (terminal + Telegram).

### Phase 4 — The Two Core Experiments (~10–14 days, critical path, A∥B)
**4.1 Experiment A (Trackability, paper mode):** paper-fill simulator (price a
follower would get N s later vs book depth); latency-budget measurement
(poller vs on-chain; how often sub-second MEV front-runs); edge-decay curve
(1s/3s/10s per liquidity bucket); per-wallet trackability verdict over ≥10
candidates.
**4.2 Experiment B (Reverse-engineering):** external event-feed connectors
(economic calendar, sports, polling, news → `events` table); trade-timing
alignment (lead/lag distributions, information-leakage-style score); order-flow /
microstructure signatures (OFI / VPIN around candidate trades); per-wallet
"likely-informed + likely-source-category" verdict, validated out-of-sample
against an independent fair-value pricing baseline.

### Phase 5 — Kalshi Integration (flow-signal only; optional; legally gated; ~6–9 days)
Kalshi authenticated client (RSA-PSS); anonymous flow aggregation (per-market,
per-side notional + VWAP, parlay-filtered); **"why Kalshi can't be
trader-tracked" artifact**; single-name vs broad-based adverse-selection lens;
conditional paper execution venue prep (resting maker orders).

### Phase 6 — Cross-Platform Unification & Research Dashboard (~8–12 days)
Unified market abstraction (evaluate `pmxt`); cross-venue equivalent-market
matching (stretch); dashboard: wallet explorer + candidate leaderboard,
specialization + experiment-results views (D3), Kalshi flow monitor.

### Phase 7 — Hardening, Validation & Documentation (~6–10 days)
Collector resilience (retries/backoff/resumable cursors/RPC-failover); monitoring
+ alerting (freshness lag, job success, RPC error rate); **security review**
(dependency/supply-chain audit — this repo category has known malware — pinned
deps, dedicated zero-funds wallet, capped approvals); secrets handling; test
suite (golden-value math tests, ingestion idempotency, shuffled-label control);
documentation + findings write-up (the verdict on trackability vs
reverse-engineering).

## Risk Register

| # | Risk | L | I | Mitigation |
|---|------|---|---|------------|
| 1 | Copy-trading edge structurally too thin (MEV front-run, slippage/decay) | High | High | Treat Experiment A as measurement not product; paper-only; select slow/deep-liquidity wallets; pivot to "leader flow as one input". |
| 2 | Kalshi data structurally un-attributable | Certain | Med | Designed around it: aggregate flow only, with an explicit impossibility artifact. |
| 3 | Legal/ToS exposure (Kalshi ML/redistribution; Polymarket US block) | Med | High | Phase 0.2 gates before building; personal-research-only on Kalshi; paper-only execution; re-check jurisdiction before any live trade. |
| 4 | Polymarket V2 migration / API drift breaks ingestion | Med | High | Target V2 + pUSD from day one; prefer V2-aware `poly_data`; Data-API poller as graceful fallback; freshness monitor. |
| 5 | Reused OSS carries malware (documented key-theft) | Med | Critical | Phase 7.2 line-by-line audit, pinned deps, allow-listed egress, zero-funds wallet, capped approvals; never run a third-party execution path. |
| 6 | Survivorship/luck masquerading as skill (~16.8% net-positive) | High | Med | Walk-forward OOS validation + shuffled-label controls; ≥50 resolved trades; consistency across uncorrelated markets. |

## Open questions for refinement
1. **Live execution at all, ever?** Plan is paper-only; live needs a real legal
   answer first (Polymarket US block, Kalshi ToS).
2. **Dashboard vs notebooks?** Cutting the Next.js dashboard (6.2) for
   Jupyter/Streamlit saves ~1 week.
3. **Manifold prototype — keep or skip?** De-risks Phase 3 at ~5–7 days' cost.
4. **Depth of reverse-engineering** — timing-alignment only vs full microstructure
   + fair-value modeling.
5. **Codename** — keep "Bellwether" or rename?

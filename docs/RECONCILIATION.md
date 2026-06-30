# Reconciliation: existing code ↔ Bellwether plan, and the access finding

This connects the **Bellwether** plan (`docs/BELLWETHER.md`) to what already
exists in this repo, and records a finding that gates Bellwether's reuse-heavy
strategy.

## Finding that changes the plan: reference repos are unreachable from this session

Bellwether's tech-stack table and ~15 "Reuse:" notes depend on cloning and
reading third-party repos (`warproxxx/poly_data`, `Polymarket/py-clob-client`,
`Jon-Becker/prediction-market-analysis`, `pmxt-dev/pmxt`, `ent0n29/polybot`, …).
**None of them are reachable from the current Claude Code session:**

- Direct GitHub web/API → **403, org egress policy** (the agent proxy blocks
  `github.com`/`api.github.com`; the proxy README says do not route around it).
- GitHub MCP integration → **scoped to `devon-smith/tradertracker` only**.
- `add_repo` → **same-owner only**; cross-owner adds are unsupported in v1.

So in this environment we can't verify those repos exist, can't audit them, and
can't vendor anything from them. Two paths unblock it (see the manifest/README in
`references/`):

1. **Fresh session with the reference repos as initial sources** (the `add_repo`
   error explicitly suggests this), or a session whose egress allow-list includes
   GitHub. Then run `scripts/fetch_references.sh`.
2. **Proceed without them** — build the Bellwether services directly against the
   public HTTP/RPC APIs (which the existing code already does for the Data API,
   Gamma, Kalshi, and Manifold) and treat the repos as optional accelerants.

The knowledge base is scaffolded for path 1 (`references/manifest.json` +
`scripts/fetch_references.sh`) and everything is marked `verified: false` until a
fetch confirms it. Path 2 is fully viable: nothing built so far needed a single
third-party repo.

## What already exists vs. Bellwether phases

The current `tradertracker/` Python package already implements the *core
analytics primitives* Bellwether schedules across Phases 1–5 — just as a flat
package against live APIs, not the monorepo + Postgres/Timescale + dashboard
shape.

| Bellwether item | Status in this repo | Module |
|---|---|---|
| 1.1 Manifold client | ✅ built | `tradertracker/manifold/client.py` |
| 2.1 Polymarket Data/Gamma read paths | ✅ built (Data API + Gamma) | `polymarket/data_api.py`, `polymarket/gamma.py` |
| 2.1 Historical wallet loader | ◐ partial (paginates; no DB persistence yet) | `data_api.iter_trades` |
| 2.2 On-chain `OrderFilled` V2 listener | ✗ not built (Phase 3 in SCOPE.md; needs paid RPC) | — |
| 3.1 Performance metrics / P&L | ◐ partial (heuristic win-rate; no SPLIT/MERGE/REDEEM) | `polymarket/wallet_scoring.py` |
| 3.1 Category specialization score | ✅ built (slug-prefix proxy; Gamma-tag join TODO) | `wallet_scoring.py`, `analytics/specialization.py` |
| 3.2 Candidate ranking + thresholds | ✅ built | `wallet_scoring.rank_wallets` |
| 3.2 Walk-forward / OOS validation | ✗ not built | — |
| 4.1 Paper-fill / copy-latency simulator | ◐ partial (slippage replay; no order-book depth model) | `analytics/paper_trade.py` |
| 4.2 Reverse-engineering (timing/flow) | ✗ not built (research layer) | — |
| 5.1 Kalshi client (RSA-PSS) + flow aggregation | ✅ built | `kalshi/client.py`, `kalshi/flow.py` |
| 5.1.3 "Why Kalshi can't be tracked" artifact | ◐ documented in README/SCOPE; no standalone artifact | — |
| 6 Dashboard, 7 Hardening, Postgres/Timescale | ✗ not built | — |

**Takeaway:** the in-memory analytics core is ~60% of Bellwether Phases 1–5
already. The big un-built pieces are infrastructure (Postgres/TimescaleDB,
Docker/Hetzner, dashboard, schedulers) and two genuinely new capabilities
(on-chain V2 listener; Experiment B timing/flow analysis).

## The one structural fork to decide

The existing code is a **flat, in-memory Python package** (`pip install -e .`,
`tt` CLI, no database). Bellwether specifies a **monorepo with a persistence
layer** (`/ingestion`, `/analytics`, `/dashboard`, `/infra`; Postgres+Timescale;
Docker Compose). These aren't compatible layouts — continuing means picking one:

- **Evolve the flat package** — add a SQLite/Postgres cache under the current
  modules, keep the `tt` CLI, defer the dashboard. Fastest path to the Phase 3
  analytics + Phase 4 Experiment A verdict; least operational overhead.
- **Restructure into the Bellwether monorepo now** — move existing modules into
  `/analytics` + `/ingestion`, stand up Timescale + Compose first, then port.
  More upfront cost; matches the long-term operational target and the dashboard.

This is a real decision and it's yours — it sets the repo's whole shape. The
recommendation, given "value front-loaded / stop at any phase boundary," is to
**evolve the flat package through the Phase 3/4 verdict first**, then restructure
to the monorepo only if the verdict says the system is worth operationalizing.
But if you already know you want the always-on Hetzner stack regardless of the
verdict, restructuring now avoids a migration later.

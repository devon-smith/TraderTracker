# Project Scope — TraderTracker

This document maps the verified open-source landscape (audited against the
GitHub API on 2026-06-30) onto a five-phase build plan. Each phase has explicit
inputs, deliverables, and abandon-criteria so the project terminates cleanly if
the edge isn't real.

## Hard constraints (from the feasibility study)

1. **Polymarket is trackable; Kalshi is not.** Polymarket wallet data is public
   on-chain. Kalshi's public feed is anonymized — there is no API path to
   per-account identity. Every phase respects this asymmetry: Polymarket gets
   trader-tracking; Kalshi gets aggregate flow signals only.
2. **Copy-trading latency is structural, not engineering.** Sub-200ms MEV bots
   beat any API-based copier. Treat leader fills as a *signal*, not an
   instruction, unless paper-trade benchmarks prove otherwise.
3. **The Kalshi Data ToS restricts ML training and redistribution.** Any
   production use of Kalshi data for modeling needs written clearance.
4. **Most copy-trading repos are SEO spam or malware.** Pin to the
   verified-upstream list below; audit before running anything that signs
   transactions.

## Verified upstream repos (anchor list)

These are the repos confirmed via the GitHub API as on-target, well-maintained,
and not spam. Use them as building blocks rather than re-implementing.

| Repo | Role in our build |
|---|---|
| `Jon-Becker/prediction-market-analysis` | Reference dataset/framework for Polymarket analysis — use as a template |
| `warproxxx/poly_data` | V2-aware on-chain ingestion (`OrderFilled` reader) — adopt for Phase 3 |
| `SII-WANGZJ/Polymarket_data` | ~1.1B-row pre-processed dataset — bootstrap for analytics without scraping |
| `darrnhard/polymarket-smart-money` | Behavioral-analysis notebook — read as a template for our scoring layer |
| `pmxt-dev/pmxt` | "CCXT for prediction markets" — evaluate as the unified client layer |
| `Polymarket/py-clob-client` (+ `rs-clob-client`, `ts-sdk`) | Official CLOB clients — use for execution if/when we ever execute |
| `ent0n29/polybot` | Strategy reverse-engineering reference — read as research input for Phase 5 |
| `YichengYang-Ethan/oracle3` | Independent pricing engine (Wang Transform) — reference for Phase 5 |
| `al1enjesus/polymarket-whales` | Working whale-trade alerting loop — reference for Phase 3 |

Hosted tools worth using *as users* (not as dependencies): PolyWallet,
polymarketanalytics.com, the `@dunedata` and `alexmccullough` Dune dashboards.

## Phase 0 — Prototype on Manifold (now)

**Why:** Manifold's API exposes per-user bet history with no auth, no money at
risk, and no ToS friction. Validate the scoring + specialization + ranking logic
end-to-end before pointing it at real money.

**Inputs:**
- `tradertracker.manifold.ManifoldClient` (in repo)
- `tradertracker.polymarket.wallet_scoring` (reused with a Manifold adapter)

**Deliverables:**
- Adapter that turns Manifold bets into the same `Trade`/`Position` shape we use
  for Polymarket so the scoring code is platform-agnostic.
- A small report on whether the ranking finds the same top wallets the Manifold
  leaderboard shows (sanity check).

**Abandon if:** the scoring layer can't recover Manifold's leaderboard
top-decile within reasonable noise. That would mean the scoring math, not the
data, is the problem — and no platform switch will fix it.

## Phase 1 — Polymarket ingestion + smart-money ranking (built)

**Status:** ✅ shipped in v0.1 (`tradertracker.polymarket.data_api`, `gamma`,
`wallet_scoring`). CLI: `tt poly leaderboard | wallet | rank | categories`.

**Next within this phase:**
- Cache layer (SQLite) so we stop re-pulling the same wallet history every run.
- Backfill from `SII-WANGZJ/Polymarket_data` for wallets we can't get full
  history on via the Data API alone.

**Abandon if:** the smart-money filter (>=50 trades, >=55% WR, +PnL, >=10
resolved) returns either zero wallets or every wallet — both mean the
thresholds are mis-calibrated for current data and the filter has no
discriminative power.

## Phase 2 — Paper-trade benchmark (built — needs to be RUN)

**Status:** ✅ shipped in v0.1 (`tradertracker.analytics.paper_trade`). CLI:
`tt poly paper`.

**Next within this phase (the gating experiment for the whole project):**
- Run `tt poly paper` across the top 20 ranked wallets from Phase 1.
- Sweep `--slippage-bps` from 50 to 500 in steps of 50.
- Plot net-of-slippage PnL vs. slippage.

**Decision gate:**
- **Go on Phase 3** if there's a non-trivial wallet cohort where net PnL stays
  positive through 200 bps of slippage (≈ the realistic Data-API-polling
  latency band).
- **Pivot to signal-only** if the curve crosses zero below 100 bps for most
  wallets — that means real-time copy isn't viable and we should use leader
  activity as input to our own rules-based entries.

## Phase 3 — On-chain `OrderFilled` listener (deferred)

**Why this is the right next module if Phase 2 says "go":** Data API polling
floors at ~2s. The on-chain listener floors at ~2s (Polygon block time) but
without the polling jitter, and it scales to N wallets at constant cost.

**Inputs:**
- Paid Polygon RPC (Alchemy or QuickNode).
- CTF Exchange V2 contract `0xE111180000d2663C0091e4f400237545B87B996B` (and
  Neg Risk V2 `0xe2222d279d744050d28e00520010520000310F59`).
- `warproxxx/poly_data` as the reference implementation.

**Deliverable:** `tradertracker.polymarket.on_chain.OrderFilledListener` that
emits `Trade` records as the existing Data API client does, so downstream
scoring/paper-trade code doesn't change.

**Abandon if:** end-to-end detection→signal latency stays above ~3s after
tuning — at that point we're not measurably faster than the polling path and
the RPC cost isn't justified.

## Phase 4 — Kalshi anonymous flow signal (built — needs to be BENCHMARKED)

**Status:** ✅ shipped in v0.1 (`tradertracker.kalshi.flow`). CLI: `tt kalshi
flow`.

**Next within this phase:**
- Record `top_imbalances()` snapshots on a cron and resolve them against
  price moves N minutes later.
- Lift-vs.-imbalance curve: does a +0.5 imbalance over $X notional predict
  price drift in the same direction within the next 15 minutes?

**Decision gate:**
- **Productize** if the lift survives realistic transaction costs (the Kalshi
  taker fee `round_up(0.07 × C × P × (1−P))`).
- **Drop the Kalshi leg entirely** if it doesn't — we already know we can't
  track Kalshi traders, so without a working flow signal there's nothing left
  to do on that venue except use it as a pure execution destination, which is
  out of scope for *this* project.

## Phase 5 — Reverse-engineering analytics (research)

**Why last:** every previous phase produces a real-time signal. This one
produces explanations, which is valuable but not deployable. Build it once
Phases 1–4 are stable so it has good data to mine.

**Inputs (read, don't copy):**
- `ent0n29/polybot` (strategy reverse-engineering)
- `YichengYang-Ethan/oracle3` (independent pricing)
- ILS (Nechepurenko, arXiv 2605.02287); Bartlett & O'Hara on Kalshi adverse
  selection (SSRN 6615739); London Business School / Yale "informed minority"
  paper (SSRN, Apr 2026).

**Deliverables:**
- Timing-vs.-news classifier: align our tracked wallets' trade timestamps
  against an economic calendar, sports feeds, and polling release feeds; flag
  accounts whose volume systematically clusters in a window *before* specific
  data types.
- Per-wallet "likely-informed in category X" score, joined onto the Phase 1
  ranking.

**Abandon if:** the timing classifier flags either nobody or everybody as
informed — same diagnosis as Phase 1's threshold trap.

## Security posture

- Dedicated wallet for any phase that signs transactions; no unlimited token
  approvals (manage via Revoke.cash).
- Pin third-party repo SHAs in any code path that imports them; re-audit on
  bump.
- Treat `.env`, `secrets/`, and any signed-message material as private — all
  three are gitignored.
- Kalshi data: do not train models on it or redistribute it without written
  consent per the Kalshi Data ToS.

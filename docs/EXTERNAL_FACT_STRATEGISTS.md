# External-fact strategists: ranking skill, not luck

A pivot away from the latency/updown pool. Target markets that resolve against a
**knowable external fact** — elections, policy, sports series, crypto-event
resolution, geopolitics, and (only if they have depth) pop-culture like Spotify
streams / TV ratings. The edge on these markets is **information, modeling, or
discipline — not speed**, so the whole latency machinery is set aside and all
updown/intraday families are excluded up front.

This is **analysis on a new pool**, not new detection logic. It reuses the
existing resolution/P&L engine (`core.position_settlements`), market-family
normalization (`strategy.recurrence.market_family`), and the
significance/shuffled-control philosophy (`candidates.validation`). Code:
`analytics/bellwether_analytics/skill/` · CLI: `tt skill recon` / `tt skill rank`
· notebook: `analytics/notebooks/05_external_fact_skill.ipynb`.

## The funnel (per account, per category)

Every position is reduced (by the existing engine) to: **entry price** =
`net_cost / net_shares` = *the market's own implied probability at entry*, the
settled **outcome** (won/lost), realized **P&L**, capital, and timing.

0. **Exclude latency families.** `exclude_latency` drops any market whose family
   matches `updown`, `up-or-down`, `-5m`, `-15m`, `-1h`, `hourly`, … Their edge
   is speed and belongs to the other pool.

1. **Eligibility.** The account must have traded **≥ 10 DISTINCT resolved
   markets** in the category — independent events, not one market repeatedly
   (distinct market ids, so 20 trades in one market = 1). Below 10 is excluded.
   The distinct-market count travels with every account: a 10-market and a
   60-market verdict are **not** presented as equally proven.

2. **Persistence (required for ALL types).** Split the account's resolved history
   into equal-count time sub-periods; require net-positive edge in **most** of
   them. One windfall bet fails; repeated edge passes. This is the primary
   not-luck test.

3. **Classify by entry timing** (median entry price on the backed outcome):
   - **predictor** — median entry `< 0.65`: entered while the market was still
     uncertain (or against the eventual outcome). A forecasting edge.
   - **momentum-rider** — median entry `0.65–0.85`: entered *after* the market
     moved toward the outcome, but consistently picks the right movers. A
     timing/discipline edge ("jumps on winners").
   - **favorite-farmer** — median entry `≥ 0.85`: only ever high-probability
     positions, collecting the baseline. **No edge.**

4. **Type-appropriate skill test:**
   - **Predictors** must **beat their entry-price-implied win rate at
     significance**. Entry price is the market's probability, so this is a
     Poisson-binomial one-sided test — observed wins vs `Σ entry_price`, scaled
     by `Σ entry(1−entry)` — with `p < 0.05`. This is a genuine forecasting edge,
     **not** "win rate > 55%" (which a favorite-farmer clears trivially).
   - **Momentum-riders** are judged on **persistence + positive ROI** across many
     markets. By construction they enter near the price and cannot beat the
     market on calibration, so beating it is not required — consistent profitable
     trend-capture is.
   - **Favorite-farmers** are **flagged no-edge and dropped**: their win rate ≈
     their entry-implied rate with no excess. This is the lucky-looking reject.

5. **Rank survivors WITHIN each type** by both **P&L** (opportunity magnitude)
   and **% return** (edge quality). Both are reported.

## Controls

- **Market-calibrated null** (`null_control`): redraw every position's outcome
  from `Bernoulli(entry_price)` — i.e. *assume the market is perfectly calibrated
  and no one has an edge* — and re-run the whole funnel many times. Under this
  null the expected P&L of every position is exactly zero and predictors beat the
  market only at ~the significance level. A real skilled cohort must exceed the
  null's survivor count; a no-skill population collapses to chance.
- **Out-of-sample discipline.** Skill is evaluated on resolved history. If any
  threshold is tuned, keep a train/test split (the persistence sub-periods and
  the `candidates.walk_forward` helper both support this).

## Information vs modeling (a hook, not an analysis)

Each survivor carries `edge_source_hint`:
- **information** — predictor entering *below* the market (median entry `< 0.5`)
  or early in the market's life: looks like they knew before the public signal.
- **modeling** — entering once the market is already converging: looks like a
  fair-value model, not private information.

This is a **flag only**, a hook for later reverse-engineering (Bellwether
Phase 4.2 / Experiment B). No timing-vs-news analysis is built here.

## Running it on a real pool

Recon and ranking run against whatever Polymarket data is loaded in the canonical
tables; `exclude_latency` guarantees updown markets can't contaminate the
external-fact population.

```bash
# 1. build an external-fact pool (on the VM, with egress + a persistent DB)
tt poly seed-leaderboard 500          # or load specific wallets: tt poly load 0x...
tt poly load 0x<wallet> --max-markets 400   # full history incl. resolution

# 2. Step-0 recon — studyable population per category (thin ones flagged)
tt skill recon --platform polymarket

# 3. the funnel + ranking + null control
tt skill rank --platform polymarket --min-markets 10
```

`category_recon` reports, per external-fact category: number of resolved markets,
the resolved-market time span, the distribution of markets-per-account, how many
accounts clear eligibility, and a **studyable / no-studyable-population** flag —
so thin categories (likely Spotify/TV) are flagged rather than forced.

### Targeting the seed (follow-up)

The generic seeders (`tt poly seed-leaderboard`, recent-volume fallback) fill the
pool with active wallets; recon then tells you which categories are deep enough.
A tighter seed — enumerate recent **resolved** Gamma markets in the target
categories (`GammaClient.markets(closed=True, tag=…)`) and pull each market's
**top holders** (`DataAPIClient.holders(market=…)`) to harvest specialist
accounts — is a small, well-scoped ingestion follow-up. It's deferred here
because it needs live egress + a persistent DB to validate the holders-response
shape (unavailable in the current sandbox; available on the local VM).

## Status

- `analytics/bellwether_analytics/skill/` — funnel, recon, null control, ranking.
- Tests: `analytics/tests/test_skill_external_fact.py` — predictor beats the
  market, momentum survives on persistence+ROI (without beating it),
  favorite-farmer dropped, thin/single-market/latency accounts excluded, and the
  null control collapses the edge. Green + ruff clean.
- The live per-category numbers are produced by running `tt skill recon` / `tt
  skill rank` against a loaded pool on the VM.

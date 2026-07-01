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

   Each account is reduced to **one dominant position per market** (the outcome it
   committed the most capital to), so dust/hedge legs don't pull the median entry.

3. **Classify by entry timing** (median entry price on the backed outcome):
   - **predictor** — median entry `0.15–0.65`: entered while the market was still
     uncertain. A forecasting edge.
   - **momentum-rider** — median entry `0.65–0.85`: entered *after* the market
     moved toward the outcome, but consistently picks the right movers. A
     timing/discipline edge ("jumps on winners").
   - **favorite-farmer** — median entry `≥ 0.85`: only ever high-probability
     positions, collecting the baseline. **No edge — dropped.**
   - **longshot** — median entry `< 0.15`: dust/longshot farming (near-dead
     outcomes bought for cents). **No forecasting edge — dropped.**

4. **Type-appropriate skill test:**
   - **Predictors** must **beat their entry-price-implied win rate at
     significance**. Entry price is the market's probability, so this is a
     Poisson-binomial one-sided test — observed wins vs `Σ entry_price`, scaled
     by `Σ entry(1−entry)`. This is a genuine forecasting edge, **not** "win rate
     > 55%" (which a favorite-farmer clears trivially).
   - **Momentum-riders** must **beat the random-entry null**: did their realized
     P&L exceed what random entry at the same prices would yield? Under the
     market-calibrated null a position's P&L has mean 0 and variance
     `net_shares² · p(1−p)`, giving a one-sided P&L z-test. This operationalizes
     "picks winners-in-motion better than random entry into moving markets" — a
     positive ROI *within noise* is **not** an edge (see the null control).
   - **Favorite-farmers and longshots** are **flagged no-edge and dropped.**
   - **Multiple-testing correction.** Across the many eligible accounts, the
     type-appropriate p-values are gated by **Benjamini–Hochberg FDR** (`q=0.05`),
     so a no-skill null produces ~0 survivors instead of the `q·N` false positives
     a raw per-account threshold would wave through. **Confidence scales with the
     distinct-market count** — 10-market and 60-market accounts are never treated
     as equally proven, and the test has correspondingly more power for the latter.

5. **Rank survivors WITHIN each type** by both **P&L** (opportunity magnitude)
   and **% return** (edge quality). Both are reported.

## Controls

- **Market-calibrated null** (`null_control`): redraw every position's outcome
  from `Bernoulli(entry_price)` — i.e. *assume the market is perfectly calibrated
  and no one has an edge* — and re-run the whole FDR-gated funnel many times.
  Under this null the expected P&L of every position is exactly zero. A real
  skilled cohort must exceed the null's survivor count; because of the FDR gate a
  no-skill population yields ~0 survivors.
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

The dedicated seeder `scripts/external_fact_pool.py` does exactly this against the
live APIs (no DB required — the funnel takes a DataFrame): it enumerates recent
**resolved** Gamma markets in the target categories (updown excluded), pulls
market-level `/trades` for the population census, and pulls per-wallet
own-history for the eligible specialists (their true entry prices — market-level
`/trades` returns only near-resolution fills and ignores ordering/time params, so
it can't drive the entry-timing classification). `build` → `specialists` →
`report`.

## First real run (REST, live Polymarket) — findings

Ran `scripts/external_fact_pool.py` against the live APIs (no DB).

**Pool.** 219 recent **resolved** external-fact markets (updown excluded),
**655,344 trades / 224,775 wallets**, spanning **2024-08 → 2026-07**.

**Step 0 — studyable population** (market-level census):

| category | resolved markets | accounts | eligible (≥10 mkts) | studyable |
|---|--:|--:|--:|:--|
| sports | 109 | 117,714 | 231 | ✅ |
| politics | 62 | 65,317 | 115 | ✅ |
| economics | 42 | 46,804 | 52 | ✅ |
| crypto | 6 | 9,767 | 0 | ❌ no studyable population (thin) |

Max distinct resolved markets by one account: **71** (sports). Crypto is flagged
thin rather than forced (only event markets survive the updown exclusion).

**Funnel.** Own-history for the 363 candidate specialists → 347 wallets /
52,588 universe fills. **237 accounts** cleared eligibility (≥10 distinct resolved
markets in a category). Type mix:

| type | n | verdict |
|---|--:|---|
| longshot (median entry < 0.15) | 189 | dropped — dust/longshot farming |
| favorite-farmer (≥ 0.85) | 37 | dropped — collects the baseline, no edge |
| momentum-rider (0.65–0.85) | 8 | tested vs random-entry null |
| predictor (0.15–0.65) | 3 | tested vs entry-implied win rate |

**Verdict: 0 accounts demonstrate skill beyond luck.** Of the 11 testable
predictor/momentum accounts, 2 predictors reached *nominal* `p ≈ 0.034–0.036`
(e.g. a politics account, 20 markets, median entry 0.58, +$143k, +8.8% ROI) — but
**none survive the Benjamini–Hochberg FDR correction** across 237 accounts. The
**market-calibrated null control agrees**: real survivors **0** vs null mean
**0.22**, and real predictors-beat-market **0** vs null **0.0**. The dominant
visible behavior on external-fact markets is **favorite-farming and longshot
farming**, neither of which is an edge.

**Honest caveats (why this is a floor, not the last word):**
- **Statistical power.** Specialists here hold 10–35 resolved markets; certifying
  a forecasting edge at FDR-corrected significance needs more independent events.
  The two nominal near-misses are exactly what you'd chase with a deeper history.
- **REST capture.** Per-wallet history is pagination-capped (~last few thousand
  trades), so very old entries for hyperactive wallets are missed; P&L is
  trade-settled (no REDEEM events, though resolution payout is modelled
  correctly). A persistent DB + on-chain backfill on the VM widens both.
- This is the **survivorship-vs-skill result the project predicted** (Risk #6):
  once persistence, a type-appropriate null test, and multiple-testing correction
  are enforced, the visible "smart money" on external-fact markets is not
  distinguishable from luck.

**Reproduce:** `python scripts/external_fact_pool.py all` (build → specialists →
report). Cache lands in `.cache/` (gitignored).

## Status

- `analytics/bellwether_analytics/skill/` — funnel, recon, FDR-gated skill tests,
  null control, ranking. `scripts/external_fact_pool.py` — the live seeder + run.
- Tests: `analytics/tests/test_skill_external_fact.py` — predictor beats the
  market, momentum survives *only* when it beats the random-entry null, a
  lucky-momentum (positive ROI within noise) is dropped, favorite-farmer/longshot
  dropped, thin/single-market/latency accounts excluded, and the null control
  collapses the edge. Green + ruff clean.
- First real run executed against live Polymarket (above); numbers reproduce via
  the script, and `tt skill recon` / `tt skill rank` run the same funnel against a
  DB-loaded pool on the VM.

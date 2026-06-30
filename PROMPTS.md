# Prompt & decision log

A running log of significant requests and the decisions made, so the project's
direction is reconstructable.

## 2026-06-30

- **Seed:** Feasibility study on tracking/copying/reverse-engineering top
  prediction-market traders (Polymarket, Kalshi, others). Conclusion: Polymarket
  trackable; Kalshi anonymous; copy-edge thin; reverse-engineering is forensic.
- **Build v0.1:** flat `tradertracker/` Python package — Data API + Gamma + Kalshi
  flow + Manifold clients, wallet scoring, paper-trade sim, `tt` CLI. 9 tests.
- **Reference repos:** could not be fetched/verified — session egress blocks
  GitHub, the integration is scoped to this repo, and `add_repo` is same-owner
  only. Captured intent in `references/manifest.json` + `scripts/fetch_references.sh`
  (verify/pin where GitHub is reachable); corrected earlier "verified" claims.
- **Bellwether plan** received (`docs/BELLWETHER.md`). Decisions:
  - Reference-repo access → bring them in via a **separate session** with the
    repos as sources; build here directly against the public APIs.
  - Structure → **restructure into the monorepo now** (ingestion/ + analytics/ +
    dashboard/ + infra/; Postgres/TimescaleDB).
  - Research surface → **build the Next.js dashboard**.
  - (Advisory) paper-only until the Phase 4 verdict; reverse-engineering starts
    light; codename "Bellwether" kept.
- **Restructure landed:** two Python packages (analytics → ingestion), canonical
  TimescaleDB schema (verified: extension + hypertable + idempotent + dedup +
  async insert), Compose/Caddy/deploy/CI, Next.js dashboard scaffold.

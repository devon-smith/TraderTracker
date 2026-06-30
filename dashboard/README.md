# Bellwether dashboard

Read-only Next.js (App Router) research surface over the canonical ingestion DB.
Prisma is used purely as a typed read client; migrations are owned by
`infra/db/migrations/*.sql`, not `prisma migrate`.

## Routes

| Route | What |
|---|---|
| `/` | Landing + links |
| `/leaderboard` | Ranked smart-money wallets from `candidate_score` |
| `/health` | DB connectivity + row counts |
| `/api/health` | JSON liveness probe (200 ok / 503 on DB error) |

## Dev

```bash
npm install            # postinstall runs `prisma generate`
npm run dev            # http://localhost:3000  (needs DATABASE_URL)
npm run build          # prisma generate && next build (standalone output)
npm run lint
```

`DATABASE_URL` points at the TimescaleDB from `infra/docker-compose.yml`
(e.g. `postgresql://bellwether:bellwether@localhost:5432/bellwether`).

## Note on building in a restricted-egress sandbox

`prisma generate` / `prisma validate` download the Prisma engine from
`binaries.prisma.sh`. In environments where that host is blocked by an egress
policy, those steps fail with `ECONNRESET` and `next build`'s type-check can't
resolve `@prisma/client`. The npm install, ESLint, and SWC compile steps all
pass offline; the full build + type-check run in CI (the `dashboard` job), which
has unrestricted network. This is the same class of egress limitation documented
for the reference repos in `../references/README.md`.

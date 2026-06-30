# Reference knowledge base

Curated upstream repos we want to learn from or reuse, plus the tooling to
materialize them.

## ⚠️ Verification status: UNVERIFIED in the authoring session

The manifest was created in a Claude Code session whose **egress policy blocks
GitHub** (`api.github.com` and `github.com` return 403 from the agent proxy) and
whose GitHub integration is **scoped to `devon-smith/tradertracker` only**.
`add_repo` is also same-owner-only, so third-party repos can't be pulled in.

**Consequence:** none of the repos in `manifest.json` could be read, audited, or
even confirmed to exist from that session. Every entry has `verified: false`, and
the star counts / descriptions from the earlier research report are recorded as
**unverified claims**, not facts.

## How to populate it (run where GitHub is reachable)

Either start a fresh Claude Code session with the reference repos as initial
sources, or run this on any machine with GitHub access:

```bash
scripts/fetch_references.sh
```

That clones each repo into `references/_cache/` (gitignored), records resolved
commit SHAs in `references/pinned.txt` (commit that), and prints `NOT FOUND` for
any repo that doesn't exist — which is how the manifest gets verified.

## Rules before importing anything

1. **Audit first.** Any entry with `security_audit_required: true` signs
   transactions or handles keys. This repo category has documented
   credential-theft incidents. Read it line-by-line; never run its execution
   path. Reuse *architecture and read-only patterns* only.
2. **Pin it.** Import against the SHA in `pinned.txt`, not `main`.
3. **Check the license.** Every `license` field is `UNKNOWN` until fetched.
   Confirm it permits our use before vendoring code (vs. merely reading it).
4. **Respect platform ToS.** The Kalshi Data ToS restricts ML-training and
   redistribution — relevant to anything in the `execution_only_kalshi` bucket.

## Files

| File | Purpose |
|---|---|
| `manifest.json` | Curated intent: which repos, what for, which SCOPE/Bellwether phase |
| `pinned.txt` | Generated: resolved SHAs (and NOT_FOUND markers) after a fetch |
| `_cache/` | Generated: shallow clones (gitignored) |
| `../scripts/fetch_references.sh` | Clone + verify + pin |

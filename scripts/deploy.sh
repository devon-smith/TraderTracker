#!/usr/bin/env bash
# Deploy Bellwether to a single Hetzner-style VPS over SSH.
# Mirrors the push -> SSH -> pull -> compose up flow.
#
# Usage:
#   DEPLOY_HOST=user@1.2.3.4 DEPLOY_DIR=/opt/bellwether ./scripts/deploy.sh
#
# Requirements on the host: git, docker, docker compose, and a populated .env
# in $DEPLOY_DIR (env vars are read at build/run time — never committed).

set -euo pipefail

HOST="${DEPLOY_HOST:?set DEPLOY_HOST=user@host}"
DIR="${DEPLOY_DIR:-/opt/bellwether}"
BRANCH="${DEPLOY_BRANCH:-$(git rev-parse --abbrev-ref HEAD)}"
REMOTE="${DEPLOY_GIT_REMOTE:-origin}"
PROFILE_ARGS="${DEPLOY_COMPOSE_PROFILES:+--profile $DEPLOY_COMPOSE_PROFILES}"

echo "→ pushing $BRANCH to $REMOTE"
git push "$REMOTE" "$BRANCH"

echo "→ deploying to $HOST:$DIR (branch $BRANCH)"
ssh "$HOST" bash -se <<EOF
set -euo pipefail
if [ ! -d "$DIR/.git" ]; then
  echo "ERROR: $DIR is not a git checkout. Clone the repo there and add .env first." >&2
  exit 1
fi
cd "$DIR"
git fetch --all --prune
git checkout "$BRANCH"
git reset --hard "origin/$BRANCH"
if [ ! -f .env ]; then
  echo "ERROR: $DIR/.env is missing. Create it from .env.example before deploying." >&2
  exit 1
fi
# Build with env present so build-time vars are baked in before any USER switch.
docker compose -f infra/docker-compose.yml $PROFILE_ARGS up -d --build
docker compose -f infra/docker-compose.yml ps
EOF

echo "✓ deploy complete"

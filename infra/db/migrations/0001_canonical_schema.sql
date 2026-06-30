-- Bellwether canonical schema (idempotent; safe to re-apply).
-- Applied in lexical order by bellwether_ingestion.db.Database.apply_migrations
-- and by `tt db init`. Everything here must run inside a single transaction, so
-- no continuous aggregates (they can't be created in a txn) — use the views below.

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ---------------------------------------------------------------------------
-- Reference entities
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS wallet (
    platform    TEXT NOT NULL,
    wallet_id   TEXT NOT NULL,
    username    TEXT,
    first_seen  TIMESTAMPTZ,
    last_seen   TIMESTAMPTZ,
    PRIMARY KEY (platform, wallet_id)
);

CREATE TABLE IF NOT EXISTS market (
    platform        TEXT NOT NULL,
    market_id       TEXT NOT NULL,
    condition_id    TEXT,
    slug            TEXT,
    title           TEXT,
    category        TEXT,
    closed          BOOLEAN DEFAULT FALSE,
    resolved_outcome TEXT,
    resolution_ts   TIMESTAMPTZ,
    PRIMARY KEY (platform, market_id)
);

-- ---------------------------------------------------------------------------
-- Trade time-series (hypertable, partitioned on ts)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trade (
    platform      TEXT NOT NULL,
    wallet_id     TEXT,
    market_id     TEXT,
    condition_id  TEXT,
    asset         TEXT,
    side          TEXT,
    size          DOUBLE PRECISION,
    price         DOUBLE PRECISION,
    notional      DOUBLE PRECISION,
    outcome       TEXT,
    outcome_index INTEGER,
    tx_hash       TEXT,
    ts            TIMESTAMPTZ NOT NULL
);

SELECT create_hypertable('trade', 'ts', if_not_exists => TRUE, migrate_data => TRUE);

-- Dedup key. Must include the partitioning column (ts) for a hypertable unique
-- index. tx_hash is the platform's natural id (Polygon tx for Polymarket, bet id
-- for Manifold); asset + ts disambiguate multiple fills within one tx.
CREATE UNIQUE INDEX IF NOT EXISTS ux_trade_dedup
    ON trade (platform, tx_hash, asset, ts);

CREATE INDEX IF NOT EXISTS ix_trade_wallet_ts ON trade (platform, wallet_id, ts DESC);
CREATE INDEX IF NOT EXISTS ix_trade_market_ts ON trade (platform, market_id, ts DESC);

-- ---------------------------------------------------------------------------
-- Position snapshots
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS position (
    platform     TEXT NOT NULL,
    wallet_id    TEXT NOT NULL,
    condition_id TEXT,
    asset        TEXT,
    size         DOUBLE PRECISION,
    avg_price    DOUBLE PRECISION,
    realized_pnl DOUBLE PRECISION,
    cash_pnl     DOUBLE PRECISION,
    cur_price    DOUBLE PRECISION,
    redeemable   BOOLEAN,
    snapshot_ts  TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_position_wallet ON position (platform, wallet_id, snapshot_ts DESC);

-- ---------------------------------------------------------------------------
-- Derived tables
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS candidate_score (
    platform           TEXT NOT NULL,
    wallet_id          TEXT NOT NULL,
    trade_count        INTEGER,
    total_volume       DOUBLE PRECISION,
    total_pnl          DOUBLE PRECISION,
    win_rate           DOUBLE PRECISION,
    resolved_positions INTEGER,
    top_category       TEXT,
    concentration      DOUBLE PRECISION,
    score              DOUBLE PRECISION,
    computed_ts        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (platform, wallet_id)
);

CREATE TABLE IF NOT EXISTS kalshi_flow (
    ticker          TEXT NOT NULL,
    yes_notional    DOUBLE PRECISION,
    no_notional     DOUBLE PRECISION,
    imbalance       DOUBLE PRECISION,
    block_notional  DOUBLE PRECISION,
    window_start    TIMESTAMPTZ,
    window_end      TIMESTAMPTZ,
    computed_ts     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, window_end)
);

-- External event feeds for Experiment B (timing-vs-news analysis).
CREATE TABLE IF NOT EXISTS event_feed (
    id        BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    category  TEXT NOT NULL,
    name      TEXT,
    ts        TIMESTAMPTZ NOT NULL,
    source    TEXT,
    payload   JSONB
);

-- Job run history for the scheduler.
CREATE TABLE IF NOT EXISTS job_run (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    job         TEXT NOT NULL,
    status      TEXT NOT NULL,
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at TIMESTAMPTZ,
    detail      JSONB
);

-- ---------------------------------------------------------------------------
-- Convenience views (plain views — txn-safe, unlike continuous aggregates)
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW trade_daily_wallet AS
SELECT
    platform,
    wallet_id,
    time_bucket('1 day', ts) AS day,
    count(*)                 AS trades,
    sum(notional)            AS volume,
    sum(size)                AS shares
FROM trade
GROUP BY platform, wallet_id, time_bucket('1 day', ts);

"""Canonical SQLAlchemy 2.x models — the single contract every ingester writes into.

Time-series facts (`trade`, `position_event`, `event`) are TimescaleDB hypertables
partitioned on `ts`, so their primary keys include `ts`. `trade`/`position_event`
use a natural (`dedup_key`, `ts`) primary key: re-ingesting the same source row
collides on the PK, which gives both idempotency (via ON CONFLICT) and a hard
unique-violation for plain inserts.
"""

from __future__ import annotations

import datetime as dt
import enum
from typing import Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Platform(str, enum.Enum):
    manifold = "manifold"
    polymarket = "polymarket"
    kalshi = "kalshi"


class Side(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"


class Source(str, enum.Enum):
    data_api = "data_api"
    onchain = "onchain"
    manifold_api = "manifold_api"


class PositionEventType(str, enum.Enum):
    SPLIT = "SPLIT"
    MERGE = "MERGE"
    REDEEM = "REDEEM"
    CONVERSION = "CONVERSION"
    REWARD = "REWARD"


# Shared enum type objects (reused across columns so the PG type is created once).
platform_type = Enum(Platform, name="platform_enum")
side_type = Enum(Side, name="side_enum")
source_type = Enum(Source, name="source_enum")
position_event_type = Enum(PositionEventType, name="position_event_type")


def _ts() -> Mapped[dt.datetime]:
    return mapped_column(DateTime(timezone=True), primary_key=True)


class Wallet(Base):
    __tablename__ = "wallet"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    platform: Mapped[Platform] = mapped_column(platform_type, nullable=False)
    external_id: Mapped[str] = mapped_column(String, nullable=False)
    handle: Mapped[Optional[str]] = mapped_column(String)
    pseudonym: Mapped[Optional[str]] = mapped_column(String)
    first_seen: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("platform", "external_id", name="uq_wallet_platform_external"),
    )


class Market(Base):
    __tablename__ = "market"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    platform: Mapped[Platform] = mapped_column(platform_type, nullable=False)
    external_id: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(Text)
    slug: Mapped[Optional[str]] = mapped_column(String)
    category: Mapped[Optional[str]] = mapped_column(String)
    raw_category: Mapped[Optional[str]] = mapped_column(String)
    created_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))
    resolution: Mapped[Optional[str]] = mapped_column(String)
    is_multi_outcome: Mapped[bool] = mapped_column(default=False)

    __table_args__ = (
        UniqueConstraint("platform", "external_id", name="uq_market_platform_external"),
        Index("ix_market_category", "category"),
    )


class Trade(Base):
    __tablename__ = "trade"
    dedup_key: Mapped[str] = mapped_column(String, primary_key=True)
    ts: Mapped[dt.datetime] = _ts()
    platform: Mapped[Platform] = mapped_column(platform_type, nullable=False)
    wallet_id: Mapped[Optional[int]] = mapped_column(ForeignKey("wallet.id"))
    market_id: Mapped[Optional[int]] = mapped_column(ForeignKey("market.id"))
    side: Mapped[Optional[Side]] = mapped_column(side_type)
    outcome: Mapped[Optional[str]] = mapped_column(String)
    size: Mapped[Optional[float]] = mapped_column(Float)
    price: Mapped[Optional[float]] = mapped_column(Float)
    notional: Mapped[Optional[float]] = mapped_column(Float)
    tx_hash: Mapped[Optional[str]] = mapped_column(String)
    log_index: Mapped[Optional[int]] = mapped_column(Integer)
    source: Mapped[Source] = mapped_column(source_type, nullable=False)

    __table_args__ = (
        Index("ix_trade_wallet_ts", "wallet_id", "ts"),
        Index("ix_trade_market_ts", "market_id", "ts"),
    )


class PositionEvent(Base):
    __tablename__ = "position_event"
    dedup_key: Mapped[str] = mapped_column(String, primary_key=True)
    ts: Mapped[dt.datetime] = _ts()
    platform: Mapped[Platform] = mapped_column(platform_type, nullable=False)
    wallet_id: Mapped[Optional[int]] = mapped_column(ForeignKey("wallet.id"))
    market_id: Mapped[Optional[int]] = mapped_column(ForeignKey("market.id"))
    event_type: Mapped[PositionEventType] = mapped_column(position_event_type, nullable=False)
    size: Mapped[Optional[float]] = mapped_column(Float)
    value: Mapped[Optional[float]] = mapped_column(Float)
    tx_hash: Mapped[Optional[str]] = mapped_column(String)
    log_index: Mapped[Optional[int]] = mapped_column(Integer)

    __table_args__ = (Index("ix_posevt_wallet_ts", "wallet_id", "ts"),)


class Event(Base):
    """External information feed (economic calendar, sports results, ...)."""

    __tablename__ = "event"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    ts: Mapped[dt.datetime] = _ts()
    category: Mapped[str] = mapped_column(String, nullable=False)
    event_type: Mapped[Optional[str]] = mapped_column(String)
    title: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[Optional[str]] = mapped_column(String)
    payload: Mapped[Optional[dict]] = mapped_column(JSONB)

    __table_args__ = (Index("ix_event_category_ts", "category", "ts"),)


class IngestionRun(Base):
    """Job bookkeeping for resumable, idempotent ingestion."""

    __tablename__ = "ingestion_run"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    target: Mapped[Optional[str]] = mapped_column(String)
    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    finished_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String, nullable=False, default="running")
    rows_written: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cursor: Mapped[Optional[str]] = mapped_column(String)
    error: Mapped[Optional[str]] = mapped_column(Text)


class CandidateScore(Base):
    """Derived per-wallet ranking (written by the analytics candidate pool)."""

    __tablename__ = "candidate_score"
    platform: Mapped[Platform] = mapped_column(platform_type, primary_key=True)
    wallet_id: Mapped[str] = mapped_column(String, primary_key=True)  # external id
    trade_count: Mapped[Optional[int]] = mapped_column(Integer)
    total_volume: Mapped[Optional[float]] = mapped_column(Float)
    total_pnl: Mapped[Optional[float]] = mapped_column(Float)
    win_rate: Mapped[Optional[float]] = mapped_column(Float)
    resolved_positions: Mapped[Optional[int]] = mapped_column(Integer)
    top_category: Mapped[Optional[str]] = mapped_column(String)
    concentration: Mapped[Optional[float]] = mapped_column(Float)
    score: Mapped[Optional[float]] = mapped_column(Float)
    computed_ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class KalshiFlow(Base):
    """Derived per-market anonymous flow snapshot (Kalshi; Phase 5)."""

    __tablename__ = "kalshi_flow"
    ticker: Mapped[str] = mapped_column(String, primary_key=True)
    window_end: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    yes_notional: Mapped[Optional[float]] = mapped_column(Float)
    no_notional: Mapped[Optional[float]] = mapped_column(Float)
    imbalance: Mapped[Optional[float]] = mapped_column(Float)
    block_notional: Mapped[Optional[float]] = mapped_column(Float)
    window_start: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True))
    computed_ts: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# Tables that become TimescaleDB hypertables (partitioned on ts).
HYPERTABLES = ("trade", "position_event", "event")

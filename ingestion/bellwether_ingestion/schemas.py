"""Canonical data models shared across ingestion and analytics.

These deliberately live in the ingestion package (the producer of the data) and
are imported by analytics (the consumer). Keeping them separate from the HTTP
clients lets analytics depend on the shapes without dragging in httpx.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class Trade(BaseModel):
    proxyWallet: str
    side: str
    asset: str
    conditionId: str
    size: float
    price: float
    timestamp: int
    title: Optional[str] = None
    slug: Optional[str] = None
    outcome: Optional[str] = None
    outcomeIndex: Optional[int] = None
    name: Optional[str] = None
    pseudonym: Optional[str] = None
    transactionHash: Optional[str] = None

    @property
    def notional(self) -> float:
        return self.size * self.price


class Position(BaseModel):
    proxyWallet: Optional[str] = None
    asset: Optional[str] = None
    conditionId: Optional[str] = None
    size: float
    avgPrice: float = 0.0
    initialValue: float = 0.0
    currentValue: float = 0.0
    cashPnl: float = 0.0
    percentPnl: float = 0.0
    realizedPnl: float = 0.0
    curPrice: float = 0.0
    redeemable: bool = False
    title: Optional[str] = None
    slug: Optional[str] = None
    outcome: Optional[str] = None


class Activity(BaseModel):
    proxyWallet: Optional[str] = None
    type: str
    timestamp: int
    asset: Optional[str] = None
    conditionId: Optional[str] = None
    size: Optional[float] = None
    usdcSize: Optional[float] = None  # USDC value (the cash leg of the event)
    price: Optional[float] = None
    side: Optional[str] = None
    outcome: Optional[str] = None
    transactionHash: Optional[str] = None
    title: Optional[str] = None
    slug: Optional[str] = None

"""Polymarket Data API client.

Endpoints:
  GET /trades?user=<wallet>      — per-wallet trade history
  GET /positions?user=<wallet>   — current holdings
  GET /activity?user=<wallet>    — TRADE | SPLIT | MERGE | REDEEM | REWARD | CONVERSION
  GET /holders                   — top holders per market
  GET /value                     — total open position value

Note: the `user` parameter accepts either the EOA or proxy address; responses key on
the proxy (Gnosis Safe) wallet that actually holds positions.
"""

from __future__ import annotations

import os
import time
from typing import Iterator, Literal, Optional

import httpx
from pydantic import BaseModel, Field

DEFAULT_BASE = os.environ.get("POLYMARKET_DATA_API", "https://data-api.polymarket.com")


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
    price: Optional[float] = None
    side: Optional[str] = None
    transactionHash: Optional[str] = None
    title: Optional[str] = None
    slug: Optional[str] = None


class DataAPIClient:
    """Synchronous Polymarket Data API client with automatic pagination."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE,
        timeout: float = 20.0,
        client: Optional[httpx.Client] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=timeout, headers={"User-Agent": "tradertracker/0.1"})

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "DataAPIClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _get(self, path: str, params: dict) -> list[dict]:
        url = f"{self.base_url}{path}"
        # Strip None values so the API doesn't reject them as bad input.
        params = {k: v for k, v in params.items() if v is not None}
        resp = self._client.get(url, params=params)
        if resp.status_code == 429:
            time.sleep(1.0)
            resp = self._client.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and "data" in data:
            data = data["data"]
        return data if isinstance(data, list) else []

    def trades(
        self,
        user: str,
        market: Optional[str] = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[Trade]:
        raw = self._get(
            "/trades",
            {"user": user, "market": market, "limit": limit, "offset": offset},
        )
        return [Trade.model_validate(t) for t in raw]

    def iter_trades(
        self,
        user: str,
        market: Optional[str] = None,
        page_size: int = 500,
        max_pages: int = 200,
    ) -> Iterator[Trade]:
        """Paginate through a wallet's complete trade history."""
        offset = 0
        for _ in range(max_pages):
            batch = self.trades(user=user, market=market, limit=page_size, offset=offset)
            if not batch:
                return
            for t in batch:
                yield t
            if len(batch) < page_size:
                return
            offset += len(batch)

    def positions(self, user: str, limit: int = 500) -> list[Position]:
        raw = self._get("/positions", {"user": user, "limit": limit})
        return [Position.model_validate(p) for p in raw]

    def activity(
        self,
        user: str,
        side: Optional[Literal["BUY", "SELL"]] = None,
        sort_by: Optional[str] = None,
        start: Optional[int] = None,
        end: Optional[int] = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[Activity]:
        raw = self._get(
            "/activity",
            {
                "user": user,
                "side": side,
                "sortBy": sort_by,
                "start": start,
                "end": end,
                "limit": limit,
                "offset": offset,
            },
        )
        return [Activity.model_validate(a) for a in raw]

    def holders(self, market: str, limit: int = 100) -> list[dict]:
        return self._get("/holders", {"market": market, "limit": limit})

    def value(self, user: str) -> list[dict]:
        return self._get("/value", {"user": user})

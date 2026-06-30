"""Polymarket Data API client.

Endpoints:
  GET /trades?user=<wallet>      — per-wallet trade history
  GET /positions?user=<wallet>   — current holdings
  GET /activity?user=<wallet>    — TRADE | SPLIT | MERGE | REDEEM | REWARD | CONVERSION
  GET /holders                   — top holders per market
  GET /value                     — total open position value

Note: the `user` parameter accepts either the EOA or proxy address; responses key
on the proxy (Gnosis Safe) wallet that actually holds positions.
"""

from __future__ import annotations

import os
import time
from typing import Iterator, Literal, Optional

import httpx

from ..schemas import Activity, Position, Trade

DEFAULT_BASE = os.environ.get("POLYMARKET_DATA_API", "https://data-api.polymarket.com")

_RETRY_STATUS = {429, 500, 502, 503, 504}


class DataAPIClient:
    """Synchronous Polymarket Data API client with automatic pagination."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE,
        timeout: float = 20.0,
        client: Optional[httpx.Client] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(timeout=timeout, headers={"User-Agent": "bellwether/0.2"})

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "DataAPIClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _get(self, path: str, params: dict, max_retries: int = 5) -> list[dict]:
        url = f"{self.base_url}{path}"
        params = {k: v for k, v in params.items() if v is not None}
        last_exc = None
        for attempt in range(max_retries):
            try:
                resp = self._client.get(url, params=params)
                if resp.status_code in _RETRY_STATUS:
                    time.sleep(min(2**attempt * 0.5, 8.0))
                    continue
                resp.raise_for_status()
                data = resp.json()
                if isinstance(data, dict) and "data" in data:
                    data = data["data"]
                return data if isinstance(data, list) else []
            except httpx.TransportError as e:
                last_exc = e
                time.sleep(min(2**attempt * 0.5, 8.0))
        if last_exc:
            raise last_exc
        resp.raise_for_status()
        return []

    def iter_activity(self, user: str, page_size: int = 500, max_pages: int = 200):
        """Paginate a wallet's /activity feed (stops at the API's offset cap)."""
        offset = 0
        for _ in range(max_pages):
            try:
                batch = self.activity(user=user, limit=page_size, offset=offset)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 400:  # deep-offset cap reached
                    return
                raise
            if not batch:
                return
            for a in batch:
                yield a
            if len(batch) < page_size:
                return
            offset += len(batch)

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
        """Paginate through a wallet's trade history (stops at the API's offset cap)."""
        offset = 0
        for _ in range(max_pages):
            try:
                batch = self.trades(user=user, market=market, limit=page_size, offset=offset)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 400:  # deep-offset cap reached
                    return
                raise
            if not batch:
                return
            for t in batch:
                yield t
            if len(batch) < page_size:
                return
            offset += len(batch)

    def recent_trades(self, limit: int = 500, offset: int = 0) -> list[Trade]:
        """Global recent trades (no user filter) — used to seed an active-wallet pool."""
        raw = self._get("/trades", {"limit": limit, "offset": offset})
        return [Trade.model_validate(t) for t in raw]

    def iter_recent_trades(self, page_size: int = 500, max_pages: int = 4) -> Iterator[Trade]:
        offset = 0
        for _ in range(max_pages):
            try:
                batch = self.recent_trades(limit=page_size, offset=offset)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 400:
                    return
                raise
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

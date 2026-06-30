"""Manifold Markets REST client.

Manifold is play-money (Mana), but it's the only major prediction market with a
fully open per-user bet API. Use it as a zero-risk prototype venue for the
clustering, specialization, and ranking logic before pointing them at Polymarket.

Docs: https://docs.manifold.markets/api  — base: https://api.manifold.markets
"""

from __future__ import annotations

import os
import time
from typing import Iterator, Optional

import httpx

DEFAULT_BASE = os.environ.get("MANIFOLD_API", "https://api.manifold.markets")

# Transient statuses worth retrying (rate limit + upstream hiccups).
_RETRY_STATUS = {429, 500, 502, 503, 504}


class ManifoldClient:
    def __init__(self, base_url: str = DEFAULT_BASE, timeout: float = 20.0):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout, headers={"User-Agent": "bellwether/0.2"})

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ManifoldClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _get(self, path: str, params: Optional[dict] = None, max_retries: int = 5):
        params = {k: v for k, v in (params or {}).items() if v is not None}
        url = f"{self.base_url}{path}"
        last_exc: Optional[Exception] = None
        for attempt in range(max_retries):
            try:
                resp = self._client.get(url, params=params)
                if resp.status_code in _RETRY_STATUS:
                    time.sleep(min(2**attempt * 0.5, 8.0))
                    continue
                resp.raise_for_status()
                return resp.json()
            except httpx.TransportError as e:  # connection resets, timeouts
                last_exc = e
                time.sleep(min(2**attempt * 0.5, 8.0))
        if last_exc:
            raise last_exc
        resp.raise_for_status()  # surface the last retryable HTTP error
        return resp.json()

    def bets(
        self,
        user_id: Optional[str] = None,
        username: Optional[str] = None,
        contract_id: Optional[str] = None,
        before: Optional[str] = None,
        limit: int = 1000,
    ) -> list[dict]:
        return self._get(
            "/v0/bets",
            {
                "userId": user_id,
                "username": username,
                "contractId": contract_id,
                "before": before,
                "limit": limit,
            },
        )

    def iter_bets(
        self,
        user_id: Optional[str] = None,
        username: Optional[str] = None,
        page_size: int = 1000,
        max_pages: int = 50,
    ) -> Iterator[dict]:
        before: Optional[str] = None
        for _ in range(max_pages):
            batch = self.bets(user_id=user_id, username=username, before=before, limit=page_size)
            if not batch:
                return
            for b in batch:
                yield b
            if len(batch) < page_size:
                return
            before = batch[-1].get("id")

    def user(self, username: str) -> dict:
        return self._get(f"/v0/user/{username}")

    def market(self, market_id: str) -> dict:
        return self._get(f"/v0/market/{market_id}")

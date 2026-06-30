"""Polymarket Gamma API client — market metadata, tags, leaderboard, price history."""

from __future__ import annotations

import os
from typing import Optional

import httpx
from pydantic import BaseModel

DEFAULT_BASE = os.environ.get("POLYMARKET_GAMMA_API", "https://gamma-api.polymarket.com")


class LeaderboardEntry(BaseModel):
    rank: Optional[int] = None
    proxyWallet: Optional[str] = None
    userName: Optional[str] = None
    vol: Optional[float] = None
    pnl: Optional[float] = None
    profileImage: Optional[str] = None
    xUsername: Optional[str] = None
    verifiedBadge: Optional[bool] = None


class GammaClient:
    def __init__(self, base_url: str = DEFAULT_BASE, timeout: float = 20.0):
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout, headers={"User-Agent": "tradertracker/0.1"})

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "GammaClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _get(self, path: str, params: Optional[dict] = None):
        url = f"{self.base_url}{path}"
        params = {k: v for k, v in (params or {}).items() if v is not None}
        resp = self._client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()

    def leaderboard(
        self,
        window: str = "all",
        limit: int = 100,
    ) -> list[LeaderboardEntry]:
        """Fetch top wallets. `window` is one of: 'day','week','month','all' (per Gamma docs)."""
        # Endpoint shape: /leaderboard?window=<>&limit=<>. Server returns either a list or {data: [...]}.
        raw = self._get("/leaderboard", {"window": window, "limit": limit})
        if isinstance(raw, dict) and "data" in raw:
            raw = raw["data"]
        entries: list[LeaderboardEntry] = []
        for item in raw or []:
            try:
                entries.append(LeaderboardEntry.model_validate(item))
            except Exception:
                continue
        return entries

    def markets(
        self,
        closed: Optional[bool] = None,
        active: Optional[bool] = None,
        tag: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        data = self._get(
            "/markets",
            {"closed": closed, "active": active, "tag": tag, "limit": limit, "offset": offset},
        )
        if isinstance(data, dict) and "data" in data:
            return data["data"]
        return data or []

    def events(self, slug: Optional[str] = None, limit: int = 100) -> list[dict]:
        data = self._get("/events", {"slug": slug, "limit": limit})
        if isinstance(data, dict) and "data" in data:
            return data["data"]
        return data or []

"""Kalshi REST client with RSA-PSS request signing.

Public market-data endpoints (markets, GetTrades, orderbook) work unauthenticated.
Authenticated endpoints require an API key ID + RSA private key; each request signs
`timestamp + method + path` with RSA-PSS / SHA-256.

Reference: Kalshi API docs, https://trading-api.readme.io/.
"""

from __future__ import annotations

import base64
import os
import time
from pathlib import Path
from typing import Optional

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

DEFAULT_BASE = os.environ.get("KALSHI_BASE_URL", "https://api.elections.kalshi.com/trade-api/v2")


class KalshiClient:
    """Synchronous Kalshi client.

    Auth is optional — public endpoints do not require it. Pass `api_key_id` and either
    `private_key_pem` (PEM bytes) or `private_key_path` to sign requests.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE,
        api_key_id: Optional[str] = None,
        private_key_pem: Optional[bytes] = None,
        private_key_path: Optional[str | Path] = None,
        timeout: float = 20.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key_id = api_key_id or os.environ.get("KALSHI_API_KEY_ID")
        self._private_key: Optional[rsa.RSAPrivateKey] = None

        if private_key_pem is not None:
            self._private_key = serialization.load_pem_private_key(private_key_pem, password=None)
        else:
            path = private_key_path or os.environ.get("KALSHI_PRIVATE_KEY_PATH")
            if path:
                with open(path, "rb") as f:
                    self._private_key = serialization.load_pem_private_key(f.read(), password=None)

        self._client = httpx.Client(timeout=timeout, headers={"User-Agent": "tradertracker/0.1"})

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "KalshiClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _sign_headers(self, method: str, path: str) -> dict[str, str]:
        if not self._private_key or not self.api_key_id:
            return {}
        ts_ms = str(int(time.time() * 1000))
        # Kalshi signs over the request path only (no query string, no body).
        message = f"{ts_ms}{method.upper()}{path}".encode()
        signature = self._private_key.sign(
            message,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )
        return {
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode(),
            "KALSHI-ACCESS-TIMESTAMP": ts_ms,
        }

    def _request(self, method: str, path: str, **kwargs) -> dict:
        url = f"{self.base_url}{path}"
        headers = kwargs.pop("headers", {}) or {}
        headers.update(self._sign_headers(method, path))
        resp = self._client.request(method, url, headers=headers, **kwargs)
        if resp.status_code == 429:
            time.sleep(1.0)
            resp = self._client.request(method, url, headers=headers, **kwargs)
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    # --- public market data (no auth required) ---

    def get_trades(
        self,
        ticker: Optional[str] = None,
        min_ts: Optional[int] = None,
        max_ts: Optional[int] = None,
        limit: int = 1000,
        cursor: Optional[str] = None,
    ) -> dict:
        """Public anonymized trade feed. No account info is ever attached."""
        params = {
            "ticker": ticker,
            "min_ts": min_ts,
            "max_ts": max_ts,
            "limit": limit,
            "cursor": cursor,
        }
        params = {k: v for k, v in params.items() if v is not None}
        return self._request("GET", "/markets/trades", params=params)

    def iter_trades(
        self,
        ticker: Optional[str] = None,
        min_ts: Optional[int] = None,
        max_ts: Optional[int] = None,
        page_size: int = 1000,
        max_pages: int = 100,
    ):
        cursor: Optional[str] = None
        for _ in range(max_pages):
            page = self.get_trades(
                ticker=ticker, min_ts=min_ts, max_ts=max_ts, limit=page_size, cursor=cursor
            )
            for t in page.get("trades", []):
                yield t
            cursor = page.get("cursor")
            if not cursor:
                return

    def get_markets(self, status: Optional[str] = None, limit: int = 200, cursor: Optional[str] = None) -> dict:
        params = {"status": status, "limit": limit, "cursor": cursor}
        params = {k: v for k, v in params.items() if v is not None}
        return self._request("GET", "/markets", params=params)

    def get_orderbook(self, ticker: str, depth: int = 100) -> dict:
        return self._request("GET", f"/markets/{ticker}/orderbook", params={"depth": depth})

    # --- authenticated (requires API key + private key) ---

    def get_balance(self) -> dict:
        return self._request("GET", "/portfolio/balance")

    def get_positions(self, settlement_status: Optional[str] = None, limit: int = 200) -> dict:
        params = {"settlement_status": settlement_status, "limit": limit}
        params = {k: v for k, v in params.items() if v is not None}
        return self._request("GET", "/portfolio/positions", params=params)

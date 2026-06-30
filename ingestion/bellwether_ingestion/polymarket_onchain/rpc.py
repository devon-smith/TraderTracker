"""Minimal Polygon JSON-RPC client over httpx (read-only methods only)."""

from __future__ import annotations

import os
import time
from typing import Optional

import httpx

_RETRY_STATUS = {429, 500, 502, 503, 504}


class JsonRpc:
    def __init__(self, url: Optional[str] = None, timeout: float = 30.0):
        self.url = url or os.environ.get("POLYGON_RPC_URL")
        if not self.url:
            raise RuntimeError(
                "POLYGON_RPC_URL is not set. The on-chain listener needs a paid "
                "Polygon RPC (Alchemy/QuickNode); public endpoints are key-gated."
            )
        self._client = httpx.Client(timeout=timeout, headers={"User-Agent": "bellwether/0.2"})
        self._id = 0

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def call(self, method: str, params: list, max_retries: int = 5):
        self._id += 1
        payload = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params}
        for attempt in range(max_retries):
            try:
                resp = self._client.post(self.url, json=payload)
                if resp.status_code in _RETRY_STATUS:
                    time.sleep(min(2**attempt * 0.5, 8.0))
                    continue
                resp.raise_for_status()
                data = resp.json()
                if "error" in data:
                    raise RuntimeError(f"RPC error: {data['error']}")
                return data["result"]
            except httpx.TransportError:
                time.sleep(min(2**attempt * 0.5, 8.0))
        raise RuntimeError(f"RPC call failed after {max_retries} attempts: {method}")

    def block_number(self) -> int:
        return int(self.call("eth_blockNumber", []), 16)

    def get_logs(self, address: str, topics: list, from_block: int, to_block: int) -> list[dict]:
        return self.call(
            "eth_getLogs",
            [{
                "address": address,
                "topics": topics,
                "fromBlock": hex(from_block),
                "toBlock": hex(to_block),
            }],
        )

    def block_timestamp(self, block_number: int) -> int:
        blk = self.call("eth_getBlockByNumber", [hex(block_number), False])
        return int(blk["timestamp"], 16)

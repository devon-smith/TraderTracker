"""On-chain Polymarket ingestion (read-only).

NEVER signs or submits a transaction. Decodes CTF Exchange OrderFilled events on
Polygon into canonical trade rows (source='onchain').

Verification note: this module's live path needs a paid Polygon RPC
(POLYGON_RPC_URL) — public endpoints are key-gated. The CTF Exchange V2 event ABI
here is best-effort and must be confirmed against the deployed contract ABI
(https://docs.polymarket.com/resources/contracts); the decoder is ABI-driven, so
swapping the fragment is a one-line change. The decoder itself is unit-tested
deterministically (encode -> decode round trip).
"""

from .contracts import (
    CTF_EXCHANGE_V1,
    CTF_EXCHANGE_V2,
    NEG_RISK_CTF_EXCHANGE_V2,
    ORDER_FILLED_V1,
    order_filled_topic0,
)
from .decode import decode_log, event_topic0
from .normalize import normalize_order_filled

__all__ = [
    "CTF_EXCHANGE_V1",
    "CTF_EXCHANGE_V2",
    "NEG_RISK_CTF_EXCHANGE_V2",
    "ORDER_FILLED_V1",
    "order_filled_topic0",
    "decode_log",
    "event_topic0",
    "normalize_order_filled",
]

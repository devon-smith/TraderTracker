"""Polymarket contract addresses + OrderFilled event ABIs.

Addresses are checked against the feasibility study; the V2 migration (Apr 28
2026) moved trading to CTF Exchange V2. The V1 addresses are the pre-migration
fallback for historical backfill. ALWAYS confirm against
https://docs.polymarket.com/resources/contracts before production — treat these
as defaults, not gospel.
"""

from __future__ import annotations

from .decode import EventABI, event_topic0

# --- addresses (Polygon, chain 137) ---
CTF_EXCHANGE_V2 = "0xE111180000d2663C0091e4f400237545B87B996B"
NEG_RISK_CTF_EXCHANGE_V2 = "0xe2222d279d744050d28e00520010520000310F59"
# Pre-V2 (for historical backfill before the Apr 28 2026 cutover):
CTF_EXCHANGE_V1 = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
NEG_RISK_CTF_EXCHANGE_V1 = "0xC5d563A36AE78145C45a50134d48A1215220f80a"

# USDC collateral is asset id 0 in the CTF; outcome tokens are non-zero ids.
COLLATERAL_ASSET_ID = 0

# --- event ABIs ---
# V1 OrderFilled — well-known, confident:
#   event OrderFilled(bytes32 indexed orderHash, address indexed maker,
#       address indexed taker, uint256 makerAssetId, uint256 takerAssetId,
#       uint256 makerAmountFilled, uint256 takerAmountFilled, uint256 fee)
ORDER_FILLED_V1: EventABI = EventABI(
    name="OrderFilled",
    inputs=[
        {"name": "orderHash", "type": "bytes32", "indexed": True},
        {"name": "maker", "type": "address", "indexed": True},
        {"name": "taker", "type": "address", "indexed": True},
        {"name": "makerAssetId", "type": "uint256", "indexed": False},
        {"name": "takerAssetId", "type": "uint256", "indexed": False},
        {"name": "makerAmountFilled", "type": "uint256", "indexed": False},
        {"name": "takerAmountFilled", "type": "uint256", "indexed": False},
        {"name": "fee", "type": "uint256", "indexed": False},
    ],
)

# V2 OrderFilled — LIVE-VERIFIED. Source-verified on Polygonscan (CTFExchange V2)
# and confirmed against real emitted logs (the dominant topic across ~1,032 events
# in a recent window). These constants are ground truth: do NOT re-derive or
# locally re-hash them. V2 differs from V1 structurally — a single `tokenId` +
# `side` (uint8) replaces the maker/takerAssetId pair, and two trailing bytes32
# fields (builder, metadata) are appended; their presence is what distinguishes a
# V2 log from a V1 one.
#   event OrderFilled(bytes32 indexed orderHash, address indexed maker,
#       address indexed taker, uint8 side, uint256 tokenId,
#       uint256 makerAmountFilled, uint256 takerAmountFilled, uint256 fee,
#       bytes32 builder, bytes32 metadata)
ORDER_FILLED_V2: EventABI = EventABI(
    name="OrderFilled",
    inputs=[
        {"name": "orderHash", "type": "bytes32", "indexed": True},
        {"name": "maker", "type": "address", "indexed": True},
        {"name": "taker", "type": "address", "indexed": True},
        {"name": "side", "type": "uint8", "indexed": False},
        {"name": "tokenId", "type": "uint256", "indexed": False},
        {"name": "makerAmountFilled", "type": "uint256", "indexed": False},
        {"name": "takerAmountFilled", "type": "uint256", "indexed": False},
        {"name": "fee", "type": "uint256", "indexed": False},
        {"name": "builder", "type": "bytes32", "indexed": False},
        {"name": "metadata", "type": "bytes32", "indexed": False},
    ],
)

# Live-verified V2 OrderFilled signature hash (topic[0]). This is the authoritative
# ground-truth value we MATCH emitted logs against — it is deliberately a constant,
# not re-derived from the ABI string at runtime (see order_filled_topic0).
ORDER_FILLED_V2_TOPIC0 = "0xd543adfd945773f1a62f74f0ee55a5e3b9b1a28262980ba90b1a89f2ea84d8ee"


def order_filled_topic0(version: str = "v1") -> str:
    """topic[0] for OrderFilled. V2 returns the live-verified constant
    (authoritative — never re-hashed); V1 is computed from its well-known ABI."""
    if version == "v2":
        return ORDER_FILLED_V2_TOPIC0
    return event_topic0(ORDER_FILLED_V1)

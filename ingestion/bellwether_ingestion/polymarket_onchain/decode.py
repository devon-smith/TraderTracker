"""ABI-driven EVM log decoding (no web3 dependency).

Computes the event topic0 from an ABI fragment and decodes a log's indexed topics
+ non-indexed data into a name->value dict. Generic over the event ABI so V1/V2
OrderFilled (or any event) decode with the same code.
"""

from __future__ import annotations

from dataclasses import dataclass

from eth_abi import decode as abi_decode
from eth_utils import keccak, to_checksum_address


@dataclass
class EventABI:
    name: str
    inputs: list[dict]  # each: {name, type, indexed}

    def signature(self) -> str:
        return f"{self.name}(" + ",".join(i["type"] for i in self.inputs) + ")"

    @property
    def indexed(self) -> list[dict]:
        return [i for i in self.inputs if i.get("indexed")]

    @property
    def non_indexed(self) -> list[dict]:
        return [i for i in self.inputs if not i.get("indexed")]


def event_topic0(abi: EventABI) -> str:
    return "0x" + keccak(text=abi.signature()).hex()


def _hexbytes(x) -> bytes:
    if isinstance(x, (bytes, bytearray)):
        return bytes(x)
    s = x[2:] if isinstance(x, str) and x.startswith("0x") else x
    return bytes.fromhex(s)


def _decode_topic(topic: bytes, sol_type: str):
    if sol_type == "address":
        return to_checksum_address(topic[-20:])
    if sol_type.startswith("bytes"):
        return "0x" + topic.hex()
    if sol_type.startswith("uint") or sol_type.startswith("int"):
        return int.from_bytes(topic, "big")
    if sol_type == "bool":
        return bool(int.from_bytes(topic, "big"))
    return "0x" + topic.hex()


def decode_log(abi: EventABI, topics: list, data) -> dict:
    """Decode one log. `topics` is [topic0, ...indexed]; `data` is the non-indexed
    ABI-encoded blob (hex str or bytes)."""
    topics_b = [_hexbytes(t) for t in topics]
    out: dict = {}

    for i, inp in enumerate(abi.indexed):
        out[inp["name"]] = _decode_topic(topics_b[i + 1], inp["type"])

    non_idx = abi.non_indexed
    if non_idx:
        values = abi_decode([i["type"] for i in non_idx], _hexbytes(data))
        for inp, val in zip(non_idx, values):
            out[inp["name"]] = val
    return out

"""Deterministic client_order_id (cloid) generation.

PRD F-12: "All order placements use client-supplied IDs so retries are
idempotent." We derive the cloid from the setup_key + level_role + sequence
so that re-issuing the same order yields the same cloid; the exchange then
rejects the duplicate, which is the behavior we want.

Hyperliquid format: a 34-character hex string `0x` + 32 hex chars (16 bytes /
128 bits of namespace). The hash space is far larger than the bot will ever
produce in its lifetime, so collisions are not a practical concern.
"""
from __future__ import annotations

import hashlib

CLOID_HEX_LEN = 32  # 16 bytes; HL's required cloid length


def make_cloid(setup_key: str, level_role: str, seq: int = 0) -> str:
    """Return a deterministic cloid for `(setup_key, level_role, seq)`.

    `seq` lets us re-issue an order if a prior attempt was cancelled or
    rejected and we want a fresh exchange order ID. Same triple -> same cloid.
    """
    payload = f"{setup_key}|{level_role}|{seq}".encode()
    digest = hashlib.sha256(payload).hexdigest()[:CLOID_HEX_LEN]
    return f"0x{digest}"

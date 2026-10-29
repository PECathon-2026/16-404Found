"""Prefixed, time-ordered ULID-style ids (AGENTS.md §0.7). Monotonic within a process."""
from __future__ import annotations

import os
import threading
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_lock = threading.Lock()
_last = 0


def _encode(value: int, length: int) -> str:
    out = []
    for _ in range(length):
        out.append(_ALPHABET[value & 31])
        value >>= 5
    return "".join(reversed(out))


def new_id(prefix: str) -> str:
    global _last
    with _lock:
        ms = int(time.time() * 1000)
        value = (ms << 80) | int.from_bytes(os.urandom(10), "big")
        if value <= _last:
            value = _last + 1
        _last = value
    return f"{prefix}_{_encode(value, 26)}"


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int(time.time() * 1000) % 1000:03d}Z"

# SPDX-License-Identifier: Apache-2.0
"""Tiered KV cache: a hot tier in RAM (LRU) + a cold tier on SSD (pickle).

Keys are prompt-prefix hashes; values are whatever the caller stores (e.g. a
model's ``past_key_values``). When the hot tier overflows, the LRU entry spills
to disk; a later hit restores it (and promotes it back to hot) — so a shared
prefix survives eviction and even a process restart. Serialization is ``pickle``
(which handles torch tensors), so the store itself needs no torch and is fully
testable. This is the in-process equivalent of oMLX's hot/cold block KV cache;
true block-level prefix sharing inside ``generate`` is model-specific and layered
on top of this store.
"""

from __future__ import annotations

import hashlib
import pickle
from collections import OrderedDict
from pathlib import Path
from typing import Any, Optional


def prefix_key(tokens) -> str:
    """Stable 32-hex key for a token-id prefix (or any repr-able sequence)."""
    digest = hashlib.sha256(repr(list(tokens)).encode()).hexdigest()
    return digest[:32]


class TieredKVCache:
    """Hot (RAM, LRU) + cold (SSD) key/value store for cached KV state."""

    def __init__(self, hot_capacity: int = 4, cold_dir: Optional[str] = None):
        self._hot: "OrderedDict[str, Any]" = OrderedDict()
        self._cap = max(1, int(hot_capacity))
        self._cold_dir = Path(cold_dir).expanduser() if cold_dir else None
        self._cold: set = set()
        if self._cold_dir is not None:
            self._cold_dir.mkdir(parents=True, exist_ok=True)
            for f in self._cold_dir.glob("*.kv"):
                self._cold.add(f.stem)

    def __len__(self) -> int:
        return len(self._hot) + len(self._cold)

    def get(self, key: str) -> Optional[Any]:
        if key in self._hot:
            self._hot.move_to_end(key)
            return self._hot[key]
        if key in self._cold:
            value = self._load_cold(key)
            if value is not None:
                self._cold.discard(key)
                self._hot[key] = value
                self._hot.move_to_end(key)
                self._evict_if_needed()
                return value
        return None

    def put(self, key: str, value: Any) -> None:
        self._hot[key] = value
        self._hot.move_to_end(key)
        self._evict_if_needed()

    def _evict_if_needed(self) -> None:
        while len(self._hot) > self._cap:
            old_key, old_val = self._hot.popitem(last=False)  # LRU
            self._offload_cold(old_key, old_val)

    def _cold_path(self, key: str) -> Path:
        return self._cold_dir / f"{key}.kv"

    def _offload_cold(self, key: str, value: Any) -> None:
        if self._cold_dir is None:
            return
        try:
            self._cold_path(key).write_bytes(pickle.dumps(value))
            self._cold.add(key)
        except (OSError, pickle.PicklingError):
            pass  # best-effort: dropping a cache entry is never fatal

    def _load_cold(self, key: str) -> Optional[Any]:
        if self._cold_dir is None:
            return None
        try:
            return pickle.loads(self._cold_path(key).read_bytes())
        except (OSError, pickle.UnpicklingError, EOFError, ValueError):
            return None

    def stats(self) -> dict:
        return {"hot": len(self._hot), "cold": len(self._cold), "hot_capacity": self._cap}

# SPDX-License-Identifier: Apache-2.0
"""Aggregate request statistics with **session** + persisted **all-time** scopes.

Modeled on oMLX's server metrics: track totals (requests, prompt / completion /
cached tokens, prefill + generation seconds) for the current process *session* and
an *all-time* tally persisted to ``~/.infermesh/stats.json`` (survives a restart).
``snapshot(scope)`` derives the operator-facing numbers — tokens served, cache
efficiency %, and prefill / generation tok/s (prefill TPS excludes cached tokens).
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from infermesh.core.settings import HOME_DIR

STATS_FILE = HOME_DIR / "stats.json"
_INT_FIELDS = ("requests", "prompt_tokens", "completion_tokens", "cached_tokens")
_FLOAT_FIELDS = ("prefill_s", "generation_s")
_SAVE_EVERY = 20  # persist all-time every N requests


def _zero() -> dict:
    return {**{k: 0 for k in _INT_FIELDS}, **{k: 0.0 for k in _FLOAT_FIELDS}}


class StatsAccumulator:
    """Session + all-time request tallies; all-time is persisted to disk."""

    def __init__(self, path: Path = STATS_FILE):
        self._lock = threading.Lock()
        self._start = time.time()
        self._path = path
        self._session = _zero()
        self._alltime = self._load()
        self._since_save = 0

    def _load(self) -> dict:
        z = _zero()
        try:
            data = json.loads(self._path.read_text())
        except (OSError, ValueError):
            return z
        for k in (*_INT_FIELDS, *_FLOAT_FIELDS):
            if isinstance(data.get(k), (int, float)):
                z[k] = data[k]
        return z

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._alltime))
        except OSError:
            pass  # best-effort

    def record(self, *, prompt_tokens: int = 0, completion_tokens: int = 0,
               cached_tokens: int = 0, prefill_s: float = 0.0, generation_s: float = 0.0) -> None:
        with self._lock:
            for tgt in (self._session, self._alltime):
                tgt["requests"] += 1
                tgt["prompt_tokens"] += int(prompt_tokens or 0)
                tgt["completion_tokens"] += int(completion_tokens or 0)
                tgt["cached_tokens"] += int(cached_tokens or 0)
                tgt["prefill_s"] += float(prefill_s or 0.0)
                tgt["generation_s"] += float(generation_s or 0.0)
            self._since_save += 1
            if self._since_save >= _SAVE_EVERY:
                self._save()
                self._since_save = 0

    def snapshot(self, scope: str = "session") -> dict:
        with self._lock:
            d = dict(self._alltime if scope == "alltime" else self._session)
            uptime = time.time() - self._start
        prompt, completion, cached = d["prompt_tokens"], d["completion_tokens"], d["cached_tokens"]
        actual = max(0, prompt - cached)
        prefill_tps = actual / d["prefill_s"] if d["prefill_s"] > 0 else 0.0
        gen_tps = completion / d["generation_s"] if d["generation_s"] > 0 else 0.0
        cache_eff = (cached / prompt * 100) if prompt > 0 else 0.0
        return {
            "scope": "alltime" if scope == "alltime" else "session",
            "total_requests": d["requests"],
            "total_prompt_tokens": prompt,
            "total_completion_tokens": completion,
            "total_cached_tokens": cached,
            "total_tokens_served": prompt + completion,
            "cache_efficiency": round(cache_eff, 1),
            "prefill_tps": round(prefill_tps, 1),
            "generation_tps": round(gen_tps, 1),
            "uptime_seconds": round(uptime, 1),
        }

    def clear(self, scope: str = "session") -> None:
        with self._lock:
            if scope == "alltime":
                self._alltime = _zero()
                self._save()
            else:
                self._session = _zero()

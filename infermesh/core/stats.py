# SPDX-License-Identifier: Apache-2.0
"""Aggregate request statistics with **session** + persisted **all-time** scopes and
a **per-model** breakdown. Modeled on oMLX's server metrics.

Tracks totals (requests, prompt / completion / cached tokens, prefill + generation
seconds) globally and per model, for the current process *session* and an
*all-time* tally persisted to ``~/.infermesh/stats.json`` (survives a restart).
``snapshot(scope, model)`` derives the operator-facing numbers — tokens served,
cache efficiency %, and prefill / generation tok/s (prefill TPS excludes cached
tokens). ``snapshot(...).models`` lists which models have stats (for a UI picker).
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


def _add(tgt: dict, prompt: int, completion: int, cached: int, prefill_s: float, gen_s: float) -> None:
    tgt["requests"] += 1
    tgt["prompt_tokens"] += int(prompt or 0)
    tgt["completion_tokens"] += int(completion or 0)
    tgt["cached_tokens"] += int(cached or 0)
    tgt["prefill_s"] += float(prefill_s or 0.0)
    tgt["generation_s"] += float(gen_s or 0.0)


def _coerce(src: dict) -> dict:
    z = _zero()
    if isinstance(src, dict):
        for k in (*_INT_FIELDS, *_FLOAT_FIELDS):
            if isinstance(src.get(k), (int, float)):
                z[k] = src[k]
    return z


class StatsAccumulator:
    """Session + all-time request tallies (global + per model); all-time persists."""

    def __init__(self, path: Path = STATS_FILE):
        self._lock = threading.Lock()
        self._start = time.time()
        self._path = path
        self._session = _zero()
        self._session_pm: dict[str, dict] = {}
        self._alltime = _zero()
        self._alltime_pm: dict[str, dict] = {}
        self._session_rej: dict[str, int] = {}
        self._alltime_rej: dict[str, int] = {}
        self._load()
        self._since_save = 0

    def _load(self) -> None:
        try:
            data = json.loads(self._path.read_text())
        except (OSError, ValueError):
            return
        # back-compat: a flat dict (pre-per-model) is the global all-time tally.
        self._alltime = _coerce(data.get("global", data))
        per_model = data.get("per_model", {})
        if isinstance(per_model, dict):
            self._alltime_pm = {mid: _coerce(c) for mid, c in per_model.items()}
        rej = data.get("rejections", {})
        if isinstance(rej, dict):
            self._alltime_rej = {str(k): int(v) for k, v in rej.items() if isinstance(v, int)}

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps({"global": self._alltime, "per_model": self._alltime_pm,
                                              "rejections": self._alltime_rej}))
        except OSError:
            pass  # best-effort

    def record(self, *, model: str = "", prompt_tokens: int = 0, completion_tokens: int = 0,
               cached_tokens: int = 0, prefill_s: float = 0.0, generation_s: float = 0.0) -> None:
        with self._lock:
            for tgt in (self._session, self._alltime):
                _add(tgt, prompt_tokens, completion_tokens, cached_tokens, prefill_s, generation_s)
            if model:
                for pm in (self._session_pm, self._alltime_pm):
                    _add(pm.setdefault(model, _zero()), prompt_tokens, completion_tokens, cached_tokens, prefill_s, generation_s)
            self._since_save += 1
            if self._since_save >= _SAVE_EVERY:
                self._save()
                self._since_save = 0

    def record_rejection(self, reason: str) -> None:
        """Count a request rejected before serving (model_not_found, insufficient_memory, ...)."""
        reason = reason or "other"
        with self._lock:
            for rej in (self._session_rej, self._alltime_rej):
                rej[reason] = rej.get(reason, 0) + 1
            self._save()

    def snapshot(self, scope: str = "session", model: str = "") -> dict:
        alltime = scope == "alltime"
        with self._lock:
            pm = self._alltime_pm if alltime else self._session_pm
            if model:
                d = dict(pm.get(model) or _zero())
            else:
                d = dict(self._alltime if alltime else self._session)
            models = sorted(pm.keys())
            rej = dict(self._alltime_rej if alltime else self._session_rej)
            uptime = time.time() - self._start
        out = self._derive(d, uptime)
        out["scope"] = "alltime" if alltime else "session"
        out["model"] = model or None
        out["models"] = models
        out["rejections"] = rej
        out["total_rejections"] = sum(rej.values())
        return out

    @staticmethod
    def _derive(d: dict, uptime: float) -> dict:
        prompt, completion, cached = d["prompt_tokens"], d["completion_tokens"], d["cached_tokens"]
        actual = max(0, prompt - cached)
        return {
            "total_requests": d["requests"],
            "total_prompt_tokens": prompt,
            "total_completion_tokens": completion,
            "total_cached_tokens": cached,
            "total_tokens_served": prompt + completion,
            "cache_efficiency": round((cached / prompt * 100) if prompt > 0 else 0.0, 1),
            "prefill_tps": round(actual / d["prefill_s"] if d["prefill_s"] > 0 else 0.0, 1),
            "generation_tps": round(completion / d["generation_s"] if d["generation_s"] > 0 else 0.0, 1),
            "uptime_seconds": round(uptime, 1),
        }

    def clear(self, scope: str = "session") -> None:
        with self._lock:
            if scope == "alltime":
                self._alltime = _zero()
                self._alltime_pm = {}
                self._alltime_rej = {}
                self._save()
            else:
                self._session = _zero()
                self._session_pm = {}
                self._session_rej = {}

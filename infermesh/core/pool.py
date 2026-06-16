# SPDX-License-Identifier: Apache-2.0
"""ModelPool — multi-model orchestration with LRU eviction, pinning, TTL, leases.

Adapted from oMLX ``omlx/engine_pool.py``. The public API and the
evict-before-load / pin / TTL / in-use-lease *semantics* are preserved verbatim;
the bodies are reimplemented against the hardware-neutral
:class:`~infermesh.core.backend.InferenceBackend` because the oMLX original is
deeply coupled to MLX (``mlx_lm.load``, ``mx.clear_cache``/``synchronize``,
``mx.get_active_memory()``, dflash/VLM/speculative machinery). Specifically:

  * each :class:`EngineEntry` holds an ``InferenceBackend`` (created lazily via
    :class:`~infermesh.core.factory.BackendFactory` on first acquire) instead of
    a concrete MLX engine;
  * memory accounting uses the sum of loaded backends' ``stats().used_mem_mb``
    plus a :class:`~infermesh.core.memory.MemoryProbe` for the default ceiling,
    replacing ``mx.get_active_memory()``;
  * "has active requests" is approximated by the in-use lease count, since the
    backend interface does not expose a request queue in Milestone 1.

Everything is in **megabytes** (the unit shared by MemoryProbe, EngineStats, and
Settings.parse_memory_limit), unlike oMLX which works in bytes.
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Iterable, Optional

from infermesh.core.backend import InferenceBackend, ModelSpec
from infermesh.core.factory import BackendFactory
from infermesh.core.memory import MemoryProbe, SystemMemoryProbe

logger = logging.getLogger("infermesh.pool")


# --------------------------------------------------------------------------- #
# Errors (oMLX raises analogous ones from its engine layer)
# --------------------------------------------------------------------------- #
class PoolError(Exception):
    """Base class for model-pool errors."""


class ModelNotFoundError(PoolError):
    def __init__(self, model_id: str, available: list[str]) -> None:
        super().__init__(
            f"Model '{model_id}' not found. Available: {sorted(available)}"
        )
        self.model_id = model_id
        self.available = available


class ModelTooLargeError(PoolError):
    def __init__(self, model_id: str, required_mb: int, ceiling_mb: int) -> None:
        super().__init__(
            f"Model '{model_id}' needs ~{required_mb} MB which alone exceeds the "
            f"memory ceiling {ceiling_mb} MB."
        )
        self.model_id = model_id
        self.required_mb = required_mb
        self.ceiling_mb = ceiling_mb


class InsufficientMemoryError(PoolError):
    def __init__(self, model_id: str, required_mb: int, current_mb: int, ceiling_mb: int) -> None:
        super().__init__(
            f"Cannot load '{model_id}': projected {current_mb + required_mb} MB "
            f"would exceed ceiling {ceiling_mb} MB (current {current_mb} MB, "
            f"model ~{required_mb} MB) and nothing else is evictable (all pinned "
            f"or in use)."
        )
        self.model_id = model_id
        self.required_mb = required_mb
        self.current_mb = current_mb
        self.ceiling_mb = ceiling_mb


@dataclass
class EngineEntry:
    """Per-model state in the pool (cf. oMLX EngineEntry)."""

    spec: ModelSpec
    estimated_mb: int
    backend: Optional[InferenceBackend] = None
    last_access: float = 0.0          # LRU timestamp (0 => never loaded)
    is_loading: bool = False
    loading_started_at: Optional[float] = None
    is_pinned: bool = False           # never evict if True
    in_use: int = 0                   # in-flight lease count; never evict while > 0
    ttl_seconds: Optional[float] = None  # per-model TTL override (None => use global)

    @property
    def model_id(self) -> str:
        return self.spec.model_id

    @property
    def loaded(self) -> bool:
        return self.backend is not None


class ModelPool:
    """Manages multiple model backends with LRU-based memory management.

    Features (mirrors oMLX EnginePool):
      - pre-load memory checking (evict before load, not after);
      - LRU eviction when the memory ceiling would be exceeded;
      - model pinning to prevent eviction;
      - in-use leases so a model serving a request is never evicted;
      - TTL-based idle unload.
    """

    def __init__(
        self,
        factory: Optional[BackendFactory] = None,
        *,
        probe: Optional[MemoryProbe] = None,
        max_memory_mb: Optional[int] = None,
        memory_reserve_mb: int = 8192,     # default ceiling = total - 8 GB (S7.1a)
        idle_timeout: float = 0.0,         # global TTL seconds; 0 => disabled
        default_model_mb: int = 4096,      # assumed footprint when unknown
    ) -> None:
        self._factory = factory or BackendFactory()
        self._probe = probe or SystemMemoryProbe()
        self._entries: dict[str, EngineEntry] = {}
        self._lock = asyncio.Lock()
        self._current_model_memory_mb = 0  # tracked accumulator (committed total)
        self._max_memory_mb = max_memory_mb
        self._memory_reserve_mb = memory_reserve_mb
        self._idle_timeout = idle_timeout
        self._default_model_mb = default_model_mb

    # ----------------------------- discovery ------------------------------- #
    def _estimate_mb(self, spec: ModelSpec) -> int:
        extra = spec.extra or {}
        return int(
            extra.get("estimated_mb", extra.get("mock_mem_mb", self._default_model_mb))
        )

    def discover_models(
        self,
        specs: Iterable[ModelSpec],
        pinned: Optional[Iterable[str]] = None,
    ) -> None:
        """Register/refresh entries from ModelSpecs (does not load anything).

        Loaded models keep their runtime state; pin flags are taken from
        ``pinned``; entries no longer present and not loaded are dropped.
        """
        pinned_set = set(pinned or [])
        seen: set[str] = set()
        for spec in specs:
            mid = spec.model_id
            seen.add(mid)
            estimated = self._estimate_mb(spec)
            existing = self._entries.get(mid)
            if existing is not None and existing.backend is not None:
                existing.spec = spec
                existing.estimated_mb = estimated
                existing.is_pinned = mid in pinned_set
            else:
                self._entries[mid] = EngineEntry(
                    spec=spec,
                    estimated_mb=estimated,
                    is_pinned=mid in pinned_set,
                )
            if mid in pinned_set:
                logger.info("Pinned model: %s", mid)

        stale = [
            mid for mid in self._entries
            if mid not in seen and self._entries[mid].backend is None
        ]
        for mid in stale:
            del self._entries[mid]

        for mid in pinned_set:
            if mid not in self._entries:
                logger.warning("Pinned model not found: %s", mid)
        logger.info("Discovered %d models", len(self._entries))

    # ------------------------------ queries -------------------------------- #
    @property
    def model_count(self) -> int:
        return len(self._entries)

    @property
    def loaded_model_count(self) -> int:
        return sum(1 for e in self._entries.values() if e.backend is not None)

    def get_model_ids(self) -> list[str]:
        return list(self._entries.keys())

    def get_loaded_model_ids(self) -> list[str]:
        return [mid for mid, e in self._entries.items() if e.backend is not None]

    def get_entry(self, model_id: str) -> Optional[EngineEntry]:
        return self._entries.get(model_id)

    def set_pinned(self, model_id: str, pinned: bool) -> bool:
        entry = self._entries.get(model_id)
        if entry is None:
            return False
        entry.is_pinned = pinned
        return True

    def _case_insensitive_match(self, name: str) -> Optional[str]:
        lower = name.lower()
        for mid in self._entries:
            if mid.lower() == lower:
                return mid
        return None

    def resolve_model_id(self, model_id_or_alias: str) -> str:
        """Resolve an alias/case-variant/provider-prefixed id to a real model_id.

        Order: exact -> case-insensitive -> spec.alias -> strip ``provider/``
        prefix and retry. Returns the input unchanged if nothing matches.
        """
        if model_id_or_alias in self._entries:
            return model_id_or_alias
        ci = self._case_insensitive_match(model_id_or_alias)
        if ci is not None:
            return ci
        for mid, entry in self._entries.items():
            if entry.spec.alias and entry.spec.alias == model_id_or_alias:
                return mid
        if "/" in model_id_or_alias:
            stripped = model_id_or_alias.split("/", 1)[1]
            if stripped in self._entries:
                return stripped
            ci = self._case_insensitive_match(stripped)
            if ci is not None:
                return ci
        return model_id_or_alias

    # ----------------------------- memory ---------------------------------- #
    def _current_ceiling_mb(self) -> int:
        """Resolve the memory ceiling in MB. 0 => no limit (admit anything)."""
        if self._max_memory_mb is not None:
            return max(0, int(self._max_memory_mb))
        total = self._probe.total_mb()
        if total <= 0:
            return 0
        return max(0, total - self._memory_reserve_mb)

    def _current_used_mb(self) -> int:
        """Sum of loaded backends' reported usage (cf. oMLX mx.get_active_memory)."""
        total = 0
        for entry in self._entries.values():
            if entry.backend is not None:
                try:
                    total += int(entry.backend.stats().used_mem_mb)
                except Exception:  # noqa: BLE001 - stats must never break admission
                    total += entry.estimated_mb
        return total

    # ------------------------------ lifecycle ------------------------------ #
    async def get_engine(self, model_id: str, *, _lease: bool = False) -> InferenceBackend:
        """Get or load the backend for ``model_id`` (evict-before-load).

        The pool lock is held for the whole operation, including the load — this
        matches oMLX and keeps eviction/admission atomic. (For slow out-of-process
        loads a future refinement could load outside the lock guarded by
        ``is_loading``.)
        """
        async with self._lock:
            entry = self._entries.get(model_id)
            if entry is None:
                raise ModelNotFoundError(model_id, list(self._entries.keys()))

            # Already loaded -> just touch LRU + lease.
            if entry.backend is not None:
                entry.last_access = time.time()
                if _lease:
                    entry.in_use += 1
                return entry.backend

            # Pre-load admission against the ceiling; evict LRU until it fits.
            ceiling = self._current_ceiling_mb()
            if ceiling > 0:
                while True:
                    current = self._current_used_mb()
                    projected = current + entry.estimated_mb
                    if projected <= ceiling:
                        break
                    victim = self._find_lru_victim()
                    if victim is not None:
                        logger.info(
                            "Evicting '%s' to fit '%s' under ceiling (%d > %d MB)",
                            victim, model_id, projected, ceiling,
                        )
                        await self._unload_engine(victim)
                        continue
                    if entry.estimated_mb > ceiling:
                        raise ModelTooLargeError(model_id, entry.estimated_mb, ceiling)
                    raise InsufficientMemoryError(
                        model_id, entry.estimated_mb, current, ceiling
                    )

            await self._load_engine(model_id)
            if _lease:
                entry.in_use += 1
            return entry.backend  # type: ignore[return-value]

    async def release_engine(self, model_id: str) -> None:
        """Release one in-use lease taken via get_engine(_lease=True)/acquire()."""
        async with self._lock:
            entry = self._entries.get(model_id)
            if entry is not None and entry.in_use > 0:
                entry.in_use -= 1

    @asynccontextmanager
    async def acquire(self, model_id: str):
        """Acquire a backend with an atomic in-use lease, always released."""
        backend = await self.get_engine(model_id, _lease=True)
        try:
            yield backend
        finally:
            await self.release_engine(model_id)

    async def unload_if_idle_unpinned(self, model_id: str, *, force: bool = False) -> bool:
        """Unload a loaded model when idle and not pinned (or unconditionally if force)."""
        async with self._lock:
            entry = self._entries.get(model_id)
            if entry is None or entry.backend is None or entry.is_loading:
                return False
            if not force and (entry.is_pinned or entry.in_use > 0):
                return False
            await self._unload_engine(model_id)
            return True

    def _find_lru_victim(self) -> Optional[str]:
        """Least-recently-used loaded model that is not pinned and not in use."""
        candidates = [
            (e.last_access, mid)
            for mid, e in self._entries.items()
            if e.backend is not None and not e.is_pinned and e.in_use == 0
        ]
        if not candidates:
            return None
        candidates.sort()  # oldest last_access first
        return candidates[0][1]

    async def _load_engine(self, model_id: str) -> None:
        """Create the backend via the factory and bring the model online.

        Assumes the pool lock is held.
        """
        entry = self._entries[model_id]
        entry.is_loading = True
        entry.loading_started_at = time.time()
        try:
            backend = self._factory.create(entry.spec)
            await backend.load(entry.spec)
            entry.backend = backend
            entry.last_access = time.time()
            self._current_model_memory_mb += entry.estimated_mb
            logger.info(
                "Loaded '%s' via %s (~%d MB)",
                model_id, backend.backend_name, entry.estimated_mb,
            )
        finally:
            entry.is_loading = False
            entry.loading_started_at = None

    async def _unload_engine(self, model_id: str) -> None:
        """Unload a model and release its backend. Assumes the pool lock is held."""
        entry = self._entries.get(model_id)
        if entry is None or entry.backend is None:
            return
        backend = entry.backend
        entry.backend = None
        self._current_model_memory_mb = max(
            0, self._current_model_memory_mb - entry.estimated_mb
        )
        try:
            await backend.unload()
        except Exception as exc:  # noqa: BLE001
            logger.error("Error unloading '%s': %s", model_id, exc)
        logger.info("Unloaded '%s'", model_id)

    # ------------------------------ pinned / ttl --------------------------- #
    async def preload_pinned_models(self) -> None:
        """Preload all pinned models at startup."""
        pinned = [mid for mid, e in self._entries.items() if e.is_pinned]
        for model_id in pinned:
            try:
                logger.info("Preloading pinned model: %s", model_id)
                await self.get_engine(model_id)
            except PoolError as exc:
                logger.error("Failed to preload pinned model %s: %s", model_id, exc)

    async def check_ttl_expirations(
        self, global_idle_timeout_seconds: Optional[float] = None
    ) -> list[str]:
        """Unload models idle longer than their effective TTL.

        Pinned/loading models and models with in-use leases are skipped (their
        ``last_access`` is refreshed for the in-use case). Returns unloaded ids.
        """
        global_ttl = (
            global_idle_timeout_seconds
            if global_idle_timeout_seconds is not None
            else self._idle_timeout
        )
        now = time.time()
        expired: list[str] = []
        async with self._lock:
            for model_id, entry in list(self._entries.items()):
                if entry.backend is None or entry.is_loading or entry.is_pinned:
                    continue
                effective_ttl = entry.ttl_seconds
                if effective_ttl is None:
                    effective_ttl = global_ttl
                if effective_ttl is None or effective_ttl <= 0:
                    continue
                if entry.in_use > 0:
                    entry.last_access = now
                    continue
                if now - entry.last_access < effective_ttl:
                    continue
                logger.info(
                    "TTL expired for '%s' (idle %.2fs >= ttl %.2fs)",
                    model_id, now - entry.last_access, effective_ttl,
                )
                await self._unload_engine(model_id)
                expired.append(model_id)
        return expired

    # ------------------------------ status --------------------------------- #
    async def shutdown(self) -> None:
        """Unload all models gracefully."""
        async with self._lock:
            for model_id in list(self._entries.keys()):
                if self._entries[model_id].backend is not None:
                    await self._unload_engine(model_id)
        logger.info("Model pool shutdown complete")

    def get_status(self) -> dict:
        """Pool status for monitoring endpoints (/api/status)."""
        models = []
        for mid, e in sorted(self._entries.items()):
            info = {
                "id": mid,
                "source": e.spec.source,
                "model_type": e.spec.model_type,
                "backend": e.spec.backend,
                "loaded": e.backend is not None,
                "is_loading": e.is_loading,
                "pinned": e.is_pinned,
                "in_use": e.in_use,
                "estimated_mb": e.estimated_mb,
                "last_access": e.last_access if e.last_access > 0 else None,
            }
            if e.backend is not None:
                s = e.backend.stats()
                info["stats"] = {
                    "prompt_tps": s.prompt_tps,
                    "generation_tps": s.generation_tps,
                    "queue_depth": s.queue_depth,
                    "active_requests": s.active_requests,
                    "used_mem_mb": s.used_mem_mb,
                    "kv_cache_hit_rate": s.kv_cache_hit_rate,
                }
            models.append(info)
        return {
            "ceiling_mb": self._current_ceiling_mb(),
            "current_model_memory_mb": self._current_model_memory_mb,
            "used_mb_live": self._current_used_mb(),
            "total_mb": self._probe.total_mb(),
            "model_count": len(self._entries),
            "loaded_count": self.loaded_model_count,
            "models": models,
        }

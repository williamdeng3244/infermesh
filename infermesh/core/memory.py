# SPDX-License-Identifier: Apache-2.0
"""Memory-probing abstraction — replaces oMLX's ``mx.get_active_memory()``.

The pool uses a :class:`MemoryProbe` to compute its default memory ceiling and,
optionally, current usage when deciding whether to evict an LRU model before
loading another. The default :class:`SystemMemoryProbe` reports host RAM via
``psutil``; a hardware backend may later supply a device-memory probe (CUDA /
ROCm / Metal VRAM). This module imports no vendor SDK.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import psutil


class MemoryProbe(ABC):
    """Reports memory usage in megabytes (MiB)."""

    @abstractmethod
    def used_mb(self) -> int:
        ...

    @abstractmethod
    def total_mb(self) -> int:
        ...

    def available_mb(self) -> int:
        return max(0, self.total_mb() - self.used_mb())


class SystemMemoryProbe(MemoryProbe):
    """Host RAM via ``psutil`` — the hardware-neutral default."""

    def used_mb(self) -> int:
        return int(psutil.virtual_memory().used / (1024 * 1024))

    def total_mb(self) -> int:
        return int(psutil.virtual_memory().total / (1024 * 1024))


class FixedMemoryProbe(MemoryProbe):
    """Deterministic probe for tests — set ``used``/``total`` explicitly."""

    def __init__(self, used_mb: int = 0, total_mb: int = 0) -> None:
        self._used = used_mb
        self._total = total_mb

    def used_mb(self) -> int:
        return self._used

    def total_mb(self) -> int:
        return self._total

    def set_used(self, mb: int) -> None:
        self._used = mb

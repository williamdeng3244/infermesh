# SPDX-License-Identifier: Apache-2.0
"""BackendFactory — turn a :class:`ModelSpec` into an :class:`InferenceBackend`.

Backends self-describe by name. The chosen class is ``spec.backend`` (if set)
else the factory's configured default. Known backends are imported lazily so
that, e.g., installing/importing the control plane never requires ``vllm``.
"""

from __future__ import annotations

import importlib
from typing import Type

from infermesh.core.backend import InferenceBackend, ModelSpec


class BackendFactory:
    """Maps a backend name to an :class:`InferenceBackend` class and instantiates it."""

    # name -> (module path, class name). Lazy so optional engine deps (vllm) are
    # only imported when that backend is actually requested.
    _LAZY: dict[str, tuple[str, str]] = {
        "mock": ("infermesh.backends.mock.mock_backend", "MockEchoBackend"),
        "vllm": ("infermesh.backends.vllm.vllm_backend", "VLLMBackend"),
    }

    # Eagerly-registered classes (via register()) take precedence over _LAZY.
    _registry: dict[str, Type[InferenceBackend]] = {}

    def __init__(self, default_backend: str = "mock") -> None:
        self.default_backend = default_backend

    @classmethod
    def register(cls, name: str, backend_cls: Type[InferenceBackend]) -> None:
        """Register (or override) a backend class under ``name``."""
        cls._registry[name] = backend_cls

    def _resolve(self, name: str) -> Type[InferenceBackend]:
        if name in self._registry:
            return self._registry[name]
        if name in self._LAZY:
            module_path, cls_name = self._LAZY[name]
            module = importlib.import_module(module_path)
            backend_cls = getattr(module, cls_name)
            self._registry[name] = backend_cls
            return backend_cls
        raise ValueError(
            f"Unknown backend '{name}'. Known: {self.known_backends()}"
        )

    def create(self, spec: ModelSpec) -> InferenceBackend:
        """Instantiate the backend for ``spec`` (one instance == one model)."""
        name = spec.backend or self.default_backend
        backend_cls = self._resolve(name)
        return backend_cls()

    def known_backends(self) -> list[str]:
        return sorted(set(self._registry) | set(self._LAZY))

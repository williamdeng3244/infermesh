# SPDX-License-Identifier: Apache-2.0
"""MockEchoBackend — a zero-dependency backend for tests and CI.

No GPU, no model download, no engine. It echoes the last user message back as a
whitespace-tokenized stream so the entire api <-> pool <-> backend stack is
exercisable without hardware. This is what CI runs.
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator, Optional

from infermesh.api.adapters.base import InternalRequest, StreamChunk
from infermesh.core.backend import (
    BackendCaps,
    EngineStats,
    HardwareInfo,
    HealthStatus,
    InferenceBackend,
    ModelSpec,
)


class MockEchoBackend(InferenceBackend):
    """Echoes the last user message, one whitespace token per stream chunk."""

    def __init__(self) -> None:
        self._spec: Optional[ModelSpec] = None
        self._loaded: bool = False
        self._mem_mb: int = 0

    @property
    def backend_name(self) -> str:
        return "mock"

    def capabilities(self) -> BackendCaps:
        return BackendCaps(streaming=True, tool_calling=True)

    def hardware(self) -> HardwareInfo:
        return HardwareInfo(vendor="cpu", device_count=0, mem_per_device_mb=0,
                            detail={"engine": "mock-echo"})

    async def load(self, spec: ModelSpec) -> None:
        # No I/O. Tests can set a per-model footprint via spec.extra["mock_mem_mb"]
        # to drive the pool's LRU-eviction policy deterministically.
        self._spec = spec
        self._mem_mb = int(spec.extra.get("mock_mem_mb", 512))
        self._loaded = True

    async def unload(self) -> None:
        self._loaded = False
        self._mem_mb = 0

    async def health(self) -> HealthStatus:
        return HealthStatus(healthy=self._loaded,
                            detail="loaded" if self._loaded else "not loaded")

    @staticmethod
    def _last_user_text(req: InternalRequest) -> str:
        for msg in reversed(req.messages):
            if msg.role == "user":
                return msg.content or ""
        return req.messages[-1].content if req.messages else ""

    async def chat_stream(self, req: InternalRequest) -> AsyncIterator[StreamChunk]:
        if not self._loaded:
            raise RuntimeError("MockEchoBackend.chat_stream() called before load()")
        prompt = self._last_user_text(req)
        tokens = prompt.split()
        prompt_tokens = max(1, len(tokens))
        if not tokens:
            tokens = [""]  # still emit one terminal chunk for empty prompts
        n = len(tokens)
        for i, tok in enumerate(tokens):
            is_last = i == n - 1
            await asyncio.sleep(0.005)  # make streaming observable
            yield StreamChunk(
                text=tok + " ",
                is_first=(i == 0),
                is_last=is_last,
                finish_reason="stop" if is_last else None,
                # token counts conventionally land on the last chunk only
                prompt_tokens=prompt_tokens if is_last else 0,
                completion_tokens=n if is_last else 0,
            )

    def stats(self) -> EngineStats:
        return EngineStats(
            model_id=self._spec.model_id if self._spec else "",
            loaded=self._loaded,
            prompt_tps=42.0,
            generation_tps=21.0,
            queue_depth=0,
            active_requests=0,
            used_mem_mb=self._mem_mb if self._loaded else 0,
            kv_cache_hit_rate=0.0,
            extra={"engine": "mock-echo"},
        )

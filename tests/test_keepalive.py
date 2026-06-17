# SPDX-License-Identifier: Apache-2.0
"""SSE keep-alive: a slow first token emits ': keep-alive' comments (M9)."""

import asyncio
from typing import AsyncIterator

from fastapi.testclient import TestClient

from infermesh.api.adapters.base import InternalRequest, StreamChunk
from infermesh.core.backend import (
    BackendCaps,
    EngineStats,
    HardwareInfo,
    HealthStatus,
    InferenceBackend,
    ModelSpec,
)
from infermesh.core.factory import BackendFactory
from infermesh.core.pool import ModelPool
from infermesh.core.settings import Settings
from infermesh.server import create_app


class _SlowBackend(InferenceBackend):
    """Sleeps before the first token so the keep-alive timer fires during 'prefill'."""

    @property
    def backend_name(self) -> str:
        return "slow"

    def capabilities(self) -> BackendCaps:
        return BackendCaps(streaming=True)

    def hardware(self) -> HardwareInfo:
        return HardwareInfo(vendor="cpu")

    async def load(self, spec: ModelSpec) -> None:
        self._mid = spec.model_id

    async def unload(self) -> None:
        pass

    async def health(self) -> HealthStatus:
        return HealthStatus(healthy=True)

    async def chat_stream(self, req: InternalRequest) -> AsyncIterator[StreamChunk]:
        await asyncio.sleep(0.18)  # > keepalive interval set on the app below
        yield StreamChunk(text="hi", is_first=True)
        yield StreamChunk(text="", is_last=True, finish_reason="stop",
                          prompt_tokens=1, completion_tokens=1)

    def stats(self) -> EngineStats:
        return EngineStats(model_id=getattr(self, "_mid", "slow-1"), loaded=True, used_mem_mb=0)


def _slow_client(keepalive: float) -> TestClient:
    BackendFactory.register("slow", _SlowBackend)
    pool = ModelPool(BackendFactory(default_backend="slow"))
    pool.discover_models([ModelSpec(model_id="slow-1", source="/tmp/slow", backend="slow",
                                    extra={"estimated_mb": 0})])
    return TestClient(create_app(pool, Settings(sse_keepalive_interval=keepalive)))


def test_sse_keepalive_during_prefill():
    client = _slow_client(0.05)
    with client.stream("POST", "/v1/chat/completions", json={
        "model": "slow-1", "messages": [{"role": "user", "content": "hi"}], "stream": True,
    }) as r:
        assert r.status_code == 200
        text = "".join(r.iter_text())
    assert ": keep-alive" in text   # >=1 keepalive emitted during the ~0.18s prefill gap
    assert "data:" in text          # and the real token stream still followed


def test_no_keepalive_when_disabled():
    client = _slow_client(0.0)
    with client.stream("POST", "/v1/chat/completions", json={
        "model": "slow-1", "messages": [{"role": "user", "content": "hi"}], "stream": True,
    }) as r:
        text = "".join(r.iter_text())
    assert ": keep-alive" not in text
    assert "data:" in text

# SPDX-License-Identifier: Apache-2.0
"""Optional power/counter capability on the backend ABC (Milestone 2, commit 4):
safe defaults, mock synthetic curve, and benchmark-time aggregation."""

import pytest

from infermesh.backends.mock.mock_backend import MockEchoBackend
from infermesh.backends.openai.openai_backend import OpenAICompatBackend
from infermesh.backends.transformers.transformers_backend import TransformersBackend
from infermesh.backends.vllm.vllm_backend import VLLMBackend
from infermesh.core.backend import (
    BackendCaps,
    EngineStats,
    HardwareInfo,
    HealthStatus,
    InferenceBackend,
    ModelSpec,
)
from infermesh.core.benchmark import run_benchmark


class _MinimalBackend(InferenceBackend):
    """Implements only the abstract surface — the conformance baseline."""

    @property
    def backend_name(self) -> str:
        return "minimal"

    def capabilities(self) -> BackendCaps:
        return BackendCaps()

    def hardware(self) -> HardwareInfo:
        return HardwareInfo()

    async def load(self, spec: ModelSpec) -> None:
        pass

    async def unload(self) -> None:
        pass

    async def health(self) -> HealthStatus:
        return HealthStatus(healthy=True)

    async def chat_stream(self, req):
        raise NotImplementedError
        yield  # pragma: no cover - marks this as an async generator

    def stats(self) -> EngineStats:
        return EngineStats(model_id="minimal")


def test_abc_optional_methods_default_to_none():
    b = _MinimalBackend()
    assert b.get_power_w() is None
    assert b.hw_counters() is None


def test_real_backends_inherit_safe_defaults():
    # None of the shipped hardware backends override the optional methods yet;
    # they must resolve to the ABC's safe defaults (no AttributeError ever).
    for cls in (OpenAICompatBackend, TransformersBackend, VLLMBackend):
        assert cls.get_power_w is InferenceBackend.get_power_w, cls
        assert cls.hw_counters is InferenceBackend.hw_counters, cls


async def test_mock_reports_synthetic_power_curve():
    b = MockEchoBackend()
    assert b.get_power_w() is None  # unloaded => unsupported
    await b.load(ModelSpec(model_id="m", source="/tmp/m"))
    vals = [b.get_power_w() for _ in range(10)]
    assert all(85.0 <= v <= 115.0 for v in vals)
    assert len({round(v, 3) for v in vals}) > 1  # a curve, not a constant
    await b.unload()
    assert b.get_power_w() is None


async def test_benchmark_aggregates_power_and_energy(mock_pool):
    r = await run_benchmark(mock_pool, "echo-1", requests=3, concurrency=2, max_tokens=8)
    assert r["power_avg_w"] is not None and 85.0 <= r["power_avg_w"] <= 115.0
    assert r["energy_j"] is not None and r["energy_j"] > 0
    # energy is the rectangle integral: average draw × wall time
    assert r["energy_j"] == pytest.approx(r["power_avg_w"] * r["wall_time_s"], rel=0.05)

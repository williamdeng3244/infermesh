# SPDX-License-Identifier: Apache-2.0
"""ModelPool lifecycle: discovery, lease, LRU eviction, pinning, TTL (S9 test 2)."""

import asyncio

import pytest

from infermesh.core.backend import ModelSpec
from infermesh.core.factory import BackendFactory
from infermesh.core.pool import InsufficientMemoryError, ModelPool
from infermesh.core.registry import ModelRegistry


def _spec(name: str, mb: int = 512) -> ModelSpec:
    return ModelSpec(model_id=name, source=f"/tmp/{name}", backend="mock",
                     extra={"mock_mem_mb": mb})


async def test_discover_three_models(fake_model_dir):
    specs = ModelRegistry(default_backend="mock").discover(fake_model_dir)
    pool = ModelPool(BackendFactory(default_backend="mock"))
    pool.discover_models(specs)
    assert len(pool.get_model_ids()) == 3
    assert sorted(pool.get_model_ids()) == ["alpha", "beta", "gamma"]


async def test_acquire_loads_then_release():
    pool = ModelPool(BackendFactory(default_backend="mock"))
    pool.discover_models([_spec("A")])
    assert pool.get_loaded_model_ids() == []
    async with pool.acquire("A") as backend:
        assert backend.backend_name == "mock"
        assert pool.get_entry("A").in_use == 1
        assert "A" in pool.get_loaded_model_ids()
    # lease released, but model stays loaded
    assert pool.get_entry("A").in_use == 0
    assert "A" in pool.get_loaded_model_ids()


async def test_lru_eviction_and_pin_protection():
    # 700 MB ceiling fits exactly one 512 MB model.
    pool = ModelPool(BackendFactory(default_backend="mock"), max_memory_mb=700)
    pool.discover_models([_spec("A"), _spec("B"), _spec("C")])

    await pool.get_engine("A")
    await pool.get_engine("B")  # must evict LRU 'A'
    assert "A" not in pool.get_loaded_model_ids()
    assert pool.get_loaded_model_ids() == ["B"]

    # Pin B; loading C cannot evict the only loaded (pinned) model -> refuse.
    pool.set_pinned("B", True)
    with pytest.raises(InsufficientMemoryError):
        await pool.get_engine("C")
    assert "B" in pool.get_loaded_model_ids()  # pinned model never evicted


async def test_ttl_unloads_idle_unpinned():
    pool = ModelPool(BackendFactory(default_backend="mock"), idle_timeout=0.1)
    pool.discover_models([_spec("T"), _spec("P")])
    await pool.get_engine("T")
    await pool.get_engine("P")
    pool.set_pinned("P", True)

    await asyncio.sleep(0.15)
    expired = await pool.check_ttl_expirations(0.1)
    assert "T" in expired
    assert "T" not in pool.get_loaded_model_ids()
    assert "P" in pool.get_loaded_model_ids()  # pinned skips TTL

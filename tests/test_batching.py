# SPDX-License-Identifier: Apache-2.0
"""Micro-batcher (M16): coalesces concurrent submits into batched run_batch calls.
No torch — run_batch is a fake that records batch sizes."""

import asyncio

import pytest

from infermesh.backends.transformers.batching import MicroBatcher


async def test_microbatcher_coalesces():
    seen = []

    def run_batch(reqs):
        seen.append(len(reqs))
        return [f"r{x}" for x in reqs]

    mb = MicroBatcher(run_batch, max_batch=8, window_s=0.05)
    results = await asyncio.gather(*[mb.submit(i) for i in range(6)])
    assert results == [f"r{i}" for i in range(6)]   # each future gets its own result, in order
    assert sum(seen) == 6                            # every request ran exactly once
    assert max(seen) > 1                             # and at least some were batched together


async def test_microbatcher_respects_max_batch():
    seen = []

    def run_batch(reqs):
        seen.append(len(reqs))
        return list(reqs)

    mb = MicroBatcher(run_batch, max_batch=3, window_s=0.05)
    await asyncio.gather(*[mb.submit(i) for i in range(7)])
    assert sum(seen) == 7 and max(seen) <= 3


async def test_microbatcher_propagates_errors():
    def run_batch(reqs):
        raise ValueError("boom")

    mb = MicroBatcher(run_batch, max_batch=4, window_s=0.02)
    with pytest.raises(ValueError):
        await mb.submit(1)

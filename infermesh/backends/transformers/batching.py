# SPDX-License-Identifier: Apache-2.0
"""Micro-batching for the in-process Transformers backend.

Concurrent requests are collected in a short time window and run as a single
batched ``generate`` (static batching) to lift throughput under load — a bounded,
backend-local take on continuous batching (vLLM does true token-level batching in
its own process). ``run_batch`` is an injected sync callable ``list[req] ->
list[result]`` (run in a worker thread), so the batching logic is testable without
torch.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, List


class MicroBatcher:
    """Coalesce concurrent submit() calls into batched run_batch() calls."""

    def __init__(self, run_batch: Callable[[List[Any]], List[Any]],
                 max_batch: int = 8, window_s: float = 0.01):
        self._run_batch = run_batch
        self._max = max(1, int(max_batch))
        self._window = max(0.0, float(window_s))
        self._queue: asyncio.Queue = asyncio.Queue()
        self._worker = None

    async def submit(self, req: Any) -> Any:
        loop = asyncio.get_event_loop()
        fut = loop.create_future()
        await self._queue.put((req, fut))
        if self._worker is None or self._worker.done():
            self._worker = asyncio.ensure_future(self._loop())
        return await fut

    async def _loop(self) -> None:
        while not self._queue.empty():
            batch = [await self._queue.get()]
            # Fill the batch with anything that arrives within the window.
            while len(batch) < self._max:
                try:
                    batch.append(await asyncio.wait_for(self._queue.get(), timeout=self._window))
                except asyncio.TimeoutError:
                    break
            reqs = [r for r, _ in batch]
            try:
                results = await asyncio.to_thread(self._run_batch, reqs)
                for (_r, fut), res in zip(batch, results):
                    if not fut.done():
                        fut.set_result(res)
            except Exception as exc:  # noqa: BLE001 - fail the whole batch's futures
                for _r, fut in batch:
                    if not fut.done():
                        fut.set_exception(exc)

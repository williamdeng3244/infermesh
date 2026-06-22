# SPDX-License-Identifier: Apache-2.0
"""Control-plane admission control.

A concurrency gate that caps the number of in-flight requests, queues the excess
in FIFO order up to a bound, and rejects (``Overloaded`` -> HTTP 503) when the
queue is full or the admission wait times out.

Pure ``asyncio`` -- no ``torch`` / vendor imports -- so it lives in the control
plane. It makes ``max_concurrent_requests`` actually enforced and yields accurate
active/queued counts regardless of whether a backend self-reports them.
"""

from __future__ import annotations

import asyncio
from typing import Optional


class Overloaded(Exception):
    """Raised by :meth:`AdmissionController.acquire` when the server is at
    capacity and the queue is full (or the admission wait timed out)."""

    def __init__(self, active: int, waiting: int):
        self.active = active
        self.waiting = waiting
        super().__init__(f"server at capacity (active={active}, waiting={waiting})")


class AdmissionController:
    """Caps concurrency at ``cap`` with an optional bounded FIFO wait queue.

    - ``max_queue`` (falsy => unbounded): once this many requests are already
      waiting, further arrivals are rejected with :class:`Overloaded` instead of
      queueing.
    - ``timeout`` (falsy => wait forever): a request that waits longer than this
      for a slot is rejected with :class:`Overloaded`.
    """

    def __init__(self, cap: int = 8, max_queue: Optional[int] = None,
                 timeout: Optional[float] = None):
        self._cap = max(1, int(cap))
        self._max_queue = int(max_queue) if max_queue else None
        self._timeout = float(timeout) if timeout else None
        self._active = 0
        self._waiting = 0
        self._cond = asyncio.Condition()

    def configure(self, cap=None, max_queue=None, timeout=None) -> None:
        """Live-adjust limits. New limits apply to subsequent arrivals and take
        effect for current waiters as slots free up."""
        if cap is not None:
            self._cap = max(1, int(cap))
        if max_queue is not None:
            self._max_queue = int(max_queue) if max_queue else None
        if timeout is not None:
            self._timeout = float(timeout) if timeout else None

    def snapshot(self) -> dict:
        return {"cap": self._cap, "active": self._active, "waiting": self._waiting,
                "max_queue": self._max_queue or 0}

    async def acquire(self) -> None:
        """Acquire one slot, blocking (and queueing) if at capacity. Raises
        :class:`Overloaded` if the queue is full or the wait times out."""
        async with self._cond:
            # Fast path: free slot and nobody ahead of us (preserve FIFO fairness).
            if self._active < self._cap and self._waiting == 0:
                self._active += 1
                return
            if self._max_queue is not None and self._waiting >= self._max_queue:
                raise Overloaded(self._active, self._waiting)
            self._waiting += 1
            try:
                loop = asyncio.get_running_loop()
                deadline = None if self._timeout is None else loop.time() + self._timeout
                while self._active >= self._cap:
                    if deadline is None:
                        await self._cond.wait()
                        continue
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        raise Overloaded(self._active, self._waiting)
                    try:
                        await asyncio.wait_for(self._cond.wait(), remaining)
                    except asyncio.TimeoutError:
                        raise Overloaded(self._active, self._waiting)
                self._active += 1
            finally:
                self._waiting -= 1

    async def release(self) -> None:
        """Release a previously-acquired slot and wake the next waiter."""
        async with self._cond:
            self._active = max(0, self._active - 1)
            self._cond.notify(1)

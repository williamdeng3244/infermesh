# SPDX-License-Identifier: Apache-2.0
"""Background benchmark jobs (control plane).

``POST /api/benchmark`` used to run the whole benchmark inside the HTTP request
(up to 240 s) and bypassed admission control. A *job* moves that work into a
background task that (a) holds one admission-gate slot while it runs — so
benchmarks and live inference share the same concurrency budget instead of
trampling each other — and (b) reports progress and supports cooperative
cancellation, checked at request boundaries.

Jobs are in-memory only: a hub restart forgets the job table, while completed
results live on in the benchmark history and the community library. Pure
asyncio + stdlib — no vendor imports.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import OrderedDict
from typing import Awaitable, Callable, Optional

TERMINAL_STATES = frozenset({"done", "failed", "cancelled"})
_MAX_KEPT = 100  # terminal jobs retained (oldest evicted first)


class JobCancelled(Exception):
    """Raised inside the job machinery when a cancel request wins a race."""


class BenchJob:
    """One benchmark job: spec, live state machine, progress, and results.

    States: ``queued`` → ``running`` → ``done`` | ``failed`` | ``cancelled``.
    (A job cancelled while still queued goes straight to ``cancelled``.)
    """

    __slots__ = ("job_id", "spec", "state", "progress", "result_run_ids",
                 "result", "error", "created_at", "started_at", "finished_at",
                 "cancel_event", "task")

    def __init__(self, spec: dict):
        self.job_id = uuid.uuid4().hex[:12]
        self.spec = dict(spec)
        self.state = "queued"
        self.progress: dict = {"phase": "queued", "current": 0,
                               "total": int(spec.get("requests") or 0)}
        self.result_run_ids: list[str] = []
        self.result: Optional[dict] = None
        self.error: Optional[str] = None
        self.created_at = time.time()
        self.started_at: Optional[float] = None
        self.finished_at: Optional[float] = None
        self.cancel_event = asyncio.Event()
        self.task: Optional[asyncio.Task] = None

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id, "spec": self.spec, "state": self.state,
            "progress": dict(self.progress), "result_run_ids": list(self.result_run_ids),
            "result": self.result, "error": self.error,
            "created_at": self.created_at, "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    def _finish(self, state: str, error: Optional[str] = None) -> None:
        self.state = state
        self.error = error
        self.finished_at = time.time()
        self.progress["phase"] = state


class BenchJobManager:
    """In-memory job table + the run loop that ties a job to the admission gate."""

    def __init__(self) -> None:
        self._jobs: "OrderedDict[str, BenchJob]" = OrderedDict()

    # ------------------------------ table ------------------------------- #
    def create(self, spec: dict) -> BenchJob:
        job = BenchJob(spec)
        self._jobs[job.job_id] = job
        self._evict()
        return job

    def get(self, job_id: str) -> Optional[BenchJob]:
        return self._jobs.get(job_id)

    def list(self) -> list[dict]:
        return [j.to_dict() for j in reversed(self._jobs.values())]

    def _evict(self) -> None:
        terminal = [j for j in self._jobs.values() if j.state in TERMINAL_STATES]
        for j in terminal[: max(0, len(terminal) - _MAX_KEPT)]:
            self._jobs.pop(j.job_id, None)

    def request_cancel(self, job_id: str) -> bool:
        """Flag a job for cooperative cancellation. Returns False for unknown
        or already-terminal jobs. The runner observes the flag at the next
        request boundary; a still-queued job finishes as ``cancelled`` without
        ever taking a gate slot."""
        job = self._jobs.get(job_id)
        if job is None or job.state in TERMINAL_STATES:
            return False
        job.cancel_event.set()
        return True

    # ------------------------------ runner ------------------------------ #
    async def run(self, job: BenchJob,
                  runner: Callable[[BenchJob], Awaitable[tuple[Optional[dict], list[str]]]],
                  gate=None) -> None:
        """Drive one job to a terminal state.

        Acquires one slot on ``gate`` (the shared AdmissionController) for the
        whole run and always releases it. ``runner(job)`` performs the actual
        benchmark and returns ``(result, run_ids)``; it must check
        ``job.cancel_event`` at iteration boundaries.
        """
        held = False
        try:
            if job.cancel_event.is_set():
                raise JobCancelled()
            if gate is not None:
                job.progress["phase"] = "waiting"
                await self._acquire_or_cancel(gate, job)
                held = True
            if job.cancel_event.is_set():
                raise JobCancelled()
            job.state = "running"
            job.started_at = time.time()
            job.progress["phase"] = "running"
            result, run_ids = await runner(job)
            if job.cancel_event.is_set():
                job.result = result  # keep any partial numbers for inspection
                job._finish("cancelled")
            else:
                job.result = result
                job.result_run_ids = run_ids
                job._finish("done")
        except JobCancelled:
            job._finish("cancelled")
        except asyncio.CancelledError:  # server shutdown tore the task down
            job._finish("cancelled", "server shutdown")
            raise
        except Exception as exc:  # noqa: BLE001 - job errors land in the job record
            job._finish("failed", str(exc))
        finally:
            if held and gate is not None:
                await gate.release()

    @staticmethod
    async def _acquire_or_cancel(gate, job: BenchJob) -> None:
        """gate.acquire() racing job.cancel_event; raises JobCancelled if the
        cancel wins (releasing the slot if acquire landed concurrently)."""
        acquire = asyncio.ensure_future(gate.acquire())
        cancel = asyncio.ensure_future(job.cancel_event.wait())
        try:
            done, _ = await asyncio.wait({acquire, cancel},
                                         return_when=asyncio.FIRST_COMPLETED)
            if acquire in done:
                acquire.result()  # propagates Overloaded
                return
            acquire.cancel()
            try:
                await acquire
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            else:
                await gate.release()  # acquire won the race after all
            raise JobCancelled()
        finally:
            cancel.cancel()

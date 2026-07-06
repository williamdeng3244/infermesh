# SPDX-License-Identifier: Apache-2.0
"""Background benchmark jobs (Milestone 2, commit 0): state machine, progress,
cooperative cancellation, and admission-gate budget sharing."""

import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from infermesh.core.bench_jobs import BenchJobManager
from infermesh.core.scheduler import AdmissionController
from infermesh.core.settings import Settings
from infermesh.server import create_app


@pytest.fixture
def jobs_client(mock_pool, tmp_path, monkeypatch):
    # Point the history store at a temp dir: entering the client context below
    # runs the app lifespan, which would otherwise load the developer's real
    # ~/.infermesh metrics into the module-global _METRICS deque (and our runs
    # would append to their real benchmarks.jsonl).
    from infermesh.core import history as h
    hist = tmp_path / "history"
    monkeypatch.setattr(h, "HISTORY_DIR", hist)
    monkeypatch.setattr(h, "METRICS_FILE", hist / "metrics.jsonl")
    monkeypatch.setattr(h, "BENCH_FILE", hist / "benchmarks.jsonl")
    # Enter the context manager: that keeps one event loop alive across
    # requests, so the create_task'd job actually progresses between polls
    # (a bare TestClient spins a fresh loop per request and strands the task).
    with TestClient(create_app(mock_pool, Settings())) as c:
        yield c


def _wait_terminal(client, job_id: str, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    d: dict = {}
    while time.time() < deadline:
        d = client.get(f"/api/bench/jobs/{job_id}").json()
        if d["state"] in ("done", "failed", "cancelled"):
            return d
        time.sleep(0.05)
    raise AssertionError(f"job never reached a terminal state: {d}")


# ------------------------------- HTTP layer ------------------------------- #

def test_job_lifecycle_done(jobs_client):
    r = jobs_client.post("/api/bench/jobs", json={
        "model": "echo-1", "requests": 2, "concurrency": 1, "max_tokens": 8})
    assert r.status_code == 202
    body = r.json()
    assert body["state"] in ("queued", "running")
    d = _wait_terminal(jobs_client, body["job_id"])
    assert d["state"] == "done"
    assert d["error"] is None
    assert d["result"]["succeeded"] == 2 and d["result"]["failed"] == 0
    assert d["progress"]["current"] == 2 and d["progress"]["total"] == 2
    assert len(d["result_run_ids"]) == 1
    assert d["started_at"] and d["finished_at"] >= d["started_at"]
    listed = jobs_client.get("/api/bench/jobs").json()["jobs"]
    assert any(j["job_id"] == body["job_id"] for j in listed)


def test_job_unknown_model_404(jobs_client):
    assert jobs_client.post("/api/bench/jobs", json={"model": "nope"}).status_code == 404


def test_job_unknown_id_404(jobs_client):
    assert jobs_client.get("/api/bench/jobs/deadbeef0000").status_code == 404
    assert jobs_client.post("/api/bench/jobs/deadbeef0000/cancel").status_code == 404


def test_job_cancel_midflight(jobs_client):
    # 200 serial requests x 8 tokens x 5 ms/chunk ≈ 8 s — the cancel lands mid-run.
    r = jobs_client.post("/api/bench/jobs", json={
        "model": "echo-1", "requests": 200, "concurrency": 1, "max_tokens": 8})
    jid = r.json()["job_id"]
    c = jobs_client.post(f"/api/bench/jobs/{jid}/cancel")
    assert c.status_code == 200 and c.json()["ok"] is True
    d = _wait_terminal(jobs_client, jid)
    assert d["state"] == "cancelled"
    assert d["result_run_ids"] == []  # cancelled runs are never recorded
    assert d["progress"]["current"] < 200
    # cancelling an already-terminal job is a no-op
    again = jobs_client.post(f"/api/bench/jobs/{jid}/cancel").json()
    assert again["ok"] is False and again["state"] == "cancelled"


# ---------------- manager level (deterministic state machine) ---------------- #

async def _spin(predicate, timeout: float = 2.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("condition never became true")
        await asyncio.sleep(0.01)


async def test_manager_holds_one_gate_slot():
    gate = AdmissionController(cap=1)
    mgr = BenchJobManager()
    job = mgr.create({"requests": 1})
    release = asyncio.Event()

    async def runner(j):
        await release.wait()
        return {"ok": True}, ["run-1"]

    task = asyncio.create_task(mgr.run(job, runner, gate=gate))
    await _spin(lambda: job.state == "running")
    assert gate.snapshot()["active"] == 1  # the job occupies the shared budget
    release.set()
    await task
    assert job.state == "done" and job.result_run_ids == ["run-1"]
    assert gate.snapshot()["active"] == 0  # slot released


async def test_manager_cancel_while_queued():
    gate = AdmissionController(cap=1)
    mgr = BenchJobManager()
    hold = asyncio.Event()

    async def holder(j):
        await hold.wait()
        return None, []

    first = mgr.create({"requests": 1})
    t1 = asyncio.create_task(mgr.run(first, holder, gate=gate))
    await _spin(lambda: first.state == "running")

    second = mgr.create({"requests": 1})
    t2 = asyncio.create_task(mgr.run(second, holder, gate=gate))
    await _spin(lambda: second.progress["phase"] == "waiting")
    assert second.state == "queued"

    assert mgr.request_cancel(second.job_id) is True
    await t2
    assert second.state == "cancelled"
    assert gate.snapshot()["active"] == 1  # first still holds the only slot

    hold.set()
    await t1
    assert first.state == "done"
    assert gate.snapshot()["active"] == 0


async def test_manager_runner_failure():
    gate = AdmissionController(cap=2)
    mgr = BenchJobManager()
    job = mgr.create({"requests": 1})

    async def boom(j):
        raise ValueError("backend exploded")

    await mgr.run(job, boom, gate=gate)
    assert job.state == "failed" and "backend exploded" in job.error
    assert gate.snapshot()["active"] == 0


async def test_manager_cancel_before_start():
    mgr = BenchJobManager()
    job = mgr.create({"requests": 1})
    assert mgr.request_cancel(job.job_id) is True

    async def never(j):  # pragma: no cover - must not be reached
        raise AssertionError("runner ran on a pre-cancelled job")

    await mgr.run(job, never, gate=None)
    assert job.state == "cancelled"

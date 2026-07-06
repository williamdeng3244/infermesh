# SPDX-License-Identifier: Apache-2.0
"""Concurrency sweep (Milestone 2, commit 6): child/parent structure,
percentile monotonicity, job recording, and the slo_p99_ttft_s setting."""

import time

import pytest

from infermesh.core import community
from infermesh.core.settings import Settings
from infermesh.core.sweep import run_concurrency_sweep

# jobs_client comes from conftest.py (context-entered client + history isolation)


def _wait_terminal(client, job_id: str, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    d: dict = {}
    while time.time() < deadline:
        d = client.get(f"/api/bench/jobs/{job_id}").json()
        if d["state"] in ("done", "failed", "cancelled"):
            return d
        time.sleep(0.05)
    raise AssertionError(f"job never reached a terminal state: {d}")


async def test_sweep_children_and_frontier_structure(mock_pool):
    parent = await run_concurrency_sweep(
        mock_pool, "echo-1", levels=[1, 2, 4], window_s=0.5, max_tokens=8)
    assert parent["mode"] == "concurrency_sweep"
    assert parent["levels"] == [1, 2, 4]
    assert len(parent["children"]) == 3 and len(parent["frontier"]) == 3
    for child, point in zip(parent["children"], parent["frontier"]):
        assert child["concurrency"] == point["concurrency"]
        assert child["n_requests"] > 0
        assert child["succeeded"] == child["n_requests"] and child["failed"] == 0
        p = child["percentiles"]["ttft"]
        assert p["p50"] <= p["p90"] <= p["p99"] <= p["p999"]  # monotone by construction
        pi = child["percentiles"]["itl"]
        assert pi["p50"] <= pi["p90"] <= pi["p99"] <= pi["p999"]
        assert child["cv_itl"] is not None and child["cv_itl"] >= 0
        assert point["throughput"] == child["output_tokens_per_sec"]
        assert point["p99_ttft_s"] == pytest.approx(p["p99"] / 1000.0, abs=1e-3)


async def test_sweep_levels_are_sorted_and_deduped(mock_pool):
    parent = await run_concurrency_sweep(
        mock_pool, "echo-1", levels=[4, 1, 4, 2], window_s=0.3, max_tokens=8)
    assert parent["levels"] == [1, 2, 4]


def test_sweep_job_records_child_runs(jobs_client):
    r = jobs_client.post("/api/bench/jobs", json={
        "model": "echo-1", "mode": "concurrency_sweep",
        "levels": [1, 2], "window_s": 0.3, "max_tokens": 8})
    assert r.status_code == 202
    d = _wait_terminal(jobs_client, r.json()["job_id"])
    assert d["state"] == "done", d["error"]
    res = d["result"]
    assert len(res["frontier"]) == 2 and len(d["result_run_ids"]) == 2
    assert res["run_id"]  # the parent aggregate got its own history run id
    assert d["progress"]["current"] == 2 and d["progress"]["total"] == 2
    rows = [x for x in community.query_runs() if x.get("percentiles")]
    assert len(rows) == 2
    assert sorted(x["batch_size"] for x in rows) == [1, 2]
    for x in rows:
        assert x["n_requests"] > 0
        assert x["cv_itl"] is not None
        assert x["percentiles"]["ttft"]["p50"] > 0
    assert {x["run_id"] for x in rows} == set(d["result_run_ids"])


def test_slo_setting_default_and_live_update(client, monkeypatch):
    monkeypatch.setattr(Settings, "save", lambda self, *a, **k: None)
    assert client.get("/api/settings").json()["slo_p99_ttft_s"] == 2.0
    body = client.put("/api/settings", json={"slo_p99_ttft_s": 1.5}).json()
    assert "slo_p99_ttft_s" in body["updated"]
    assert client.get("/api/settings").json()["slo_p99_ttft_s"] == 1.5

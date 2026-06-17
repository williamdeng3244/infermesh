# SPDX-License-Identifier: Apache-2.0
"""Benchmark runner + /api/benchmark endpoint + dashboard tab (Milestone 7)."""

from infermesh.core.benchmark import run_benchmark


async def test_run_benchmark_mock(mock_pool):
    r = await run_benchmark(mock_pool, "echo-1", requests=10, concurrency=4, max_tokens=16)
    assert r["succeeded"] == 10 and r["failed"] == 0
    assert r["requests"] == 10 and r["concurrency"] == 4
    assert r["requests_per_sec"] > 0 and r["output_tokens_per_sec"] > 0
    for key in ("mean", "p50", "p90", "p99", "min", "max"):
        assert r["latency_ms"][key] >= 0
    assert r["ttft_ms"]["mean"] >= 0
    assert r["latency_ms"]["p99"] >= r["latency_ms"]["p50"]


def test_benchmark_endpoint(client):
    r = client.post("/api/benchmark", json={
        "model": "echo-1", "requests": 8, "concurrency": 2, "max_tokens": 16,
    })
    assert r.status_code == 200
    d = r.json()
    assert d["succeeded"] == 8 and d["failed"] == 0
    assert {"latency_ms", "ttft_ms", "requests_per_sec", "output_tokens_per_sec",
            "total_output_tokens", "wall_time_s"} <= set(d.keys())


def test_benchmark_unknown_model_404(client):
    assert client.post("/api/benchmark", json={"model": "does-not-exist"}).status_code == 404


def test_dashboard_has_benchmark_section(client):
    html = client.get("/admin").text
    for marker in ("sec-benchmark", 'id="bmRun"', 'data-sec="benchmark"', "runBenchmark"):
        assert marker in html, marker

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


async def test_benchmark_comprehensive_metrics(mock_pool):
    r = await run_benchmark(mock_pool, "echo-1", requests=8, concurrency=4, max_tokens=16, mode="same")
    assert r["mode"] == "same"
    for key in ("pp_tps", "tg_tps"):
        assert r[key]["mean"] >= 0 and r[key]["max"] >= 0
    for k in ("mean", "p50", "p90", "p99", "min", "max"):
        assert r["tpot_ms"][k] >= 0
    assert r["total_prompt_tokens"] > 0
    assert r["peak_mem_mb"] is None or r["peak_mem_mb"] >= 0


async def test_benchmark_modes_differ(mock_pool):
    same = await run_benchmark(mock_pool, "echo-1", requests=6, concurrency=2, max_tokens=12, mode="same")
    diff = await run_benchmark(mock_pool, "echo-1", requests=6, concurrency=2, max_tokens=12, mode="different")
    assert same["mode"] == "same" and diff["mode"] == "different"
    # "different" prepends a unique leading prompt -> at least as many prompt tokens
    assert diff["total_prompt_tokens"] >= same["total_prompt_tokens"]


def test_benchmark_endpoint_mode(client):
    r = client.post("/api/benchmark", json={
        "model": "echo-1", "requests": 4, "concurrency": 2, "max_tokens": 8, "mode": "different"})
    assert r.status_code == 200
    d = r.json()
    assert d["mode"] == "different"
    assert {"pp_tps", "tg_tps", "tpot_ms", "peak_mem_mb", "total_prompt_tokens"} <= set(d)


def test_dashboard_has_benchmark_modes(client):
    html = client.get("/admin").text
    for marker in ('id="bmMode"', 'id="bmSingle"', 'id="bmCopy"', 'id="bmTpot"',
                   "Prefill (PP)", "Decode (TG)"):
        assert marker in html, marker

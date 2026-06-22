# SPDX-License-Identifier: Apache-2.0
"""Aggregate stats (M19): session + persisted all-time scopes, /api/stats, UI panel."""

from infermesh.core.stats import StatsAccumulator


def test_accumulator_derives_metrics(tmp_path):
    s = StatsAccumulator(path=tmp_path / "stats.json")
    s.record(prompt_tokens=100, completion_tokens=40, cached_tokens=20, prefill_s=0.1, generation_s=0.4)
    snap = s.snapshot("session")
    assert snap["total_requests"] == 1 and snap["total_tokens_served"] == 140
    assert snap["total_cached_tokens"] == 20 and snap["cache_efficiency"] == 20.0   # 20/100*100
    assert snap["generation_tps"] == 100.0          # 40 / 0.4
    assert snap["prefill_tps"] == 800.0             # (100-20) / 0.1, cached excluded
    assert s.snapshot("alltime")["total_requests"] == 1


def test_clear_scopes_are_independent(tmp_path):
    s = StatsAccumulator(path=tmp_path / "stats.json")
    s.record(prompt_tokens=10, completion_tokens=5)
    s.clear("session")
    assert s.snapshot("session")["total_requests"] == 0
    assert s.snapshot("alltime")["total_requests"] == 1   # all-time kept
    s.clear("alltime")
    assert s.snapshot("alltime")["total_requests"] == 0


def test_alltime_persists_across_instances(tmp_path):
    p = tmp_path / "stats.json"
    s = StatsAccumulator(path=p)
    for _ in range(25):           # > _SAVE_EVERY -> flushed to disk
        s.record(prompt_tokens=2, completion_tokens=1)
    s2 = StatsAccumulator(path=p)  # fresh instance == a "restart"
    assert s2.snapshot("alltime")["total_requests"] >= 20   # survived
    assert s2.snapshot("session")["total_requests"] == 0    # session starts fresh


def test_api_stats_endpoint(client):
    client.post("/v1/chat/completions", json={"model": "echo-1", "messages": [{"role": "user", "content": "hi"}]})
    s = client.get("/api/stats?scope=session").json()
    assert s["scope"] == "session" and s["total_requests"] >= 1 and s["total_tokens_served"] >= 1
    assert client.get("/api/stats?scope=alltime").json()["scope"] == "alltime"
    assert client.post("/api/stats/clear?scope=session").json()["cleared"] == "session"


def test_dashboard_has_stats_panel(client):
    html = client.get("/admin").text
    for m in ('id="stScopeSession"', 'id="stScopeAll"', 'id="stClear"',
              "function refreshStats", "Cache efficiency", "/api/stats"):
        assert m in html, m

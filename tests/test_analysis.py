# SPDX-License-Identifier: Apache-2.0
"""Read-side analysis API (Milestone 2, commit 8): efficiency, frontier +
goodput vs SLO, scaling, driver timeline with regression flags, and compare."""

import pytest

from infermesh.core import analysis, community, specs


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    """Fresh 5s-TTL cache per test + no user chip-spec overrides."""
    monkeypatch.setattr(specs, "HOME_DIR", tmp_path)
    analysis.cache_clear()
    yield
    analysis.cache_clear()


def _submit(**kw) -> dict:
    base = dict(submitter="rig", chip="Enflame S60", vendor="enflame",
                model="Qwen2.5-7B-Instruct", quant="fp16", context_length=2048)
    base.update(kw)
    return community.submit(base)


def test_params_from_model():
    assert analysis.params_from_model("Qwen2.5-7B-Instruct") == 7e9
    assert analysis.params_from_model("llama-3.1-70b") == 70e9
    assert analysis.params_from_model("phi-0.5B") == 5e8
    assert analysis.params_from_model("gpt-oss") is None
    assert analysis.params_from_model(None) is None
    assert analysis.params_from_model("model-8bit") is None  # quant, not size


def test_efficiency_joins_specs_and_latest_run():
    _submit(run_id="r1", submission_group="r1",
            tg_tps=12.0, pp_tps=350.0, power_avg_w=275.0)
    s60 = {c["chip"]: c for c in analysis.efficiency()["chips"]}["Enflame S60"]
    assert s60["spec_key"] == "s60"
    assert s60["mbu"] == pytest.approx(14e9 * 12 / 800e9, abs=1e-3)     # 0.21
    assert s60["mfu"] == pytest.approx(2 * 7e9 * 350 / 150e12, abs=1e-3)
    assert s60["tok_j"] == pytest.approx(12 / 275, abs=1e-4)
    assert s60["tok_j_basis"] == "measured"


def test_efficiency_tdp_fallback_and_unknown_chip():
    _submit(run_id="r1", submission_group="r1", tg_tps=10.0)  # no measured power
    _submit(run_id="r2", submission_group="r2", chip="Mystery X1", vendor="x",
            tg_tps=5.0)
    eff = {c["chip"]: c for c in analysis.efficiency()["chips"]}
    assert eff["Enflame S60"]["tok_j"] == pytest.approx(10 / 300, abs=1e-4)
    assert eff["Enflame S60"]["tok_j_basis"] == "tdp"
    assert eff["Mystery X1"]["spec_key"] is None
    assert eff["Mystery X1"]["mbu"] is None and eff["Mystery X1"]["mfu"] is None


def test_efficiency_soak_delta():
    for i, tg in enumerate([10.0, 10.0, 10.0, 9.0]):  # newest drifted down 10%
        _submit(run_id=f"s{i}", submission_group=f"s{i}", tg_tps=tg,
                created_at=1000.0 + i)
    s60 = {c["chip"]: c for c in analysis.efficiency()["chips"]}["Enflame S60"]
    assert s60["soak_delta_pct"] == pytest.approx(-10.0, abs=0.1)


def test_frontier_points_and_goodput_vs_slo():
    _submit(run_id="f1", submission_group="f1", batch_size=1,
            total_throughput=100.0, cv_itl=0.1, n_requests=10,
            percentiles={"ttft": {"p50": 100, "p90": 200, "p99": 500, "p999": 600}})
    _submit(run_id="f2", submission_group="f2", batch_size=2,
            total_throughput=180.0, cv_itl=0.2, n_requests=20,
            percentiles={"ttft": {"p50": 300, "p90": 900, "p99": 2500, "p999": 3000}})
    s = {x["chip"]: x for x in analysis.frontier("", 2.0)["series"]}["Enflame S60"]
    assert [p["concurrency"] for p in s["points"]] == [1, 2]
    assert s["points"][1]["p99_ttft_s"] == pytest.approx(2.5)
    # level 2 misses the 2 s SLO -> goodput comes from level 1
    assert s["goodput"] == 100.0 and s["goodput_concurrency"] == 1 and s["slo_met"]
    analysis.cache_clear()
    tight = analysis.frontier("", 0.1)["series"][0]
    assert tight["goodput"] is None and tight["slo_met"] is False  # prefill-bound
    analysis.cache_clear()
    assert analysis.frontier("No Such Chip", 2.0)["series"] == []


def test_scaling_speedup_and_efficiency():
    _submit(run_id="a1", submission_group="a1", total_throughput=100.0, device_count=1)
    _submit(run_id="a2", submission_group="a2", total_throughput=110.0, device_count=1)
    _submit(run_id="a3", submission_group="a3", total_throughput=180.0,
            device_count=2, parallelism={"tp": 2})
    sc = analysis.scaling(model="Qwen", quant="fp16")
    assert sc["baseline_median"] == pytest.approx(105.0)
    pts = {p["device_count"]: p for p in sc["points"]}
    assert pts[1]["n_runs"] == 2
    assert pts[2]["speedup"] == pytest.approx(180 / 105, abs=1e-3)
    assert pts[2]["efficiency"] == pytest.approx(180 / 105 / 2, abs=1e-3)


def test_timeline_orders_by_first_seen_and_flags_regressions():
    _submit(run_id="t1", submission_group="t1", driver_version="drv-1.0",
            tg_tps=12.0, ttft_ms=100.0, created_at=1000.0)
    _submit(run_id="t2", submission_group="t2", driver_version="drv-1.0",
            tg_tps=12.2, ttft_ms=100.0, created_at=1001.0)
    _submit(run_id="t3", submission_group="t3", driver_version="drv-1.1",
            tg_tps=11.0, ttft_ms=103.0, created_at=2000.0)
    tl = analysis.timeline("Enflame S60", "tg")
    assert [p["driver_version"] for p in tl["points"]] == ["drv-1.0", "drv-1.1"]
    assert tl["points"][0]["delta_pct"] is None
    assert tl["points"][1]["regression"] is True          # tg −9.9%
    tt = analysis.timeline("Enflame S60", "ttft")
    assert tt["higher_is_better"] is False
    assert tt["points"][1]["regression"] is True          # ttft +3%


def test_compare_verdicts_and_threshold():
    a = _submit(run_id="c1", submission_group="c1",
                tg_tps=100.0, ttft_ms=100.0, pp_tps=1000.0)
    b = _submit(run_id="c2", submission_group="c2",
                tg_tps=95.0, ttft_ms=101.0, pp_tps=1010.0)
    res = analysis.compare(a["id"], b["id"], 2.0)
    d = res["deltas"]
    assert d["tg_tps"]["delta_pct"] == pytest.approx(-5.0) and d["tg_tps"]["verdict"] == "worse"
    assert d["ttft_ms"]["verdict"] == "same"   # +1% within the band
    assert d["pp_tps"]["verdict"] == "same"
    strict = analysis.compare(a["id"], b["id"], 0.5)["deltas"]
    assert strict["ttft_ms"]["verdict"] == "worse"   # latency up, tight band
    assert strict["pp_tps"]["verdict"] == "better"
    assert analysis.compare("nope00000000", a["id"]) is None


def test_http_endpoints(client):
    a = _submit(run_id="h1", submission_group="h1", tg_tps=10.0)
    b = _submit(run_id="h2", submission_group="h2", tg_tps=11.0)
    assert client.get("/api/analysis/efficiency").status_code == 200
    assert client.get("/api/analysis/frontier?slo=1.5").json()["slo_p99_ttft_s"] == 1.5
    assert client.get("/api/analysis/scaling?model=Qwen").status_code == 200
    assert client.get("/api/analysis/timeline?chip=Enflame%20S60&metric=tg").status_code == 200
    assert client.get("/api/analysis/timeline?metric=bogus").status_code == 400
    ok = client.get(f"/api/compare?a={a['id']}&b={b['id']}")
    assert ok.status_code == 200 and ok.json()["threshold_pct"] == 2.0
    assert client.get("/api/compare?a=nope&b=alsonope").status_code == 404

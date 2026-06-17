# SPDX-License-Identifier: Apache-2.0
"""M11 observability: device enumeration, run-history persistence, dashboard wiring."""

from infermesh.core import history
from infermesh.core.devices import enumerate_devices

_KEYS = {"id", "vendor", "name", "mem_total_mb", "mem_used_mb", "mem_free_mb"}


def test_enumerate_devices_includes_cpu():
    devs = enumerate_devices()
    assert devs and devs[-1]["vendor"] == "cpu"
    for d in devs:
        assert _KEYS <= set(d)


def test_api_devices_endpoint(client):
    d = client.get("/api/devices").json()
    assert "devices" in d and any(x["vendor"] == "cpu" for x in d["devices"])


def test_history_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "METRICS_FILE", tmp_path / "m.jsonl")
    monkeypatch.setattr(history, "BENCH_FILE", tmp_path / "b.jsonl")
    monkeypatch.setattr(history, "HISTORY_DIR", tmp_path)
    assert history.load_benchmarks() == [] and history.load_metrics() == []
    history.append_benchmark({"t": 1.0, "model": "x", "params": {"requests": 4},
                              "result": {"requests_per_sec": 9}})
    history.append_metric({"t": 1.0, "model": "x", "latency_ms": 5, "tokens": 2, "tps": 4})
    b, m = history.load_benchmarks(), history.load_metrics()
    assert len(b) == 1 and b[0]["model"] == "x" and b[0]["result"]["requests_per_sec"] == 9
    assert len(m) == 1 and m[0]["tokens"] == 2


def test_benchmark_persists_to_history(client, tmp_path, monkeypatch):
    monkeypatch.setattr(history, "METRICS_FILE", tmp_path / "m.jsonl")
    monkeypatch.setattr(history, "BENCH_FILE", tmp_path / "b.jsonl")
    monkeypatch.setattr(history, "HISTORY_DIR", tmp_path)
    client.post("/api/benchmark", json={"model": "echo-1", "requests": 4, "concurrency": 2, "max_tokens": 8})
    hist = client.get("/api/history").json()
    assert len(hist["benchmarks"]) >= 1 and hist["benchmarks"][-1]["model"] == "echo-1"


def test_dashboard_has_devices_and_history(client):
    html = client.get("/admin").text
    for marker in ('data-sec="devices"', 'id="sec-devices"', 'id="devSel"', 'id="bmHist"',
                   "refreshDevices", "loadDevicePicker", "refreshBenchHistory"):
        assert marker in html, marker

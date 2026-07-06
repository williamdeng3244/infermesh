# SPDX-License-Identifier: Apache-2.0
"""Multi-device benchmarks (Milestone 2, commit 5): data-parallel child runs,
tensor-parallel group runs, the vLLM tp mapping, and interconnect detection."""

import time

import pytest

from infermesh.core import community
from infermesh.core import devices as devices_mod
from infermesh.core.backend import ModelSpec

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


def test_data_parallel_one_child_run_per_device(jobs_client):
    r = jobs_client.post("/api/bench/jobs", json={
        "model": "echo-1", "requests": 2, "concurrency": 1, "max_tokens": 8,
        "devices": ["cpu:0", "cpu:1"]})
    assert r.status_code == 202
    d = _wait_terminal(jobs_client, r.json()["job_id"])
    assert d["state"] == "done", d["error"]
    assert len(d["result_run_ids"]) == 2
    assert len(set(d["result_run_ids"])) == 2  # two distinct recorded runs
    res = d["result"]
    assert res["mode"] == "data_parallel"
    assert [c["device"] for c in res["children"]] == ["cpu:0", "cpu:1"]
    per_dev = [c["result"]["output_tokens_per_sec"] for c in res["children"]]
    assert res["combined_output_tokens_per_sec"] == pytest.approx(sum(per_dev), abs=0.2)
    assert d["progress"]["current"] == 4 and d["progress"]["total"] == 4
    # both child runs landed in the community store with the right v2 fields
    rows = [x for x in community.query_runs() if x.get("parallelism") == {"dp": 2}]
    assert len(rows) == 2
    assert all(x["device_count"] == 1 for x in rows)
    assert {x["run_id"] for x in rows} == set(d["result_run_ids"])


def test_tensor_parallel_single_group_run(jobs_client, mock_pool):
    r = jobs_client.post("/api/bench/jobs", json={
        "model": "echo-1", "requests": 2, "concurrency": 1, "max_tokens": 8,
        "devices": ["cpu:0", "cpu:1"], "parallelism": {"tp": 2}})
    d = _wait_terminal(jobs_client, r.json()["job_id"])
    assert d["state"] == "done", d["error"]
    assert len(d["result_run_ids"]) == 1  # the whole group is one run
    assert d["result"]["device_count"] == 2
    assert d["result"]["parallelism"] == {"tp": 2}
    # the neutral hint reached the model spec for the backend to map at load
    assert mock_pool.get_entry("echo-1").spec.extra["parallelism"] == {"tp": 2}
    rows = [x for x in community.query_runs() if x.get("parallelism") == {"tp": 2}]
    assert len(rows) == 1 and rows[0]["device_count"] == 2


def test_vllm_maps_tp_to_tensor_parallel_size():
    from infermesh.backends.vllm.vllm_backend import VLLMBackend, _tp_size
    spec = ModelSpec(model_id="m", source="/models/m",
                     extra={"parallelism": {"tp": 2}})
    cmd = VLLMBackend._build_launch_cmd(spec, 8000)
    i = cmd.index("--tensor-parallel-size")
    assert cmd[i + 1] == "2"
    assert _tp_size(spec) == 2
    # absent / malformed hint => no flag
    plain = ModelSpec(model_id="m", source="/models/m")
    assert "--tensor-parallel-size" not in VLLMBackend._build_launch_cmd(plain, 8000)
    assert _tp_size(ModelSpec(model_id="m", source="/m",
                              extra={"parallelism": {"tp": "x"}})) == 1
    # an explicit vllm_args entry wins over the neutral hint (no duplicate)
    both = ModelSpec(model_id="m", source="/models/m",
                     extra={"parallelism": {"tp": 2},
                            "vllm_args": {"tensor-parallel-size": 4}})
    cmd = VLLMBackend._build_launch_cmd(both, 8000)
    assert cmd.count("--tensor-parallel-size") == 1
    assert cmd[cmd.index("--tensor-parallel-size") + 1] == "4"


def test_detect_interconnect_nvidia_topo(monkeypatch):
    nvlink_topo = ("        GPU0    GPU1    CPU Affinity\n"
                   "GPU0     X      NV2     0-31\n"
                   "GPU1    NV2      X      0-31\n")
    monkeypatch.setattr(devices_mod, "_run", lambda cmd: nvlink_topo)
    assert devices_mod.detect_interconnect("nvidia") == "nvlink"

    pcie_topo = ("        GPU0    GPU1\n"
                 "GPU0     X      PHB\n"
                 "GPU1    PHB      X\n")
    monkeypatch.setattr(devices_mod, "_run", lambda cmd: pcie_topo)
    assert devices_mod.detect_interconnect("nvidia") == "pcie"


def test_detect_interconnect_registry_fallback(monkeypatch, tmp_path):
    from infermesh.core import specs
    monkeypatch.setattr(specs, "HOME_DIR", tmp_path)  # no user overrides
    monkeypatch.setattr(devices_mod, "_run", lambda cmd: None)  # no nvidia-smi
    assert devices_mod.detect_interconnect("enflame", "Enflame S60") == "esl"
    assert devices_mod.detect_interconnect("nvidia", "NVIDIA A100") == "nvlink"
    assert devices_mod.detect_interconnect(None, "Totally Unknown") is None

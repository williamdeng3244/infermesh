# SPDX-License-Identifier: Apache-2.0
"""Chip spec registry (Milestone 2, commit 2): built-ins, user overrides,
validation, alias resolution, and the GET/PUT /api/specs endpoints."""

import pytest
from fastapi.testclient import TestClient

from infermesh.core import specs
from infermesh.core.settings import Settings
from infermesh.server import create_app


@pytest.fixture(autouse=True)
def _isolate_user_specs(tmp_path, monkeypatch):
    """Point the user override file at a temp dir (never ~/.infermesh)."""
    monkeypatch.setattr(specs, "HOME_DIR", tmp_path)


def test_builtin_entries_present_and_valid():
    s = specs.load()
    assert {"s60", "a100", "rtx4090", "m3max"} <= set(s)
    assert specs.validate(s) == []
    for key in ("s60", "a100", "rtx4090", "m3max"):
        entry = s[key]
        for field in specs.REQUIRED_NUMERIC:
            assert entry[field] > 0, (key, field)
        assert entry.get("source"), key  # datasheet/estimated annotation required


def test_user_override_merges_per_field():
    specs.save_user({
        "s60": {"tdp_w": 320.0},  # partial tweak of a builtin
        "gx1": {"name": "GX-1 (in-house sample)", "peak_bw_gbps": 1200.0,
                "peak_tflops_fp16": 220.0, "tdp_w": 350.0,
                "interconnect": "esl", "source": "measured"},
    })
    s = specs.load()
    assert s["s60"]["tdp_w"] == 320.0
    assert s["s60"]["peak_bw_gbps"] == 800.0  # untouched builtin fields survive
    assert s["gx1"]["peak_tflops_fp16"] == 220.0
    assert specs.user_path().exists()


def test_save_user_rejects_invalid_and_writes_nothing():
    with pytest.raises(ValueError):
        specs.save_user({"gx1": {"peak_bw_gbps": -5, "peak_tflops_fp16": 1, "tdp_w": 1}})
    with pytest.raises(ValueError):
        specs.save_user({"gx1": "not-a-dict"})
    with pytest.raises(ValueError):  # new chip missing required numerics
        specs.save_user({"gx2": {"name": "GX-2"}})
    assert not specs.user_path().exists()


def test_partial_override_of_builtin_is_valid_but_partial_new_chip_is_not():
    merged = specs.save_user({"a100": {"tdp_w": 300.0}})  # SXM->PCIe power tweak
    assert merged["a100"]["tdp_w"] == 300.0 and merged["a100"]["peak_bw_gbps"] == 2039.0


def test_resolve_by_key_name_and_alias():
    assert specs.resolve("Enflame S60")[0] == "s60"
    assert specs.resolve("NVIDIA GeForce RTX 4090")[0] == "rtx4090"
    assert specs.resolve("a100")[0] == "a100"
    assert specs.resolve("APPLE m3-max")[0] == "m3max"  # case/punct-insensitive
    assert specs.resolve("Unknown Chip 9000") is None
    assert specs.resolve("") is None


def test_api_get_and_put(client):
    r = client.get("/api/specs")
    assert r.status_code == 200 and "s60" in r.json()["specs"]
    ok = client.put("/api/specs", json={"specs": {"s60": {"tdp_w": 305.0}}})
    assert ok.status_code == 200 and ok.json()["specs"]["s60"]["tdp_w"] == 305.0
    bad = client.put("/api/specs", json={"specs": {"gx9": {"peak_bw_gbps": 0}}})
    assert bad.status_code == 400


def test_put_specs_requires_api_key_when_set(mock_pool):
    c = TestClient(create_app(mock_pool, Settings(api_key="sek")))
    assert c.put("/api/specs", json={"specs": {}}).status_code == 401
    ok = c.put("/api/specs", json={"specs": {}}, headers={"x-api-key": "sek"})
    assert ok.status_code == 200

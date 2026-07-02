# SPDX-License-Identifier: Apache-2.0
"""HF downloader core — search, size, background download, additive pool registration
(M13). Network is mocked via the _hf_* wrappers; no huggingface_hub calls happen."""

import os
import time

import pytest

import infermesh.core.downloader as dl
from infermesh.core.backend import ModelSpec
from infermesh.core.factory import BackendFactory
from infermesh.core.pool import ModelPool


class _M:
    def __init__(self, id, downloads=0, likes=0, tag=None):
        self.id, self.downloads, self.likes, self.pipeline_tag, self.gated = id, downloads, likes, tag, False


class _Info:
    def __init__(self, sizes):
        self.siblings = [type("S", (), {"size": s})() for s in sizes]


@pytest.fixture(autouse=True)
def _inprocess_downloads(monkeypatch):
    """Run downloads in-process (production uses a killable subprocess) so the
    _hf_snapshot/_ms_snapshot monkeypatches apply; isolate job state per test."""
    monkeypatch.setattr(dl, "subprocess_downloads", False)
    dl._JOBS.clear()
    dl._PROCS.clear()
    yield
    dl._JOBS.clear()
    dl._PROCS.clear()


def test_search_models(monkeypatch):
    monkeypatch.setattr(dl, "_hf_list_models",
                        lambda q, l, **k: [_M("org/alpha", 100, 5, "text-generation"), _M("org/beta", 50)])
    r = dl.search_models("alpha", 10)
    assert [m["id"] for m in r] == ["org/alpha", "org/beta"]
    assert r[0]["downloads"] == 100 and r[0]["likes"] == 5 and r[0]["pipeline_tag"] == "text-generation"


def test_model_size_bytes(monkeypatch):
    monkeypatch.setattr(dl, "_hf_model_info", lambda rid: _Info([1000, 2000, 50]))
    assert dl.model_size_bytes("org/x") == 3050


def test_download_lifecycle(tmp_path, monkeypatch):
    dl._JOBS.clear()
    monkeypatch.setattr(dl, "_hf_model_info", lambda rid: _Info([10, 20]))

    def fake_snap(rid, dest):
        os.makedirs(dest, exist_ok=True)
        with open(os.path.join(dest, "config.json"), "w") as fh:
            fh.write("{}")
        return dest
    monkeypatch.setattr(dl, "_hf_snapshot", fake_snap)

    job = dl.start_download("org/My-Model", str(tmp_path))
    assert job["status"] in ("queued", "downloading") and job["model_id"] == "My-Model"
    st = {}
    for _ in range(100):  # mocked snapshot is instant; wait for the daemon thread
        st = {j["repo_id"]: j for j in dl.downloads_status()}["org/My-Model"]
        if st["status"] in ("done", "error"):
            break
        time.sleep(0.02)
    assert st["status"] == "done", st.get("error")
    assert st["progress"] == 1.0
    assert (tmp_path / "My-Model" / "config.json").exists()
    assert any(j["model_id"] == "My-Model" for j in dl.completed_jobs())


def test_pool_add_spec_is_additive():
    pool = ModelPool(BackendFactory(default_backend="mock"))
    pool.discover_models([ModelSpec(model_id="a", source="/a", backend="mock", extra={"mock_mem_mb": 10})])
    pool.add_spec(ModelSpec(model_id="b", source="/b", backend="mock", extra={"mock_mem_mb": 10}))
    assert {"a", "b"} <= set(pool.get_model_ids())   # add_spec did NOT drop "a"


def _app(tmp_path):
    from fastapi.testclient import TestClient
    from infermesh.core.settings import Settings
    from infermesh.server import create_app
    pool = ModelPool(BackendFactory(default_backend="mock"))
    pool.discover_models([ModelSpec(model_id="echo-1", source="/tmp/echo-1", backend="mock", extra={"mock_mem_mb": 64})])
    return TestClient(create_app(pool, Settings(model_dir=str(tmp_path)))), pool


def test_hf_search_endpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(dl, "_hf_list_models", lambda q, l, **k: [_M("org/x", 9, 1, "text-generation")])
    client, _ = _app(tmp_path)
    r = client.get("/api/hf/search?q=x")
    assert r.status_code == 200 and r.json()["models"][0]["id"] == "org/x"


def test_hf_search_sort_task_passthrough(tmp_path, monkeypatch):
    seen = {}

    def fake(q, l, sort="downloads", task=None):
        seen.update(q=q, sort=sort, task=task)
        return [_M("org/y", 1, 0, "image-text-to-text")]
    monkeypatch.setattr(dl, "_hf_list_models", fake)
    client, _ = _app(tmp_path)
    r = client.get("/api/hf/search?sort=trending_score&task=image-text-to-text").json()  # empty q -> popular
    assert seen["q"] == "" and seen["sort"] == "trending_score" and seen["task"] == "image-text-to-text"
    assert r["models"][0]["id"] == "org/y" and r["sort"] == "trending_score"
    bad = client.get("/api/hf/search?sort=bogus").json()   # invalid sort falls back, never 500
    assert bad["sort"] == "downloads"


def test_hf_download_and_autoregister(tmp_path, monkeypatch):
    dl._JOBS.clear()
    monkeypatch.setattr(dl, "_hf_model_info", lambda rid: _Info([5]))

    def fake_snap(rid, dest):
        os.makedirs(dest, exist_ok=True)
        with open(os.path.join(dest, "config.json"), "w") as fh:
            fh.write("{}")
        return dest
    monkeypatch.setattr(dl, "_hf_snapshot", fake_snap)

    client, pool = _app(tmp_path)
    r = client.post("/api/hf/download", json={"repo_id": "org/New-Model"})
    assert r.status_code == 200 and r.json()["model_id"] == "New-Model"
    st = {}
    for _ in range(100):
        st = {j["repo_id"]: j for j in client.get("/api/hf/downloads").json()["downloads"]}.get("org/New-Model", {})
        if st.get("status") in ("done", "error"):
            break
        time.sleep(0.02)
    assert st.get("status") == "done"
    client.get("/api/hf/downloads")  # ensure auto-register ran
    assert pool.get_entry("New-Model") is not None   # downloaded model appears without a restart


def test_hf_download_requires_model_dir(client):
    assert client.post("/api/hf/download", json={"repo_id": "org/x"}).status_code == 400


def test_dashboard_has_download_tab(client):
    html = client.get("/admin").text
    for marker in ('data-sec="download"', 'id="sec-download"', 'id="dlSearch"', "runHfSearch", "hfDownload",
                   'id="dlSort"', 'id="dlTask"', 'id="msdlId"', 'id="msdlBtn"', "ModelScope (by model ID)"):
        assert marker in html, marker


def test_set_endpoint():
    dl.set_endpoint("https://hf-mirror.com")
    assert dl._endpoint == "https://hf-mirror.com"
    dl.set_endpoint("")
    assert dl._endpoint is None          # blank clears -> default hub


def test_settings_put_hf_endpoint(client, monkeypatch):
    from infermesh.core.settings import Settings
    monkeypatch.setattr(Settings, "save", lambda self, *a, **k: None)
    r = client.put("/api/settings", json={"hf_endpoint": "https://hf-mirror.com"}).json()
    assert "hf_endpoint" in r["updated"] and r["settings"]["hf_endpoint"] == "https://hf-mirror.com"
    assert dl._endpoint == "https://hf-mirror.com"   # applied to the live downloader
    dl.set_endpoint(None)                            # reset for other tests


def test_start_download_routes_to_modelscope(tmp_path, monkeypatch):
    dl._JOBS.clear()
    calls = {}

    def fake_ms(rid, dest):
        calls["rid"] = rid
        os.makedirs(dest, exist_ok=True)
        with open(os.path.join(dest, "config.json"), "w") as fh:
            fh.write("{}")
        return dest
    monkeypatch.setattr(dl, "_ms_snapshot", fake_ms)
    job = dl.start_download("Qwen/Q", str(tmp_path), source="modelscope")
    assert job["source"] == "modelscope"
    st = {}
    for _ in range(100):
        st = {j["repo_id"]: j for j in dl.downloads_status()}["Qwen/Q"]
        if st["status"] in ("done", "error"):
            break
        time.sleep(0.02)
    assert st["status"] == "done", st.get("error")
    assert calls["rid"] == "Qwen/Q"   # routed to the ModelScope snapshot, not HF


def test_hf_download_endpoint_source_modelscope(tmp_path, monkeypatch):
    dl._JOBS.clear()

    def fake_ms(rid, dest):
        os.makedirs(dest, exist_ok=True)
        with open(os.path.join(dest, "config.json"), "w") as fh:
            fh.write("{}")
        return dest
    monkeypatch.setattr(dl, "_ms_snapshot", fake_ms)
    client, _ = _app(tmp_path)
    r = client.post("/api/hf/download", json={"repo_id": "org/M", "source": "modelscope"})
    assert r.status_code == 200 and r.json()["source"] == "modelscope"


def test_pause_download_terminates_and_marks_paused():
    class _H:
        def __init__(self):
            self.terminated = False

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return 0

    dl._JOBS["org/Big"] = {"repo_id": "org/Big", "status": "downloading", "path": "/tmp/none",
                           "total_bytes": 0, "downloaded_bytes": 0, "model_id": "Big",
                           "error": None, "source": "hf"}
    handle = _H()
    dl._PROCS["org/Big"] = handle
    res = dl.pause_download("org/Big")
    assert res["status"] == "paused" and handle.terminated


def _fake_snap(rid, dest):
    os.makedirs(dest, exist_ok=True)
    with open(os.path.join(dest, "config.json"), "w") as fh:
        fh.write("{}")
    return dest


def _wait_done(get_jobs, repo_id):
    for _ in range(100):
        st = {j["repo_id"]: j for j in get_jobs()}.get(repo_id, {})
        if st.get("status") in ("done", "error"):
            return st
        time.sleep(0.02)
    return {}


def test_delete_download_removes_files_and_job(tmp_path, monkeypatch):
    monkeypatch.setattr(dl, "_hf_model_info", lambda rid: _Info([10]))
    monkeypatch.setattr(dl, "_hf_snapshot", _fake_snap)
    dl.start_download("org/Del-Me", str(tmp_path))
    _wait_done(dl.downloads_status, "org/Del-Me")
    assert (tmp_path / "Del-Me" / "config.json").exists()
    res = dl.delete_download("org/Del-Me")
    assert res["deleted"] and res["files_removed"]
    assert not (tmp_path / "Del-Me").exists()
    assert "org/Del-Me" not in {j["repo_id"] for j in dl.downloads_status()}


def test_download_delete_endpoint_also_drops_from_pool(tmp_path, monkeypatch):
    monkeypatch.setattr(dl, "_hf_model_info", lambda rid: _Info([5]))
    monkeypatch.setattr(dl, "_hf_snapshot", _fake_snap)
    client, pool = _app(tmp_path)
    client.post("/api/hf/download", json={"repo_id": "org/Gone"})
    _wait_done(lambda: client.get("/api/hf/downloads").json()["downloads"], "org/Gone")
    assert (tmp_path / "Gone").exists() and pool.get_entry("Gone") is not None
    r = client.post("/api/hf/download/delete", json={"repo_id": "org/Gone"})
    assert r.status_code == 200 and r.json()["deleted"] and r.json()["files_removed"]
    assert not (tmp_path / "Gone").exists()
    assert pool.get_entry("Gone") is None


def test_delete_on_disk_model_without_job(tmp_path):
    # a model on disk with no tracked job (discovered after a restart) is still deletable
    (tmp_path / "Orphan").mkdir()
    (tmp_path / "Orphan" / "config.json").write_text("{}")
    client, _ = _app(tmp_path)
    r = client.post("/api/hf/download/delete", json={"repo_id": "Orphan"})
    assert r.status_code == 200 and r.json()["files_removed"]
    assert not (tmp_path / "Orphan").exists()


def test_require_ms_helpful_error_when_absent():
    import importlib.util
    import pytest
    if importlib.util.find_spec("modelscope") is not None:
        pytest.skip("modelscope is installed")
    with pytest.raises(RuntimeError, match="modelscope"):
        dl._require_ms()

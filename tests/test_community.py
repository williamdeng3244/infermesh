# SPDX-License-Identifier: Apache-2.0
"""Shared community benchmark library — store, endpoints, and auto-publish.

The autouse ``_isolate_community_db`` fixture (conftest) points the SQLite DB at a
per-test temp path, so these never touch the real ~/.infermesh.
"""

from infermesh.core import community


def _rec(**kw):
    base = dict(submitter="S60-box", chip="Enflame S60", vendor="enflame",
               model="Qwen2.5-7B", quant="fp16", context_length=1024,
               batch_size=1, pp_tps=600.0, tg_tps=12.4, peak_mem_gb=14.2)
    base.update(kw)
    return base


# ------------------------------- store unit ------------------------------- #

def test_store_submit_query_facets():
    community.submit(_rec())
    community.submit(_rec(chip="NVIDIA RTX 5070", vendor="nvidia",
                          context_length=4096, pp_tps=1180.0, tg_tps=41.0))
    assert community.count() == 2
    f = community.facets()
    assert set(f["chips"]) == {"Enflame S60", "NVIDIA RTX 5070"}
    assert 1024 in f["contexts"] and 4096 in f["contexts"]
    # min_pp filter keeps only the fast one
    assert len(community.query_runs(min_pp=1000)) == 1
    assert len(community.query_runs(chip="Enflame S60")) == 1
    assert len(community.query_runs(model="Qwen")) == 2  # substring match


def test_store_dedup_group_collapses_but_distinct_runs_accumulate():
    # same submission_group => idempotent (re-POST collapses)
    community.submit(_rec(submission_group="g1"))
    community.submit(_rec(submission_group="g1", pp_tps=999))
    assert community.count() == 1
    # a different group (or no group => fresh id) adds a distinct sample
    community.submit(_rec(submission_group="g2", pp_tps=640))
    assert community.count() == 2


def test_store_compare_boxplot():
    community.submit(_rec(pp_tps=600))
    community.submit(_rec(pp_tps=640))  # group-less => distinct
    out = community.compare("pp_tps", [{"chip": "Enflame S60",
                                        "model": "Qwen2.5-7B", "quant": "fp16"}])
    assert out["contexts"] == [1024]
    box = out["series"][0]["cells"]["1024"]
    assert box["n"] == 2 and box["min"] == 600.0 and box["max"] == 640.0
    assert box["median"] == 620.0 and box["points"] == [600.0, 640.0]


# ------------------------------- endpoints -------------------------------- #

def test_submit_and_runs_endpoint(client):
    r = client.post("/api/community/submit", json=_rec())
    assert r.status_code == 200 and r.json()["id"]
    body = client.get("/api/community/runs").json()
    assert len(body["runs"]) == 1
    assert body["facets"]["chips"] == ["Enflame S60"]
    assert body["runs"][0]["pp_tps"] == 600.0


def test_runs_filters(client):
    client.post("/api/community/submit", json=_rec())
    client.post("/api/community/submit", json=_rec(chip="NVIDIA RTX 5070",
                vendor="nvidia", pp_tps=1180.0, tg_tps=41.0))
    assert len(client.get("/api/community/runs", params={"min_tg": 30}).json()["runs"]) == 1
    assert len(client.get("/api/community/runs", params={"quant": "fp16"}).json()["runs"]) == 2
    assert len(client.get("/api/community/runs", params={"vendor": "nvidia"}).json()["runs"]) == 1


def test_compare_endpoint(client):
    client.post("/api/community/submit", json=_rec())
    series = '[{"chip":"Enflame S60","model":"Qwen2.5-7B","quant":"fp16"}]'
    out = client.get("/api/community/compare",
                     params={"metric": "tg_tps", "series": series}).json()
    assert out["metric"] == "tg_tps" and out["contexts"] == [1024]
    assert out["series"][0]["cells"]["1024"]["median"] == 12.4


def test_export_csv(client):
    client.post("/api/community/submit", json=_rec())
    r = client.get("/api/community/export.csv")
    assert r.status_code == 200 and "text/csv" in r.headers["content-type"]
    head = r.text.splitlines()[0]
    assert "chip" in head and "pp_tps" in head and "tg_tps" in head


def test_run_permalink_404(client):
    assert client.get("/api/community/run/does-not-exist").status_code == 404
    rid = client.post("/api/community/submit", json=_rec()).json()["id"]
    assert client.get("/api/community/run/" + rid).json()["model"] == "Qwen2.5-7B"


# ----------------------------- auto-publish ------------------------------- #

def test_benchmark_auto_publishes(client):
    before = len(client.get("/api/community/runs").json()["runs"])
    r = client.post("/api/benchmark", json={"model": "echo-1", "requests": 4,
                                            "concurrency": 2, "max_tokens": 8})
    assert r.status_code == 200
    runs = client.get("/api/community/runs").json()["runs"]
    assert len(runs) == before + 1
    assert runs[0]["model"] == "echo-1" and runs[0]["pp_tps"] is not None


def test_benchmark_share_false_skips_publish(client):
    r = client.post("/api/benchmark", json={"model": "echo-1", "requests": 4,
                                            "concurrency": 2, "max_tokens": 8,
                                            "share": False})
    assert r.status_code == 200
    assert client.get("/api/community/runs").json()["runs"] == []


# ------------------------------- dashboard -------------------------------- #

def test_dashboard_has_community_ui(client):
    html = client.get("/admin").text
    for marker in ('data-sec="explorer"', 'data-sec="community"',
                   'id="sec-explorer"', 'id="sec-community"',
                   'id="exChart"', 'id="exMetric"', 'id="exAdd"', 'id="exPoints"',
                   'id="cmRows"', 'id="cmChip"', 'id="cmMinPp"', 'id="cmMinTg"',
                   'id="bmShare"', 'id="setSubmitter"', 'id="setAutoPub"',
                   'id="saveCommunity"'):
        assert marker in html, marker


async def test_publish_to_hub_sends_bearer_key(monkeypatch):
    """A spoke pushing to a keyed hub must authenticate (hub_key setting) —
    without it, submissions to an auth-enabled hub 401 and are dropped."""
    import urllib.request

    from infermesh.server import _publish_to_hub

    seen = {}

    class _Resp:
        def read(self):
            return b"{}"

    def fake_urlopen(req, timeout=10):
        seen["url"] = req.full_url
        seen["auth"] = req.get_header("Authorization")
        return _Resp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    await _publish_to_hub("http://hub:8000/", {"x": 1}, key="sekrit")
    assert seen["url"] == "http://hub:8000/api/community/submit"
    assert seen["auth"] == "Bearer sekrit"

    await _publish_to_hub("http://hub:8000/", {"x": 1})   # keyless hub: no header
    assert seen["auth"] is None


def test_hub_key_setting_roundtrip(client, monkeypatch):
    from infermesh.core.settings import Settings

    monkeypatch.setattr(Settings, "save", lambda self, *a, **k: None)  # no disk write
    r = client.put("/api/settings", json={"hub_key": "k1"})
    d = r.json()
    assert "hub_key" in d["updated"]
    assert d["settings"]["hub_key"] is True          # redacted: set/unset only
    assert client.get("/api/settings").json()["hub_key"] is True
    r2 = client.put("/api/settings", json={"hub_key": ""})
    assert r2.json()["settings"]["hub_key"] is False

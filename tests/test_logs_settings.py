# SPDX-License-Identifier: Apache-2.0
"""Logs + settings endpoints and dashboard sections (Milestone 4)."""

import logging

from infermesh.core.settings import Settings


def test_logs_endpoint_captures_infermesh_logs(client):
    logging.getLogger("infermesh.testlog").info("marker-xyz-123")
    r = client.get("/api/logs")
    assert r.status_code == 200
    lines = r.json()["lines"]
    assert isinstance(lines, list)
    assert any("marker-xyz-123" in entry["line"] for entry in lines)
    assert all({"level", "line"} <= set(entry.keys()) for entry in lines)


def test_settings_get_redacts_api_key(client):
    s = client.get("/api/settings").json()
    assert isinstance(s["api_key"], bool)   # never the raw value
    assert "idle_timeout" in s and "backend" in s and "port" in s


def test_settings_put_idle_timeout_live(client, monkeypatch):
    monkeypatch.setattr(Settings, "save", lambda self, *a, **k: None)  # no disk write
    r = client.put("/api/settings", json={"idle_timeout": 0.25})
    assert r.status_code == 200
    body = r.json()
    assert "idle_timeout" in body["updated"]
    assert body["settings"]["idle_timeout"] == 0.25
    assert isinstance(body["settings"]["api_key"], bool)


def test_settings_put_api_key_toggles_auth(client, monkeypatch):
    monkeypatch.setattr(Settings, "save", lambda self, *a, **k: None)
    # enable auth at runtime
    client.put("/api/settings", json={"api_key": "secret"})
    assert client.get("/api/status").status_code == 401
    assert client.get("/api/status", headers={"Authorization": "Bearer secret"}).status_code == 200
    # disable again (this PUT must itself carry the key, since auth is now on)
    client.put("/api/settings", json={"api_key": ""}, headers={"Authorization": "Bearer secret"})
    assert client.get("/api/status").status_code == 200


def test_dashboard_has_all_sections(client):
    html = client.get("/admin").text
    for marker in ("sec-models", "sec-chat", "sec-logs", "sec-metrics", "sec-settings",
                   'id="chatInput"', 'id="logs"', 'id="setIdle"', 'id="setKvHot"', 'id="saveKv"',
                   'id="setHfEndpoint"', 'id="saveHf"', "chartLatency",
                   'id="setGenTemp"', 'id="saveGen"', "Generation defaults",
                   'class="prefill"', "msg-meta", 'id="themeBtn"', 'data-theme="light"'):
        assert marker in html, marker


def test_metrics_records_chat(client):
    before = len(client.get("/api/metrics").json()["samples"])
    client.post("/v1/chat/completions", json={
        "model": "echo-1", "messages": [{"role": "user", "content": "hi there"}],
    })
    samples = client.get("/api/metrics").json()["samples"]
    assert len(samples) > before
    last = samples[-1]
    assert {"t", "model", "latency_ms", "tokens", "tps"} <= set(last.keys())
    assert last["model"] == "echo-1" and last["latency_ms"] >= 0


def test_settings_put_kv_cache(client, mock_pool, monkeypatch):
    monkeypatch.setattr(Settings, "save", lambda self, *a, **k: None)
    body = client.put("/api/settings", json={"kv_hot_capacity": 12, "kv_cold_dir": "/tmp/kv"}).json()
    assert "kv_hot_capacity" in body["updated"] and "kv_cold_dir" in body["updated"]
    assert body["settings"]["kv_hot_capacity"] == 12 and body["settings"]["kv_cold_dir"] == "/tmp/kv"
    assert mock_pool.default_extra == {"prefix_kv": 12, "kv_cold_dir": "/tmp/kv"}   # applied globally


def test_settings_put_generation_defaults(client, monkeypatch):
    monkeypatch.setattr(Settings, "save", lambda self, *a, **k: None)
    r = client.put("/api/settings", json={"gen_temperature": 0.3, "gen_top_k": 40, "gen_max_tokens": 17}).json()
    for k in ("gen_temperature", "gen_top_k", "gen_max_tokens"):
        assert k in r["updated"]
    assert r["settings"]["gen_temperature"] == 0.3 and r["settings"]["gen_top_k"] == 40 and r["settings"]["gen_max_tokens"] == 17
    clamp = client.put("/api/settings", json={"gen_temperature": 9.9, "gen_top_p": 2.0, "gen_max_tokens": 0}).json()["settings"]
    assert clamp["gen_temperature"] == 2.0 and clamp["gen_top_p"] == 1.0 and clamp["gen_max_tokens"] == 1   # clamped
    cleared = client.put("/api/settings", json={"gen_temperature": None}).json()["settings"]
    assert cleared["gen_temperature"] is None          # explicit null clears the default


def test_apply_gen_defaults_only_fills_omitted():
    from infermesh.server import _apply_gen_defaults
    from infermesh.api.openai_models import ChatCompletionRequest
    msgs = [{"role": "user", "content": "hi"}]
    s = Settings(gen_temperature=0.2, gen_max_tokens=33)
    filled = _apply_gen_defaults(ChatCompletionRequest(model="m", messages=msgs), s)
    assert filled.temperature == 0.2 and filled.max_tokens == 33   # omitted -> server default
    kept = _apply_gen_defaults(ChatCompletionRequest(model="m", messages=msgs, temperature=0.9), s)
    assert kept.temperature == 0.9                                 # client value always wins
    none_default = _apply_gen_defaults(ChatCompletionRequest(model="m", messages=msgs), Settings())
    assert none_default.top_p is None                             # no default -> left for adapter fallback


async def test_pool_merges_default_extra_at_load(mock_pool):
    mock_pool.default_extra = {"prefix_kv": 8}
    async with mock_pool.acquire("echo-1"):
        pass
    assert mock_pool.get_entry("echo-1").spec.extra.get("prefix_kv") == 8   # global default reached the spec

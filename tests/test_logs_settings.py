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
                   'id="chatInput"', 'id="logs"', 'id="setIdle"', "chartLatency",
                   'id="themeBtn"', 'data-theme="light"'):
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

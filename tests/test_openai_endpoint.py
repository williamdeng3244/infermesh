# SPDX-License-Identifier: Apache-2.0
"""OpenAI-compatible endpoint tests (S9 test 3)."""

import json


def test_chat_completions_non_stream(client):
    r = client.post("/v1/chat/completions", json={
        "model": "echo-1",
        "messages": [{"role": "user", "content": "Hello world"}],
        "stream": False,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["object"] == "chat.completion"
    assert data["choices"][0]["message"]["content"].strip() == "Hello world"
    assert data["choices"][0]["finish_reason"] == "stop"
    assert data["usage"]["prompt_tokens"] >= 1
    assert data["usage"]["completion_tokens"] >= 1


def test_chat_completions_stream(client):
    with client.stream("POST", "/v1/chat/completions", json={
        "model": "echo-1",
        "messages": [{"role": "user", "content": "Hello world"}],
        "stream": True,
    }) as resp:
        assert resp.status_code == 200
        lines = [ln for ln in resp.iter_lines() if ln]

    data_lines = [ln for ln in lines if ln.startswith("data:")]
    assert len(data_lines) >= 2
    assert data_lines[-1].strip() == "data: [DONE]"

    streamed = ""
    for ln in data_lines:
        payload = ln[len("data:"):].strip()
        if payload == "[DONE]":
            continue
        delta = json.loads(payload)["choices"][0]["delta"]
        streamed += delta.get("content") or ""
    assert "Hello world" in streamed


def test_models_lists_mock_model(client):
    r = client.get("/v1/models")
    assert r.status_code == 200
    body = r.json()
    assert body["object"] == "list"
    assert "echo-1" in [m["id"] for m in body["data"]]

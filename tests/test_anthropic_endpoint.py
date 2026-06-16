# SPDX-License-Identifier: Apache-2.0
"""Anthropic-compatible endpoint tests (S9 test 4)."""


def test_messages_non_stream(client):
    r = client.post("/v1/messages", json={
        "model": "echo-1",
        "max_tokens": 64,
        "messages": [{"role": "user", "content": "Hello world"}],
        "stream": False,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["type"] == "message"
    assert data["role"] == "assistant"
    assert data["content"][0]["type"] == "text"
    assert "Hello world" in data["content"][0]["text"]


def test_messages_stream(client):
    with client.stream("POST", "/v1/messages", json={
        "model": "echo-1",
        "max_tokens": 64,
        "messages": [{"role": "user", "content": "Hello world"}],
        "stream": True,
    }) as resp:
        assert resp.status_code == 200
        body = "".join(resp.iter_text())

    # Anthropic streaming event sequence
    assert "event: message_start" in body
    assert "event: content_block_start" in body
    assert "event: content_block_delta" in body
    assert "event: message_stop" in body
    # echoed tokens streamed as text deltas
    assert "Hello" in body and "world" in body

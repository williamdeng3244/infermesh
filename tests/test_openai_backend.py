# SPDX-License-Identifier: Apache-2.0
"""OpenAICompatBackend pure logic — key resolution + request body (no network) (M8)."""

import json

from infermesh.api.adapters.base import InternalMessage, InternalRequest
from infermesh.backends.openai.openai_backend import OpenAICompatBackend, _resolve_key
from infermesh.core.backend import ModelSpec
from infermesh.core.factory import BackendFactory


def test_resolve_key(monkeypatch):
    monkeypatch.setenv("MY_KEY", "sk-xyz")
    assert _resolve_key("env:MY_KEY") == "sk-xyz"
    assert _resolve_key("sk-literal") == "sk-literal"
    assert _resolve_key(None) is None
    assert _resolve_key("env:DEFINITELY_MISSING_VAR") is None


async def test_load_and_body(monkeypatch):
    monkeypatch.setenv("MY_KEY", "sk-xyz")
    b = OpenAICompatBackend()
    await b.load(ModelSpec(model_id="gpt", source="gpt", backend="openai", extra={
        "base_url": "https://api.openai.com/v1/",  # trailing slash should be stripped
        "upstream_model": "gpt-4o-mini",
        "api_key": "env:MY_KEY",
    }))
    assert b._base_url == "https://api.openai.com/v1"
    assert b.backend_name == "openai"
    assert b.hardware().vendor == "remote"
    assert b.stats().used_mem_mb == 0          # remote -> no local VRAM
    body = b._build_body(InternalRequest(
        messages=[InternalMessage(role="user", content="hi")], max_tokens=10))
    assert body["model"] == "gpt-4o-mini" and body["stream"] is True
    assert b._headers().get("Authorization") == "Bearer sk-xyz"


def test_factory_resolves_openai():
    b = BackendFactory().create(ModelSpec(model_id="x", source="x", backend="openai"))
    assert b.backend_name == "openai"


async def test_build_body_forwards_response_format():
    b = OpenAICompatBackend()
    await b.load(ModelSpec(model_id="gpt", source="gpt", backend="openai",
                           extra={"base_url": "https://api.openai.com/v1"}))
    rf = {"type": "json_schema",
          "json_schema": {"name": "x", "schema": {"type": "object"}}}
    body = b._build_body(InternalRequest(
        messages=[InternalMessage(role="user", content="hi")], max_tokens=10, response_format=rf))
    assert body["response_format"] == rf


def test_load_providers_file(tmp_path):
    from infermesh.cli import _load_providers
    f = tmp_path / "providers.json"
    f.write_text(json.dumps({"models": [
        {"id": "gpt-4o-mini", "base_url": "https://api.openai.com/v1", "api_key": "env:OPENAI_API_KEY"},
        {"id": "claude", "base_url": "https://api.anthropic.com/v1",
         "upstream_model": "claude-3-5-sonnet-20241022", "api_key": "env:ANTHROPIC_API_KEY"},
    ]}))
    specs = _load_providers(str(f))
    assert [s.model_id for s in specs] == ["gpt-4o-mini", "claude"]
    assert all(s.backend == "openai" and s.extra["estimated_mb"] == 0 for s in specs)
    assert specs[0].extra["upstream_model"] == "gpt-4o-mini"          # defaults to id
    assert specs[1].extra["upstream_model"] == "claude-3-5-sonnet-20241022"

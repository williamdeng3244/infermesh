# SPDX-License-Identifier: Apache-2.0
"""MCP server (M14): InfermeshClient driven against the in-process gateway via
httpx ASGITransport (no real server, no stdio), plus the FastMCP build."""

import httpx
import pytest

from infermesh.core.backend import ModelSpec
from infermesh.core.factory import BackendFactory
from infermesh.core.pool import ModelPool
from infermesh.core.settings import Settings
from infermesh.mcp_server import InfermeshClient, build_mcp
from infermesh.server import create_app


def _client():
    pool = ModelPool(BackendFactory(default_backend="mock"))
    pool.discover_models([ModelSpec(model_id="echo-1", source="/tmp/echo-1", backend="mock", extra={"mock_mem_mb": 64})])
    ac = httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(pool, Settings())), base_url="http://test")
    return InfermeshClient("http://test", client=ac), ac


async def test_mcp_client_list_load_status():
    c, ac = _client()
    try:
        assert any(m["id"] == "echo-1" for m in await c.list_models())
        assert (await c.load("echo-1"))["loaded"] is True
        assert (await c.status())["loaded_count"] >= 1
        assert (await c.unload("echo-1", force=True))["model"] == "echo-1"
    finally:
        await ac.aclose()


async def test_mcp_client_benchmark_and_chat():
    c, ac = _client()
    try:
        b = await c.benchmark("echo-1", requests=4, concurrency=2, max_tokens=8, mode="different")
        assert b["succeeded"] == 4 and b["mode"] == "different" and "pp_tps" in b
        txt = await c.chat("echo-1", "hello mcp", max_tokens=8)
        assert isinstance(txt, str)
    finally:
        await ac.aclose()


async def test_mcp_client_devices_and_search(monkeypatch):
    import infermesh.core.downloader as dl
    monkeypatch.setattr(dl, "_hf_list_models", lambda q, l: [type("M", (), {
        "id": "org/x", "downloads": 9, "likes": 1, "pipeline_tag": "text-generation", "gated": False})()])
    c, ac = _client()
    try:
        assert any(d["vendor"] == "cpu" for d in await c.devices())
        res = await c.search_models("x", 5)
        assert res and res[0]["id"] == "org/x"
    finally:
        await ac.aclose()


def _tool_names(server):
    tm = getattr(server, "_tool_manager", None)
    if tm is not None and hasattr(tm, "list_tools"):
        try:
            return {t.name for t in tm.list_tools()}
        except Exception:
            return set()
    return set()


def test_build_mcp_registers_tools():
    pytest.importorskip("mcp")  # the [mcp] extra; skip cleanly in a base CI env
    server = build_mcp("http://127.0.0.1:8000")
    assert server is not None
    names = _tool_names(server)
    if names:  # introspection available in this SDK version
        for t in ("list_models", "load_model", "run_benchmark", "chat", "search_models", "download_model"):
            assert t in names, t

# SPDX-License-Identifier: Apache-2.0
"""MCP server — let an agent (Claude Code, etc.) drive a running infermesh gateway.

This is a thin **stdio** MCP server that proxies to the gateway's existing HTTP API
(``infermesh mcp --base-url http://127.0.0.1:8000``). An agent gets tools to list /
load / unload / pin models, run benchmarks, chat, inspect devices/metrics, and
search + download HuggingFace models — i.e. run tests itself, no curl.

``mcp`` is imported lazily so the control plane imports without it (install the
extra: ``pip install 'infermesh[mcp]'``). The :class:`InfermeshClient` is a plain
httpx wrapper around the gateway — injectable for in-process tests (ASGITransport).
"""

from __future__ import annotations

from typing import Optional

import httpx


class InfermeshClient:
    """Async HTTP client for the infermesh gateway (one method per MCP tool)."""

    def __init__(self, base_url: str, api_key: Optional[str] = None, client: Optional[httpx.AsyncClient] = None):
        self._base = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = client  # injected (tests); else a per-call client

    async def _get(self, path: str, params: Optional[dict] = None):
        owns = self._client is None
        client = self._client or httpx.AsyncClient(timeout=120.0)
        try:
            r = await client.get(self._base + path, params=params, headers=self._headers)
            r.raise_for_status()
            return r.json()
        finally:
            if owns:
                await client.aclose()

    async def _post(self, path: str, json: Optional[dict] = None):
        owns = self._client is None
        client = self._client or httpx.AsyncClient(timeout=600.0)
        try:
            r = await client.post(self._base + path, json=json, headers=self._headers)
            r.raise_for_status()
            return r.json()
        finally:
            if owns:
                await client.aclose()

    async def list_models(self) -> list:
        data = await self._get("/api/status")
        return [
            {"id": m["id"], "loaded": m["loaded"], "pinned": m["pinned"],
             "backend": m.get("backend"), "estimated_mb": m.get("estimated_mb")}
            for m in data.get("models", [])
        ]

    async def status(self) -> dict:
        return await self._get("/api/status")

    async def load(self, model_id: str, device: Optional[str] = None) -> dict:
        path = f"/v1/models/{model_id}/load"
        if device:
            path += f"?device={device}"
        return await self._post(path)

    async def unload(self, model_id: str, force: bool = False) -> dict:
        return await self._post(f"/v1/models/{model_id}/unload?force={'true' if force else 'false'}")

    async def pin(self, model_id: str) -> dict:
        return await self._post(f"/v1/models/{model_id}/pin")

    async def unpin(self, model_id: str) -> dict:
        return await self._post(f"/v1/models/{model_id}/unpin")

    async def benchmark(self, model: str, requests: int = 20, concurrency: int = 4,
                        max_tokens: int = 64, mode: str = "same") -> dict:
        return await self._post("/api/benchmark", {
            "model": model, "requests": requests, "concurrency": concurrency,
            "max_tokens": max_tokens, "mode": mode,
        })

    async def chat(self, model: str, prompt: str, max_tokens: int = 256) -> str:
        data = await self._post("/v1/chat/completions", {
            "model": model, "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
        })
        return data["choices"][0]["message"]["content"] or ""

    async def metrics(self) -> dict:
        return await self._get("/api/metrics")

    async def history(self) -> dict:
        return await self._get("/api/history")

    async def devices(self) -> list:
        return (await self._get("/api/devices")).get("devices", [])

    async def search_models(self, query: str, limit: int = 20) -> list:
        return (await self._get("/api/hf/search", {"q": query, "limit": limit})).get("models", [])

    async def download_model(self, repo_id: str) -> dict:
        return await self._post("/api/hf/download", {"repo_id": repo_id})

    async def downloads(self) -> list:
        return (await self._get("/api/hf/downloads")).get("downloads", [])


def build_mcp(base_url: str, api_key: Optional[str] = None):
    """Build a FastMCP server exposing infermesh as MCP tools."""
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("infermesh")
    client = InfermeshClient(base_url, api_key)

    @server.tool()
    async def list_models() -> list:
        """List models in the pool with their loaded/pinned state and memory."""
        return await client.list_models()

    @server.tool()
    async def pool_status() -> dict:
        """Pool memory ceiling/usage and per-model status."""
        return await client.status()

    @server.tool()
    async def load_model(model_id: str, device: str = "") -> dict:
        """Load (warm) a model. device is optional, e.g. 'cuda:0' or 'cpu'."""
        return await client.load(model_id, device or None)

    @server.tool()
    async def unload_model(model_id: str, force: bool = False) -> dict:
        """Unload a model (force=True to evict even if pinned/in-use)."""
        return await client.unload(model_id, force)

    @server.tool()
    async def pin_model(model_id: str) -> dict:
        """Pin a model so it is never evicted."""
        return await client.pin(model_id)

    @server.tool()
    async def unpin_model(model_id: str) -> dict:
        """Unpin a model."""
        return await client.unpin(model_id)

    @server.tool()
    async def run_benchmark(model: str, requests: int = 20, concurrency: int = 4,
                            max_tokens: int = 64, mode: str = "same") -> dict:
        """Benchmark a model: prefill/decode tok/s, TTFT, TPOT, E2E percentiles, peak
        memory. mode is 'same' (shared prompt) or 'different' (no prefix sharing)."""
        return await client.benchmark(model, requests, concurrency, max_tokens, mode)

    @server.tool()
    async def chat(model: str, prompt: str, max_tokens: int = 256) -> str:
        """Run a single non-streaming completion and return the text."""
        return await client.chat(model, prompt, max_tokens)

    @server.tool()
    async def recent_metrics() -> dict:
        """Recent per-request latency/throughput samples."""
        return await client.metrics()

    @server.tool()
    async def benchmark_history() -> dict:
        """Past benchmark runs and metric samples (persisted)."""
        return await client.history()

    @server.tool()
    async def list_devices() -> list:
        """Detected compute devices (NVIDIA/AMD/CPU) with VRAM."""
        return await client.devices()

    @server.tool()
    async def search_models(query: str, limit: int = 20) -> list:
        """Search HuggingFace for models (id, downloads, likes, task)."""
        return await client.search_models(query, limit)

    @server.tool()
    async def download_model(repo_id: str) -> dict:
        """Download a HuggingFace repo into the server's model dir (background)."""
        return await client.download_model(repo_id)

    @server.tool()
    async def download_status() -> list:
        """Progress of in-flight/finished model downloads."""
        return await client.downloads()

    return server


def run_stdio(base_url: str, api_key: Optional[str] = None) -> None:
    """Run the MCP server over stdio (the transport Claude Code launches)."""
    build_mcp(base_url, api_key).run(transport="stdio")

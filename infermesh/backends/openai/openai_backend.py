# SPDX-License-Identifier: Apache-2.0
"""OpenAICompatBackend — proxy to any OpenAI-compatible chat/embeddings API.

Instead of running a model locally, this backend forwards an ``InternalRequest``
to a remote provider's HTTP API (OpenAI, Anthropic's OpenAI-compatible endpoint,
OpenRouter, Together, a local vLLM server, …). It lets hosted models live in the
same pool / dashboard / OpenAI+Anthropic gateway as local vLLM models.

Config via ``ModelSpec.extra``:
  * ``base_url``        e.g. "https://api.openai.com/v1" (default) or
                        "https://api.anthropic.com/v1" or a local server.
  * ``api_key``         literal, or "env:OPENAI_API_KEY" to read from the
                        environment (so keys never live in code/config files).
  * ``upstream_model``  the provider's model id (defaults to ``model_id``).
Set ``extra["estimated_mb"]: 0`` — a remote model uses no local VRAM, so it never
counts against the pool's memory ceiling or triggers eviction of local models.

No vendor SDK: just ``httpx`` (a control-plane dependency).
"""

from __future__ import annotations

import json
import os
from typing import AsyncIterator, Optional

import httpx

from infermesh.api.adapters.base import InternalRequest, StreamChunk
from infermesh.core.backend import (
    BackendCaps,
    EngineStats,
    HardwareInfo,
    HealthStatus,
    InferenceBackend,
    ModelSpec,
)


def _resolve_key(value: Optional[str]) -> Optional[str]:
    """Resolve an api_key spec: ``env:VAR`` -> os.environ[VAR]; else literal."""
    if not value:
        return None
    if value.startswith("env:"):
        return os.environ.get(value[4:])
    return value


class OpenAICompatBackend(InferenceBackend):
    """Forward chat/embeddings to a remote OpenAI-compatible endpoint."""

    def __init__(self) -> None:
        self._spec: Optional[ModelSpec] = None
        self._loaded: bool = False
        self._base_url: Optional[str] = None
        self._key: Optional[str] = None
        self._upstream: Optional[str] = None

    @property
    def backend_name(self) -> str:
        return "openai"

    def capabilities(self) -> BackendCaps:
        return BackendCaps(streaming=True, tool_calling=True, embeddings=True)

    def hardware(self) -> HardwareInfo:
        return HardwareInfo(vendor="remote", detail={"base_url": self._base_url})

    async def load(self, spec: ModelSpec) -> None:
        self._spec = spec
        self._base_url = str(spec.extra.get("base_url") or "https://api.openai.com/v1").rstrip("/")
        self._key = _resolve_key(spec.extra.get("api_key"))
        self._upstream = spec.extra.get("upstream_model") or spec.model_id
        self._loaded = True

    async def unload(self) -> None:
        self._loaded = False

    def _headers(self) -> dict:
        headers = {"content-type": "application/json"}
        if self._key:
            headers["Authorization"] = f"Bearer {self._key}"
        return headers

    async def health(self) -> HealthStatus:
        if not self._loaded or not self._base_url:
            return HealthStatus(healthy=False, detail="not loaded")
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(f"{self._base_url}/models", headers=self._headers())
            # <500 means we reached the provider (401/404 still implies reachable)
            return HealthStatus(resp.status_code < 500, detail=f"http {resp.status_code}")
        except httpx.HTTPError as exc:
            return HealthStatus(healthy=False, detail=str(exc))

    def _build_body(self, req: InternalRequest) -> dict:
        body: dict = {
            "model": self._upstream,
            "messages": [{"role": m.role, "content": m.content} for m in req.messages],
            "max_tokens": req.max_tokens,
            "temperature": req.temperature,
            "top_p": req.top_p,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if req.stop:
            body["stop"] = req.stop
        if req.tools:
            body["tools"] = req.tools
        if req.tool_choice:
            body["tool_choice"] = req.tool_choice
        if req.response_format:
            body["response_format"] = req.response_format
        return body

    async def chat_stream(self, req: InternalRequest) -> AsyncIterator[StreamChunk]:
        if not self._loaded or not self._base_url:
            raise RuntimeError("OpenAICompatBackend.chat_stream() called before load()")
        body = self._build_body(req)
        first = True
        finish_reason: Optional[str] = None
        prompt_tokens = completion_tokens = 0
        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream(
                "POST", f"{self._base_url}/chat/completions", json=body, headers=self._headers()
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    payload = line[len("data:"):].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        obj = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    usage = obj.get("usage")
                    if usage:
                        prompt_tokens = usage.get("prompt_tokens", prompt_tokens)
                        completion_tokens = usage.get("completion_tokens", completion_tokens)
                    choices = obj.get("choices") or []
                    if not choices:
                        continue
                    choice = choices[0]
                    delta = choice.get("delta") or {}
                    if choice.get("finish_reason"):
                        finish_reason = choice["finish_reason"]
                    text = delta.get("content") or ""
                    reasoning = delta.get("reasoning_content")
                    tool_calls = delta.get("tool_calls")
                    if text or reasoning or tool_calls:
                        yield StreamChunk(
                            text=text, reasoning_content=reasoning, tool_call_delta=tool_calls,
                            is_first=first, is_last=False,
                        )
                        first = False
        yield StreamChunk(
            text="", is_first=first, is_last=True, finish_reason=finish_reason or "stop",
            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not self._loaded or not self._base_url:
            raise RuntimeError("OpenAICompatBackend.embed() called before load()")
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self._base_url}/embeddings",
                json={"model": self._upstream, "input": texts},
                headers=self._headers(),
            )
            resp.raise_for_status()
            payload = resp.json()
        items = sorted(payload.get("data", []), key=lambda d: d.get("index", 0))
        return [list(item["embedding"]) for item in items]

    def stats(self) -> EngineStats:
        return EngineStats(
            model_id=self._spec.model_id if self._spec else "",
            loaded=self._loaded,
            used_mem_mb=0,  # remote — no local VRAM
            extra={"base_url": self._base_url, "upstream_model": self._upstream, "remote": True},
        )

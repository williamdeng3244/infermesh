# SPDX-License-Identifier: Apache-2.0
"""The hardware/engine-agnostic inference backend interface.

This is the single seam between the control plane and any compute engine. It
generalizes oMLX's in-process ``engine/base.py:BaseEngine`` to also cover
out-of-process backends (vLLM/SGLang sidecars, remote workers).

Critically, it consumes/produces the SAME internal types as the lifted adapter
layer (:class:`~infermesh.api.adapters.base.InternalRequest`,
:class:`~infermesh.api.adapters.base.InternalResponse`,
:class:`~infermesh.api.adapters.base.StreamChunk`) so the API gateway and the
engine speak one language. The only types crossing the api <-> backend boundary
are those three.

One backend instance == one loaded model (mirrors oMLX's per-model engine and
vLLM's one-model-per-process model). The pool holds many instances.

ZERO vendor imports live here, by rule. All hardware-specific code lives under
``infermesh.backends.<name>`` behind this interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

from infermesh.api.adapters.base import (
    InternalRequest,
    InternalResponse,
    StreamChunk,
)


@dataclass
class ModelSpec:
    """A model the platform can serve. Backend-neutral."""

    model_id: str                      # canonical id (usually the directory name)
    source: str                        # local path OR hugging-face repo id
    model_type: str = "llm"            # llm | vlm | embedding | reranker
    revision: Optional[str] = None
    quantization: Optional[str] = None
    max_context: Optional[int] = None
    alias: Optional[str] = None        # optional API-visible name
    backend: Optional[str] = None      # force a backend; None => factory default
    extra: dict = field(default_factory=dict)  # backend-specific knobs


@dataclass
class BackendCaps:
    """What a backend can do — lets the pool/router reason about a model."""

    streaming: bool = True
    embeddings: bool = False
    rerank: bool = False
    vision: bool = False
    tool_calling: bool = False
    tensor_parallel: bool = False
    tiered_kv: bool = False


@dataclass
class HardwareInfo:
    """What the backend is running on."""

    vendor: str = "unknown"            # nvidia | amd | cpu | apple | custom
    device_count: int = 0
    mem_per_device_mb: int = 0
    detail: dict = field(default_factory=dict)


@dataclass
class EngineStats:
    """Point-in-time backend telemetry. Feeds /api/status (and later a dashboard)."""

    model_id: str
    loaded: bool = False
    prompt_tps: float = 0.0
    generation_tps: float = 0.0
    queue_depth: int = 0
    active_requests: int = 0
    used_mem_mb: int = 0
    kv_cache_hit_rate: float = 0.0
    extra: dict = field(default_factory=dict)


@dataclass
class HealthStatus:
    healthy: bool
    detail: str = ""


class InferenceBackend(ABC):
    """Hardware/engine-agnostic inference backend.

    A backend instance serves exactly ONE model. It may be backed by:
      - an in-process library (llama.cpp, MLX),
      - a local sidecar server (vLLM, SGLang) spawned by ``load()``,
      - a remote worker reached over HTTP/gRPC.
    The control plane talks ONLY to this interface and never imports a vendor SDK.
    """

    # ---- identity & capability (let the pool/router reason about this model) ----
    @property
    @abstractmethod
    def backend_name(self) -> str:
        ...

    @abstractmethod
    def capabilities(self) -> BackendCaps:
        ...

    @abstractmethod
    def hardware(self) -> HardwareInfo:
        ...

    # ---- lifecycle (load brings the one model online; may spawn a process) ----
    @abstractmethod
    async def load(self, spec: ModelSpec) -> None:
        ...

    @abstractmethod
    async def unload(self) -> None:
        ...

    @abstractmethod
    async def health(self) -> HealthStatus:
        ...

    # ---- inference (streaming-first; consume InternalRequest, yield StreamChunk) ----
    @abstractmethod
    async def chat_stream(self, req: InternalRequest) -> AsyncIterator[StreamChunk]:
        ...

    async def chat(self, req: InternalRequest) -> InternalResponse:
        """Default non-streaming impl: aggregate the stream.

        Override if the backend has a native non-streaming path.
        """
        text: list[str] = []
        reasoning: list[str] = []
        pt = ct = cached = 0
        finish: Optional[str] = None
        tool_calls = None
        async for ch in self.chat_stream(req):
            text.append(ch.text)
            if ch.reasoning_content:
                reasoning.append(ch.reasoning_content)
            if ch.finish_reason:
                finish = ch.finish_reason
            pt = ch.prompt_tokens or pt
            ct = ch.completion_tokens or ct
            cached = ch.cached_tokens or cached
        return InternalResponse(
            text="".join(text),
            reasoning_content="".join(reasoning) or None,
            finish_reason=finish or "stop",
            prompt_tokens=pt,
            completion_tokens=ct,
            cached_tokens=cached,
            tool_calls=tool_calls,
            model=req.model,
        )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    async def rerank(self, query: str, docs: list[str]) -> list[float]:
        raise NotImplementedError

    # ---- observability (feeds /api/status and, later, the dashboard) ----
    @abstractmethod
    def stats(self) -> EngineStats:
        ...

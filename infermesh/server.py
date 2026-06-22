# SPDX-License-Identifier: Apache-2.0
"""FastAPI gateway — wires the lifted OpenAI/Anthropic adapters to the ModelPool.

Data flow for a chat request (S7.4)::

    HTTP JSON (OpenAI or Anthropic)
      -> {OpenAI,Anthropic}Adapter.parse_request()  -> InternalRequest
      -> pool.acquire(model)                         -> InferenceBackend (leased)
      -> backend.chat_stream(InternalRequest)        -> async StreamChunk
      -> adapter.format_stream_chunk / format_response
      -> SSE or JSON

The only types crossing api <-> backend are InternalRequest / InternalResponse /
StreamChunk. This module imports no vendor SDK.

Streaming note: the in-use lease is taken manually and released inside the
generator's ``finally`` — NOT via ``async with acquire()`` — because the
StreamingResponse body runs *after* the route returns, so a context manager
would release the lease before the stream is consumed.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import struct
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import asdict
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from infermesh import __version__
from infermesh.api.adapters import AnthropicAdapter, OpenAIAdapter
from infermesh.api.anthropic_models import MessagesRequest
from infermesh.api.embedding_models import (
    EmbeddingData,
    EmbeddingRequest,
    EmbeddingResponse,
    EmbeddingUsage,
)
from infermesh.api.openai_models import ChatCompletionRequest
from infermesh.api.rerank_models import (
    RerankRequest,
    RerankResponse,
    RerankResult,
    RerankUsage,
)
from infermesh.core.pool import (
    InsufficientMemoryError,
    ModelNotFoundError,
    ModelPool,
    ModelTooLargeError,
    PoolError,
)
from infermesh.core.settings import Settings
from infermesh.core.scheduler import AdmissionController, Overloaded
from infermesh.core.model_settings import ModelSettingsStore, SAMPLING_FIELDS
from infermesh.core.devices import enumerate_devices
from infermesh.core.stats import StatsAccumulator
from infermesh.core.history import (
    append_benchmark,
    append_metric,
    load_benchmarks,
    load_metrics,
    truncate_on_startup,
)
from infermesh.dashboard import DASHBOARD_HTML

logger = logging.getLogger("infermesh.server")


def _encode_embedding(vec: list[float], fmt: str):
    """OpenAI embeddings encoding: raw float list, or base64 of little-endian f32."""
    if fmt == "base64":
        return base64.b64encode(struct.pack(f"<{len(vec)}f", *vec)).decode("ascii")
    return vec


# Recent-logs ring buffer feeding the dashboard's Logs view.
_LOG_BUFFER: deque = deque(maxlen=500)


class _RingBufferLogHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self._fmt = logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S"
        )

    def emit(self, record: logging.LogRecord) -> None:
        try:
            _LOG_BUFFER.append({"level": record.levelname, "line": self._fmt.format(record)})
        except Exception:  # noqa: BLE001 - logging must never raise
            pass


def _install_log_capture() -> None:
    """Capture infermesh.* logs (pool, server, backends) into the ring buffer."""
    lg = logging.getLogger("infermesh")
    if lg.level == logging.NOTSET or lg.level > logging.INFO:
        lg.setLevel(logging.INFO)
    if not any(isinstance(h, _RingBufferLogHandler) for h in lg.handlers):
        lg.addHandler(_RingBufferLogHandler())


class SettingsPatch(BaseModel):
    """Runtime-editable settings (host/port/model-dir require a restart)."""

    idle_timeout: Optional[float] = None
    api_key: Optional[str] = None  # "" clears (auth off); null = leave unchanged
    max_concurrent_requests: Optional[int] = None  # admission cap (live)
    max_queued_requests: Optional[int] = None      # admission queue bound (0 => unbounded)
    kv_hot_capacity: Optional[int] = None
    kv_cold_dir: Optional[str] = None
    hf_endpoint: Optional[str] = None
    gen_temperature: Optional[float] = None  # null in body clears the default; absent leaves it unchanged
    gen_top_p: Optional[float] = None
    gen_top_k: Optional[int] = None
    gen_max_tokens: Optional[int] = None
    host: Optional[str] = None              # startup-only (saved now, applied on restart)
    port: Optional[int] = None
    model_dir: Optional[str] = None
    backend: Optional[str] = None
    max_process_memory: Optional[str] = None


class ModelSettingsPatch(BaseModel):
    """Per-model generation overrides; a null field clears that override."""

    model: str
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    max_tokens: Optional[int] = None
    max_context_window: Optional[int] = None


class BenchmarkRequest(BaseModel):
    """Config for POST /api/benchmark (bounded server-side)."""

    model: str
    requests: int = 20
    concurrency: int = 4
    max_tokens: int = 64
    prompt: str = "Write one concise sentence about distributed systems."
    mode: str = "same"  # "same" (shared prompt, prefix-cacheable) | "different"


class HFDownloadRequest(BaseModel):
    """Config for POST /api/hf/download."""

    repo_id: str
    source: str = "hf"   # "hf" (HuggingFace) | "modelscope"


# Rolling per-request metrics for the dashboard's latency/throughput charts.
_METRICS: deque = deque(maxlen=300)
# Aggregate request stats (session + persisted all-time), oMLX-style.
_STATS = StatsAccumulator()
_MODEL_SETTINGS = ModelSettingsStore()


def _record_metric(model: Optional[str], latency_ms: float, completion_tokens: int,
                   prompt_tokens: int = 0, cached_tokens: int = 0,
                   ttft_ms: Optional[float] = None) -> None:
    tokens = int(completion_tokens or 0)
    tps = (tokens / (latency_ms / 1000.0)) if latency_ms > 0 and tokens else 0.0
    record = {
        "t": time.time(),
        "model": model or "",
        "latency_ms": round(latency_ms, 1),
        "tokens": tokens,
        "tps": round(tps, 1),
    }
    _METRICS.append(record)
    append_metric(record)
    # Aggregate: prefill time ~= TTFT; the rest is generation.
    prefill_s = (ttft_ms / 1000.0) if ttft_ms else 0.0
    generation_s = max(0.0, (latency_ms - (ttft_ms or 0.0)) / 1000.0)
    _STATS.record(model=model or "", prompt_tokens=prompt_tokens, completion_tokens=tokens,
                  cached_tokens=cached_tokens, prefill_s=prefill_s, generation_s=generation_s)


def _kv_defaults(settings: Settings) -> dict:
    """Global Transformers tiered-KV defaults applied (under per-model extra) at load."""
    if settings.kv_hot_capacity and settings.kv_hot_capacity > 0:
        extra = {"prefix_kv": int(settings.kv_hot_capacity)}
        if settings.kv_cold_dir:
            extra["kv_cold_dir"] = settings.kv_cold_dir
        return extra
    return {}


def _apply_gen_defaults(request, settings: Settings):
    """Fill omitted sampling params on a chat request from server-side generation
    defaults. A value the client explicitly sent always wins; an unset default
    (None) leaves the field for the adapter's built-in fallback."""
    for attr, val in (("temperature", settings.gen_temperature), ("top_p", settings.gen_top_p),
                      ("top_k", settings.gen_top_k), ("max_tokens", settings.gen_max_tokens)):
        if val is not None and getattr(request, attr, None) is None:
            setattr(request, attr, val)
    return request


def _apply_model_overrides(request, model_id: str, store: ModelSettingsStore) -> dict:
    """Fill omitted sampling params from a model's per-model overrides (which win
    over the global defaults but still yield to an explicit request value).
    Returns the override dict so the caller can read ``max_context_window``."""
    ov = store.get(model_id)
    for attr in SAMPLING_FIELDS:
        val = ov.get(attr)
        if val is not None and getattr(request, attr, None) is None:
            setattr(request, attr, val)
    return ov


def _approx_prompt_tokens(request) -> int:
    """Tokenizer-free estimate (~4 chars/token) of a chat request's prompt size,
    summed over message text. Backs the approximate ``max_context_window`` guard
    -- the control plane has no tokenizer, so this is deliberately a soft bound."""
    chars = 0
    for msg in (getattr(request, "messages", None) or []):
        content = getattr(msg, "content", None)
        if isinstance(content, str):
            chars += len(content)
        elif isinstance(content, list):
            for part in content:
                text = getattr(part, "text", None)
                if text is None and isinstance(part, dict):
                    text = part.get("text")
                if text:
                    chars += len(text)
    return chars // 4


def create_app(pool: ModelPool, settings: Optional[Settings] = None) -> FastAPI:
    """Build the FastAPI app around a (pre-populated) ModelPool."""
    settings = settings or Settings()
    _install_log_capture()
    openai_adapter = OpenAIAdapter()
    anthropic_adapter = AnthropicAdapter()

    async def _ttl_loop() -> None:
        interval = max(1.0, float(settings.ttl_check_interval))
        while True:
            await asyncio.sleep(interval)
            # live-checked so PUT /api/settings {idle_timeout} takes effect at runtime
            if not (settings.idle_timeout and settings.idle_timeout > 0):
                continue
            try:
                await pool.check_ttl_expirations(settings.idle_timeout)
            except Exception as exc:  # noqa: BLE001
                logger.error("TTL check failed: %s", exc)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup: reload persisted metrics, warm pinned models, start TTL reaper.
        truncate_on_startup()
        for sample in load_metrics(_METRICS.maxlen or 300):
            _METRICS.append(sample)
        try:
            await pool.preload_pinned_models()
        except Exception as exc:  # noqa: BLE001
            logger.error("preload_pinned_models failed: %s", exc)
        ttl_task = asyncio.create_task(_ttl_loop())
        try:
            yield
        finally:
            ttl_task.cancel()
            await pool.shutdown()

    app = FastAPI(title="infermesh", version=__version__, lifespan=lifespan)
    app.state.pool = pool
    app.state.settings = settings
    gate = AdmissionController(cap=settings.max_concurrent_requests,
                               max_queue=getattr(settings, "max_queued_requests", 0) or None)
    app.state.gate = gate
    pool.default_extra = _kv_defaults(settings)
    from infermesh.core import downloader as _downloader
    _downloader.set_endpoint(settings.hf_endpoint)

    # ------------------------------ auth ------------------------------- #
    async def require_auth(
        authorization: Optional[str] = Header(default=None),
        x_api_key: Optional[str] = Header(default=None),
    ) -> None:
        if not settings.api_key:
            return  # auth disabled
        token: Optional[str] = None
        if authorization and authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
        elif x_api_key:
            token = x_api_key.strip()
        if token != settings.api_key:
            raise HTTPException(status_code=401, detail="invalid or missing API key")

    # --------------------------- chat handler -------------------------- #
    async def _handle_chat(request, adapter):
        model_id = pool.resolve_model_id(request.model)
        ov = _apply_model_overrides(request, model_id, _MODEL_SETTINGS)  # per-model overrides win over globals
        _apply_gen_defaults(request, settings)                          # globals fill whatever is still omitted
        mcw = ov.get("max_context_window")
        if mcw and _approx_prompt_tokens(request) > int(mcw):
            _STATS.record_rejection("context_too_long")
            return JSONResponse(
                adapter.create_error_response(
                    f"prompt is approximately too long for max_context_window={mcw}",
                    "context_too_long", 400),
                status_code=400,
            )
        internal = adapter.parse_request(request)

        try:
            await gate.acquire()  # control-plane concurrency cap (held until the response completes)
        except Overloaded as exc:
            _STATS.record_rejection("overloaded")
            return JSONResponse(
                adapter.create_error_response(str(exc), "overloaded", 503),
                status_code=503,
            )

        if internal.stream:
            try:
                backend = await pool.get_engine(model_id, _lease=True)
            except ModelNotFoundError as exc:
                await gate.release()
                _STATS.record_rejection("model_not_found")
                return JSONResponse(
                    adapter.create_error_response(str(exc), "model_not_found", 404),
                    status_code=404,
                )
            except (ModelTooLargeError, InsufficientMemoryError) as exc:
                await gate.release()
                _STATS.record_rejection("insufficient_memory")
                return JSONResponse(
                    adapter.create_error_response(str(exc), "insufficient_memory", 503),
                    status_code=503,
                )

            start = time.monotonic()
            keepalive = max(0.0, float(getattr(settings, "sse_keepalive_interval", 0.0)))

            async def event_stream():
                # Produce formatted SSE chunks on a background task and drain them
                # with a timeout, so a slow first token (long prefill on a big model)
                # emits ': keep-alive' comments instead of letting the client read-time-out.
                completion = 0
                prompt_toks = 0
                cached_toks = 0
                ttft_ms = None
                queue: asyncio.Queue = asyncio.Queue()
                _DONE = object()

                async def produce():
                    nonlocal completion, prompt_toks, cached_toks, ttft_ms
                    try:
                        async for chunk in backend.chat_stream(internal):
                            if ttft_ms is None and (chunk.text or chunk.reasoning_content):
                                ttft_ms = (time.monotonic() - start) * 1000.0
                            if chunk.completion_tokens:
                                completion = chunk.completion_tokens
                            if chunk.prompt_tokens:
                                prompt_toks = chunk.prompt_tokens
                            if chunk.cached_tokens:
                                cached_toks = chunk.cached_tokens
                            await queue.put(adapter.format_stream_chunk(chunk, request))
                        tail = adapter.format_stream_end(request)
                        if tail:
                            await queue.put(tail)
                    except Exception as exc:  # surface to consumer, then close cleanly
                        await queue.put(exc)
                    finally:
                        await queue.put(_DONE)

                task = asyncio.ensure_future(produce())
                try:
                    while True:
                        if keepalive > 0:
                            try:
                                item = await asyncio.wait_for(queue.get(), timeout=keepalive)
                            except asyncio.TimeoutError:
                                yield ": keep-alive\n\n"  # SSE comment line; ignored by clients
                                continue
                        else:
                            item = await queue.get()
                        if item is _DONE:
                            break
                        if isinstance(item, Exception):
                            logger.warning("streaming generation error: %s", item)
                            break
                        yield item
                finally:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
                    await pool.release_engine(model_id)
                    await gate.release()
                    _record_metric(request.model, (time.monotonic() - start) * 1000.0, completion,
                                   prompt_tokens=prompt_toks, cached_tokens=cached_toks, ttft_ms=ttft_ms)

            return StreamingResponse(event_stream(), media_type="text/event-stream")

        # Non-streaming
        try:
            start = time.monotonic()
            try:
                async with pool.acquire(model_id) as backend:
                    response = await backend.chat(internal)
            except ModelNotFoundError as exc:
                _STATS.record_rejection("model_not_found")
                return JSONResponse(
                    adapter.create_error_response(str(exc), "model_not_found", 404),
                    status_code=404,
                )
            except (ModelTooLargeError, InsufficientMemoryError) as exc:
                _STATS.record_rejection("insufficient_memory")
                return JSONResponse(
                    adapter.create_error_response(str(exc), "insufficient_memory", 503),
                    status_code=503,
                )
            except PoolError as exc:
                _STATS.record_rejection("server_error")
                return JSONResponse(
                    adapter.create_error_response(str(exc), "server_error", 500),
                    status_code=500,
                )

            _record_metric(request.model, (time.monotonic() - start) * 1000.0, response.completion_tokens,
                           prompt_tokens=response.prompt_tokens, cached_tokens=response.cached_tokens)
            formatted = adapter.format_response(response, request)
            if hasattr(formatted, "model_dump"):
                return JSONResponse(formatted.model_dump(exclude_none=True))
            return JSONResponse(formatted)
        finally:
            await gate.release()

    # ------------------------------ routes ----------------------------- #
    @app.post("/v1/chat/completions")
    async def chat_completions(request: ChatCompletionRequest, _: None = Depends(require_auth)):
        return await _handle_chat(request, openai_adapter)

    @app.post("/v1/messages")
    async def anthropic_messages(request: MessagesRequest, _: None = Depends(require_auth)):
        return await _handle_chat(request, anthropic_adapter)

    @app.post("/v1/embeddings")
    async def embeddings(request: EmbeddingRequest, _: None = Depends(require_auth)):
        if request.items is not None:
            texts = [(item.text or "") for item in request.items]
        elif isinstance(request.input, str):
            texts = [request.input]
        else:
            texts = list(request.input or [])
        model_id = pool.resolve_model_id(request.model)
        try:
            async with pool.acquire(model_id) as backend:
                vectors = await backend.embed(texts)
        except ModelNotFoundError as exc:
            return JSONResponse(openai_adapter.create_error_response(str(exc), "model_not_found", 404), status_code=404)
        except NotImplementedError:
            return JSONResponse(openai_adapter.create_error_response(
                f"backend for '{model_id}' does not support embeddings", "unsupported", 501), status_code=501)
        except (ModelTooLargeError, InsufficientMemoryError) as exc:
            return JSONResponse(openai_adapter.create_error_response(str(exc), "insufficient_memory", 503), status_code=503)
        if request.dimensions:
            vectors = [v[: request.dimensions] for v in vectors]
        data = [
            EmbeddingData(index=i, embedding=_encode_embedding(v, request.encoding_format))
            for i, v in enumerate(vectors)
        ]
        tokens = sum(len(t.split()) for t in texts)
        resp = EmbeddingResponse(
            data=data, model=request.model,
            usage=EmbeddingUsage(prompt_tokens=tokens, total_tokens=tokens),
        )
        return JSONResponse(resp.model_dump())

    @app.post("/v1/rerank")
    async def rerank(request: RerankRequest, _: None = Depends(require_auth)):
        query = request.query if isinstance(request.query, str) else (request.query.get("text") or "")
        docs = [d if isinstance(d, str) else (d.get("text") or "") for d in request.documents]
        model_id = pool.resolve_model_id(request.model)
        try:
            async with pool.acquire(model_id) as backend:
                scores = await backend.rerank(query, docs)
        except ModelNotFoundError as exc:
            return JSONResponse(openai_adapter.create_error_response(str(exc), "model_not_found", 404), status_code=404)
        except NotImplementedError:
            return JSONResponse(openai_adapter.create_error_response(
                f"backend for '{model_id}' does not support rerank", "unsupported", 501), status_code=501)
        except (ModelTooLargeError, InsufficientMemoryError) as exc:
            return JSONResponse(openai_adapter.create_error_response(str(exc), "insufficient_memory", 503), status_code=503)
        results = sorted(
            (
                RerankResult(
                    index=i,
                    relevance_score=float(score),
                    document=(
                        ({"text": request.documents[i]} if isinstance(request.documents[i], str)
                         else request.documents[i]) if request.return_documents else None
                    ),
                )
                for i, score in enumerate(scores)
            ),
            key=lambda r: r.relevance_score,
            reverse=True,
        )
        if request.top_n is not None:
            results = results[: request.top_n]
        tokens = len(query.split()) + sum(len(d.split()) for d in docs)
        resp = RerankResponse(
            results=results, model=request.model, usage=RerankUsage(total_tokens=tokens),
        )
        return JSONResponse(resp.model_dump())

    @app.get("/v1/models")
    async def list_models(_: None = Depends(require_auth)):
        created = int(time.time())
        return {
            "object": "list",
            "data": [
                {"id": mid, "object": "model", "created": created, "owned_by": "infermesh"}
                for mid in pool.get_model_ids()
            ],
        }

    @app.get("/v1/models/status")
    async def models_status(_: None = Depends(require_auth)):
        return pool.get_status()

    @app.post("/v1/models/{model_id:path}/load")
    async def load_model(
        model_id: str,
        device: Optional[str] = Query(default=None),
        _: None = Depends(require_auth),
    ):
        mid = pool.resolve_model_id(model_id)
        if device:
            pool.set_device(mid, device)
        try:
            async with pool.acquire(mid):
                pass  # acquire warms (loads) the model; release on block exit
        except ModelNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except PoolError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        return {
            "status": "loaded",
            "model": mid,
            "loaded": mid in pool.get_loaded_model_ids(),
        }

    @app.post("/v1/models/{model_id:path}/unload")
    async def unload_model(
        model_id: str,
        force: bool = Query(default=False),
        _: None = Depends(require_auth),
    ):
        mid = pool.resolve_model_id(model_id)
        if pool.get_entry(mid) is None:
            raise HTTPException(status_code=404, detail=f"model '{model_id}' not found")
        unloaded = await pool.unload_if_idle_unpinned(mid, force=force)
        return {
            "status": "unloaded" if unloaded else "kept",
            "model": mid,
            "loaded": mid in pool.get_loaded_model_ids(),
        }

    @app.post("/v1/models/{model_id:path}/pin")
    async def pin_model(model_id: str, _: None = Depends(require_auth)):
        mid = pool.resolve_model_id(model_id)
        if not pool.set_pinned(mid, True):
            raise HTTPException(status_code=404, detail=f"model '{model_id}' not found")
        return {"model": mid, "pinned": True}

    @app.post("/v1/models/{model_id:path}/unpin")
    async def unpin_model(model_id: str, _: None = Depends(require_auth)):
        mid = pool.resolve_model_id(model_id)
        if not pool.set_pinned(mid, False):
            raise HTTPException(status_code=404, detail=f"model '{model_id}' not found")
        return {"model": mid, "pinned": False}

    @app.get("/", include_in_schema=False)
    @app.get("/admin", include_in_schema=False)
    async def admin_dashboard():
        return HTMLResponse(DASHBOARD_HTML)

    @app.get("/health")
    async def health():
        return {"status": "ok", "version": __version__, "loaded_models": pool.get_loaded_model_ids()}

    @app.get("/api/status")
    async def api_status(_: None = Depends(require_auth)):
        return dict(pool.get_status(), admission=gate.snapshot())

    @app.get("/api/logs")
    async def api_logs(
        limit: int = Query(default=200, ge=1, le=500),
        _: None = Depends(require_auth),
    ):
        return {"lines": list(_LOG_BUFFER)[-limit:]}

    @app.get("/api/metrics")
    async def api_metrics(_: None = Depends(require_auth)):
        return {"samples": list(_METRICS)}

    @app.get("/api/devices")
    async def api_devices(_: None = Depends(require_auth)):
        return {"devices": enumerate_devices()}

    @app.get("/api/stats")
    async def api_stats(scope: str = Query(default="session"), model: str = Query(default=""),
                        _: None = Depends(require_auth)):
        return _STATS.snapshot("alltime" if scope == "alltime" else "session", model=model)

    @app.post("/api/stats/clear")
    async def api_stats_clear(scope: str = Query(default="session"), _: None = Depends(require_auth)):
        target = "alltime" if scope == "alltime" else "session"
        _STATS.clear(target)
        return {"cleared": target}

    @app.get("/api/stats/models")
    async def api_stats_models(scope: str = Query(default="session"), _: None = Depends(require_auth)):
        sc = "alltime" if scope == "alltime" else "session"
        models = _STATS.snapshot(sc).get("models", [])
        return {"scope": sc, "models": [{"model": m, **_STATS.snapshot(sc, model=m)} for m in models]}

    @app.get("/api/history")
    async def api_history(_: None = Depends(require_auth)):
        return {"benchmarks": load_benchmarks(), "metrics": load_metrics()}

    def _register_downloaded() -> None:
        """Add freshly-downloaded models to the pool (so they appear without a restart)."""
        from infermesh.core import downloader
        from infermesh.core.backend import ModelSpec
        if not settings.model_dir:
            return
        for job in downloader.completed_jobs():
            mid = job.get("model_id")
            if mid and pool.get_entry(mid) is None:
                pool.add_spec(ModelSpec(model_id=mid, source=job["path"], backend=settings.backend))

    @app.get("/api/hf/search")
    async def api_hf_search(
        q: str = Query(default=""),
        limit: int = Query(default=20, ge=1, le=50),
        sort: str = Query(default="downloads"),
        task: str = Query(default=""),
        _: None = Depends(require_auth),
    ):
        from infermesh.core import downloader
        if sort not in ("downloads", "likes", "trending_score", "lastModified"):
            sort = "downloads"
        try:
            models = await asyncio.to_thread(downloader.search_models, q, limit, sort, task or None)
        except RuntimeError as exc:  # huggingface_hub not installed
            raise HTTPException(status_code=501, detail=str(exc))
        except Exception as exc:  # bad sort/task/query or network — surface, don't 500
            raise HTTPException(status_code=502, detail=str(exc)[:200])
        return {"models": models, "sort": sort, "task": task or None}

    @app.post("/api/hf/download")
    async def api_hf_download(req: HFDownloadRequest, _: None = Depends(require_auth)):
        from infermesh.core import downloader
        if not settings.model_dir:
            raise HTTPException(status_code=400, detail="downloads need a --model-dir; none is configured")
        try:
            src = req.source if req.source in ("hf", "modelscope") else "hf"
            return downloader.start_download(req.repo_id, settings.model_dir, source=src)
        except RuntimeError as exc:
            raise HTTPException(status_code=501, detail=str(exc))

    @app.get("/api/hf/downloads")
    async def api_hf_downloads(_: None = Depends(require_auth)):
        from infermesh.core import downloader
        _register_downloaded()
        return {"downloads": downloader.downloads_status(), "model_dir": settings.model_dir}

    @app.post("/api/benchmark")
    async def api_benchmark(req: BenchmarkRequest, _: None = Depends(require_auth)):
        from infermesh.core.benchmark import run_benchmark
        model_id = pool.resolve_model_id(req.model)
        if pool.get_entry(model_id) is None:
            return JSONResponse(
                openai_adapter.create_error_response(f"model '{req.model}' not found", "model_not_found", 404),
                status_code=404,
            )
        n = max(1, min(req.requests, 200))
        c = max(1, min(req.concurrency, 32))
        mt = max(1, min(req.max_tokens, 1024))
        try:
            result = await run_benchmark(pool, model_id, requests=n, concurrency=c,
                                         max_tokens=mt, prompt=req.prompt, mode=req.mode)
        except (ModelTooLargeError, InsufficientMemoryError) as exc:
            return JSONResponse(
                openai_adapter.create_error_response(str(exc), "insufficient_memory", 503),
                status_code=503,
            )
        append_benchmark({
            "t": time.time(), "model": model_id,
            "params": {"requests": n, "concurrency": c, "max_tokens": mt},
            "result": result,
        })
        return result

    @app.get("/api/settings")
    async def api_get_settings(_: None = Depends(require_auth)):
        data = asdict(settings)
        data["api_key"] = bool(settings.api_key)  # redact: only expose whether set
        return data

    @app.put("/api/settings")
    async def api_put_settings(patch: SettingsPatch, _: None = Depends(require_auth)):
        changed = []
        if patch.idle_timeout is not None:
            settings.idle_timeout = max(0.0, float(patch.idle_timeout))
            changed.append("idle_timeout")
        if patch.api_key is not None:
            settings.api_key = patch.api_key or None
            changed.append("api_key")
        if patch.max_concurrent_requests is not None:
            settings.max_concurrent_requests = max(1, int(patch.max_concurrent_requests))
            gate.configure(cap=settings.max_concurrent_requests)   # live
            changed.append("max_concurrent_requests")
        if patch.max_queued_requests is not None:
            settings.max_queued_requests = max(0, int(patch.max_queued_requests))
            gate.configure(max_queue=settings.max_queued_requests)  # live
            changed.append("max_queued_requests")
        if patch.kv_hot_capacity is not None:
            settings.kv_hot_capacity = max(0, int(patch.kv_hot_capacity))
            changed.append("kv_hot_capacity")
        if patch.kv_cold_dir is not None:
            settings.kv_cold_dir = patch.kv_cold_dir or None
            changed.append("kv_cold_dir")
        if patch.hf_endpoint is not None:
            settings.hf_endpoint = patch.hf_endpoint or None
            changed.append("hf_endpoint")
            from infermesh.core import downloader as _downloader
            _downloader.set_endpoint(settings.hf_endpoint)
        fset = patch.model_fields_set  # explicit null clears a default; absent key leaves it unchanged
        if "gen_temperature" in fset:
            settings.gen_temperature = None if patch.gen_temperature is None else max(0.0, min(2.0, float(patch.gen_temperature)))
            changed.append("gen_temperature")
        if "gen_top_p" in fset:
            settings.gen_top_p = None if patch.gen_top_p is None else max(0.0, min(1.0, float(patch.gen_top_p)))
            changed.append("gen_top_p")
        if "gen_top_k" in fset:
            settings.gen_top_k = None if patch.gen_top_k is None else max(0, int(patch.gen_top_k))
            changed.append("gen_top_k")
        if "gen_max_tokens" in fset:
            settings.gen_max_tokens = None if patch.gen_max_tokens is None else max(1, int(patch.gen_max_tokens))
            changed.append("gen_max_tokens")
        if patch.host is not None:
            new = patch.host.strip() or settings.host
            if new != settings.host:
                settings.host = new; changed.append("host")
        if patch.port is not None:
            new = max(1, min(65535, int(patch.port)))
            if new != settings.port:
                settings.port = new; changed.append("port")
        if patch.model_dir is not None:
            new = patch.model_dir.strip() or None
            if new != settings.model_dir:
                settings.model_dir = new; changed.append("model_dir")
        if patch.backend is not None:
            new = patch.backend.strip() or settings.backend
            if new != settings.backend:
                settings.backend = new; changed.append("backend")
        if patch.max_process_memory is not None:
            new = patch.max_process_memory.strip() or settings.max_process_memory
            if new != settings.max_process_memory:
                settings.max_process_memory = new; changed.append("max_process_memory")
        if "kv_hot_capacity" in changed or "kv_cold_dir" in changed:
            pool.default_extra = _kv_defaults(settings)
        if changed:
            try:
                settings.save()
            except OSError as exc:
                logger.error("settings save failed: %s", exc)
        data = asdict(settings)
        data["api_key"] = bool(settings.api_key)
        restart_fields = {"host", "port", "model_dir", "backend", "max_process_memory"}
        return {"updated": changed, "settings": data,
                "restart_required": [c for c in changed if c in restart_fields]}

    @app.post("/api/restart")
    async def api_restart(_: None = Depends(require_auth)):
        """Re-exec the serve process so it reloads settings.json (keeps the PID)."""
        import os as _os
        from infermesh import cli as _cli
        _cli.restart_in_place()
        return {"restarting": True, "pid": _os.getpid()}

    @app.get("/api/model-settings")
    async def api_model_settings(_: None = Depends(require_auth)):
        return {"settings": _MODEL_SETTINGS.all()}

    @app.put("/api/model-settings")
    async def api_put_model_settings(patch: ModelSettingsPatch, _: None = Depends(require_auth)):
        fset = patch.model_fields_set
        fields: dict = {}
        if "temperature" in fset:
            fields["temperature"] = None if patch.temperature is None else max(0.0, min(2.0, float(patch.temperature)))
        if "top_p" in fset:
            fields["top_p"] = None if patch.top_p is None else max(0.0, min(1.0, float(patch.top_p)))
        if "top_k" in fset:
            fields["top_k"] = None if patch.top_k is None else max(0, int(patch.top_k))
        if "max_tokens" in fset:
            fields["max_tokens"] = None if patch.max_tokens is None else max(1, int(patch.max_tokens))
        if "max_context_window" in fset:
            fields["max_context_window"] = None if patch.max_context_window is None else max(1, int(patch.max_context_window))
        cur = _MODEL_SETTINGS.set(patch.model, **fields)
        return {"model": patch.model, "settings": cur}

    return app

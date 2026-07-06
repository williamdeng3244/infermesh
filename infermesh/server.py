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
import uuid
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
from infermesh.core.bench_jobs import BenchJobManager
from infermesh.core.model_settings import ModelSettingsStore, SAMPLING_FIELDS
from infermesh.core.devices import detect_interconnect, enumerate_devices
from infermesh.core.stats import StatsAccumulator
from infermesh.core.history import (
    append_benchmark,
    append_metric,
    load_benchmarks,
    load_metrics,
    truncate_on_startup,
)
from infermesh.core.backend import UnsupportedModelError
from infermesh.core import community as _community
from infermesh.core import specs as _specs
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
    slo_p99_ttft_s: Optional[float] = None         # capacity SLO for read-side goodput (live)
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
    submitter_label: Optional[str] = None   # community display name ("" clears => hostname)
    auto_publish: Optional[bool] = None      # auto-submit benchmarks to the shared library
    hub_url: Optional[str] = None            # remote community hub ("" => store locally / be the hub)


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
    device: Optional[str] = None  # run on a specific accelerator (e.g. "gcu:0", "cpu"); None = current
    share: Optional[bool] = True  # publish this run to the shared community library (per-run opt-out)
    # multi-device (jobs only): devices=["gcu:0","gcu:1"] without tp => one
    # sub-run per card (data parallel); with parallelism={"tp": n} => one run
    # over the whole group (backend maps tp, e.g. vLLM tensor_parallel_size)
    devices: Optional[list] = None
    parallelism: Optional[dict] = None
    # concurrency sweep (jobs only, mode="concurrency_sweep"): in-flight levels
    # and the per-level measurement window
    levels: Optional[list] = None
    window_s: Optional[float] = None


class SpecsPutRequest(BaseModel):
    """Body for PUT /api/specs — replaces the user chip-spec override file."""

    specs: dict


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


def _sysinfo() -> dict:
    """Software + hardware snapshot for benchmark records (OS, Python, infermesh
    version, CPU, RAM, accelerators). Vendor-free — enumerate_devices is CLI-based."""
    import os as _os
    import platform as _pf
    gpus = []
    try:
        from infermesh.core.devices import enumerate_devices
        gpus = [{"name": d.get("name"), "vendor": d.get("vendor"), "mem_total_mb": d.get("mem_total_mb")}
                for d in enumerate_devices() if d.get("vendor") != "cpu"]
    except Exception:
        pass
    ram_gb = None
    try:
        ram_gb = round(_os.sysconf("SC_PAGE_SIZE") * _os.sysconf("SC_PHYS_PAGES") / (1024 ** 3), 1)
    except Exception:
        pass
    return {
        "os": _pf.platform(),
        "python": _pf.python_version(),
        "infermesh": __version__,
        "hostname": _pf.node(),
        "cpu": _pf.processor() or _pf.machine(),
        "cpu_cores": _os.cpu_count(),
        "ram_gb": ram_gb,
        "gpus": gpus,
    }


def _detect_quant(pool: "ModelPool", model_id: str) -> Optional[str]:
    """Best-effort quantization label for the community store (metadata only).

    Reads the model's local ``config.json`` (``quantization_config.bits`` or
    ``torch_dtype``) when the source is a directory. Control-plane pure — only
    reads JSON, never imports torch. Returns None if it can't tell; the caller
    then defaults by device (CPU => fp32, accelerator => fp16)."""
    import json as _json
    import os as _os
    try:
        entry = pool.get_entry(model_id)
        src = getattr(getattr(entry, "spec", None), "source", None)
        if src and _os.path.isdir(str(src)):
            cfg_path = _os.path.join(str(src), "config.json")
            if _os.path.exists(cfg_path):
                with open(cfg_path) as fh:
                    cfg = _json.load(fh)
                bits = (cfg.get("quantization_config") or {}).get("bits")
                if bits:
                    return f"{int(bits)}bit"
                td = str(cfg.get("torch_dtype") or "").lower()
                if "bfloat16" in td:
                    return "bf16"
                if "float16" in td:
                    return "fp16"
                if "float32" in td:
                    return "fp32"
    except Exception:
        pass
    return None


def _community_record(result: dict, params: dict, sysinfo: dict,
                      submitter: str, quant: str, backend: Optional[str],
                      run_id: Optional[str] = None) -> dict:
    """Map an infermesh benchmark result into a flat community-store row."""
    import uuid as _uuid
    vendor = result.get("vendor")
    accel_gb = None
    gpu_name = None
    for g in (sysinfo.get("gpus") or []):
        if g.get("vendor") == vendor:
            if g.get("mem_total_mb"):
                accel_gb = round(g["mem_total_mb"] / 1024, 1)
            gpu_name = g.get("name") or gpu_name
            break
    # resolve a clean chip name: explicit device_name > the matching GPU's name in
    # sysinfo > the bare vendor (keeps old records that predate device_name capture
    # from splitting "Enflame S60" and "enflame" into two chips)
    chip = result.get("device_name") or gpu_name or (vendor if vendor and vendor != "cpu" else "CPU")
    succ = max(1, int(result.get("succeeded") or 1))
    ctx = round((result.get("total_prompt_tokens") or 0) / succ) or None
    peak_gb = round(result["peak_mem_mb"] / 1024, 2) if result.get("peak_mem_mb") else None
    wall = result.get("wall_time_s") or 0
    tput = None
    if wall > 0:
        tput = round(((result.get("total_output_tokens") or 0) +
                      (result.get("total_prompt_tokens") or 0)) / wall, 1)
    e2e = (result.get("latency_ms") or {}).get("p50")
    group = run_id or _uuid.uuid4().hex[:12]
    return {
        "submitter": submitter, "submission_group": group, "run_id": group,
        "chip": chip,
        "vendor": vendor, "accel_mem_gb": accel_gb, "cores": None,
        "infermesh_version": sysinfo.get("infermesh"), "os": sysinfo.get("os"), "backend": backend,
        "model": result.get("model"), "quant": quant,
        "context_length": ctx, "batch_size": params.get("concurrency"),
        "pp_tps": (result.get("pp_tps") or {}).get("mean"),
        "tg_tps": (result.get("tg_tps") or {}).get("mean"),
        "ttft_ms": (result.get("ttft_ms") or {}).get("p50"),
        "tpot_ms": (result.get("tpot_ms") or {}).get("mean"),
        "peak_mem_gb": peak_gb,
        "power_avg_w": result.get("power_avg_w"),
        "energy_j": result.get("energy_j"),
        "n_requests": result.get("succeeded"),
        "e2e_latency_s": round(e2e / 1000, 3) if e2e else None,
        "total_throughput": tput,
    }


async def _publish_to_hub(hub_url: str, rec: dict) -> None:
    """POST one record to a remote community hub (when this node isn't the hub)."""
    import json as _json
    import urllib.request as _ur

    def _post():
        url = hub_url.rstrip("/") + "/api/community/submit"
        body = _json.dumps(rec).encode()
        req = _ur.Request(url, data=body, method="POST",
                          headers={"Content-Type": "application/json"})
        _ur.urlopen(req, timeout=10).read()

    await asyncio.to_thread(_post)


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
    bench_jobs = BenchJobManager()
    app.state.bench_jobs = bench_jobs
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
        limit: int = Query(default=200, ge=1, le=2000),
        level: str = Query(default=""),
        _: None = Depends(require_auth),
    ):
        lines = list(_LOG_BUFFER)
        total = len(lines)
        if level:  # min-level view filter (does not affect the saved log file)
            rank = {"debug": 0, "info": 1, "warning": 2, "error": 3}
            minr = rank.get(level.lower(), 0)
            lines = [ln for ln in lines if rank.get(str(ln.get("level", "")).lower(), 1) >= minr]
        return {"lines": lines[-limit:], "total": total}

    @app.get("/api/metrics")
    async def api_metrics(_: None = Depends(require_auth)):
        return {"samples": list(_METRICS)}

    @app.get("/api/devices")
    async def api_devices(_: None = Depends(require_auth)):
        return {"devices": enumerate_devices()}

    @app.get("/api/sysinfo")
    async def api_sysinfo(_: None = Depends(require_auth)):
        return _sysinfo()

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

    # -------------------- shared community benchmark library -------------------- #
    @app.get("/api/community/runs")
    async def api_community_runs(
        chip: str = Query(default=""), vendor: str = Query(default=""),
        model: str = Query(default=""), quant: str = Query(default=""),
        context: Optional[int] = Query(default=None), min_pp: Optional[float] = Query(default=None),
        min_tg: Optional[float] = Query(default=None), submitter: str = Query(default=""),
        sort: str = Query(default="recent"), limit: int = Query(default=500, ge=1, le=5000),
        _: None = Depends(require_auth),
    ):
        runs = await asyncio.to_thread(
            lambda: _community.query_runs(chip=chip, vendor=vendor, model=model, quant=quant,
                                          context=context, min_pp=min_pp, min_tg=min_tg,
                                          submitter=submitter, sort=sort, limit=limit))
        facets = await asyncio.to_thread(_community.facets)
        return {"runs": runs, "facets": facets}

    @app.get("/api/community/compare")
    async def api_community_compare(metric: str = Query(default="pp_tps"),
                                    series: str = Query(default="[]"),
                                    _: None = Depends(require_auth)):
        import json as _json
        try:
            sel = _json.loads(series)
            if not isinstance(sel, list):
                sel = []
        except (ValueError, TypeError):
            sel = []
        return await asyncio.to_thread(_community.compare, metric, sel)

    @app.get("/api/community/run/{run_id}")
    async def api_community_run(run_id: str, _: None = Depends(require_auth)):
        rec = await asyncio.to_thread(_community.get, run_id)
        if not rec:
            raise HTTPException(status_code=404, detail="run not found")
        return rec

    @app.post("/api/community/submit")
    async def api_community_submit(payload: dict, _: None = Depends(require_auth)):
        recs = payload.get("runs") if "runs" in payload else payload
        if isinstance(recs, list):
            return await asyncio.to_thread(_community.submit_many, recs)
        return await asyncio.to_thread(_community.submit, recs if isinstance(recs, dict) else payload)

    @app.get("/api/community/export.csv")
    async def api_community_export(
        chip: str = Query(default=""), vendor: str = Query(default=""),
        model: str = Query(default=""), quant: str = Query(default=""),
        context: Optional[int] = Query(default=None), min_pp: Optional[float] = Query(default=None),
        min_tg: Optional[float] = Query(default=None), sort: str = Query(default="recent"),
        _: None = Depends(require_auth),
    ):
        import csv
        import io
        runs = await asyncio.to_thread(
            lambda: _community.query_runs(chip=chip, vendor=vendor, model=model, quant=quant,
                                          context=context, min_pp=min_pp, min_tg=min_tg,
                                          sort=sort, limit=5000))
        cols = ["created_at", "submitter", "chip", "vendor", "model", "quant", "context_length",
                "batch_size", "pp_tps", "tg_tps", "ttft_ms", "tpot_ms", "peak_mem_gb",
                "e2e_latency_s", "total_throughput", "backend", "os", "infermesh_version", "id"]
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(cols)
        for r in runs:
            w.writerow([r.get(c) for c in cols])
        return StreamingResponse(io.BytesIO(buf.getvalue().encode()), media_type="text/csv",
                                 headers={"Content-Disposition": "attachment; filename=infermesh-community.csv"})

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
            raise HTTPException(status_code=502, detail=(
                "search failed — is HuggingFace reachable? Set a mirror endpoint in "
                "Settings (e.g. https://hf-mirror.com). " + str(exc)[:120]))
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

    @app.post("/api/hf/download/pause")
    async def api_hf_download_pause(req: HFDownloadRequest, _: None = Depends(require_auth)):
        from infermesh.core import downloader
        return await asyncio.to_thread(downloader.pause_download, req.repo_id)

    @app.post("/api/hf/download/delete")
    async def api_hf_download_delete(req: HFDownloadRequest, _: None = Depends(require_auth)):
        from infermesh.core import downloader
        res = await asyncio.to_thread(downloader.delete_download, req.repo_id)
        mid = req.repo_id.split("/")[-1]   # model_id == repo basename
        if not res.get("files_removed") and settings.model_dir:  # on-disk model with no tracked job
            import os as _os
            import shutil as _shutil
            p = _os.path.join(_os.path.expanduser(settings.model_dir), mid)
            if _os.path.isdir(p):
                try:
                    await asyncio.to_thread(_shutil.rmtree, p)
                    res["files_removed"] = True
                    res["path"] = p
                except OSError as exc:
                    logger.warning("delete of '%s' failed: %s", p, exc)
        try:  # also drop it from the pool so a deleted model doesn't linger in Models
            await pool.unload_if_idle_unpinned(mid, force=True)
            pool.remove_spec(mid)
        except Exception as exc:  # pool cleanup is best-effort
            logger.warning("pool cleanup after delete failed: %s", exc)
        return res

    async def _record_benchmark(result: dict, *, concurrency: int, params: dict,
                                share: Optional[bool], model_id: str,
                                extras: Optional[dict] = None) -> str:
        """Persist one finished benchmark to history (+ community library when
        enabled). ``extras`` adds schema-v2 fields (device_count, parallelism,
        interconnect, …) onto the community row. Returns the shared run id."""
        run_id = uuid.uuid4().hex[:12]
        sysinfo = _sysinfo()
        append_benchmark({
            "t": time.time(), "model": model_id, "run_id": run_id,
            "params": params,
            "result": result,
            "system": sysinfo,
        })
        # auto-publish to the shared community library (per-run opt-out via share)
        if settings.auto_publish and share is not False:
            try:
                submitter = settings.submitter_label or sysinfo.get("hostname") or "anonymous"
                quant = _detect_quant(pool, model_id) or ("fp32" if result.get("vendor") == "cpu" else "fp16")
                bk = getattr(getattr(pool.get_entry(model_id), "spec", None), "backend", None) or settings.backend
                rec = _community_record(result, {"concurrency": concurrency}, sysinfo,
                                        submitter, quant, bk, run_id=run_id)
                if extras:
                    rec.update({k: v for k, v in extras.items() if v is not None})
                if settings.hub_url:
                    await _publish_to_hub(settings.hub_url, rec)
                else:
                    await asyncio.to_thread(_community.submit, rec)
            except Exception as exc:  # publishing must never fail the benchmark
                logger.warning("community auto-publish failed: %s", exc)
        return run_id

    @app.post("/api/benchmark", deprecated=True)
    async def api_benchmark(req: BenchmarkRequest, _: None = Depends(require_auth)):
        """Synchronous benchmark (deprecated — use POST /api/bench/jobs, which
        runs in the background and respects admission control)."""
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
        if req.device:  # pin the model to the chosen accelerator, reloading it there
            pool.set_device(model_id, req.device)
            await pool.unload_if_idle_unpinned(model_id, force=True)
        try:
            async with pool.acquire(model_id):  # load once up front so an unsupported
                pass                              # model (embedding/encoder) fails fast & clean here, not as silent per-request failures
            _bench = run_benchmark(pool, model_id, requests=n, concurrency=c,
                                   max_tokens=mt, prompt=req.prompt, mode=req.mode)
            # a device-pinned run reloads the model there; some accelerators (e.g. a CPU
            # fallback on a torch_gcu box) can hang on load — bound it instead of hanging.
            result = await (asyncio.wait_for(_bench, timeout=240) if req.device else _bench)
        except asyncio.TimeoutError:
            return JSONResponse(openai_adapter.create_error_response(
                f"benchmark on device '{req.device}' timed out — that accelerator may be "
                f"unavailable in this environment", "device_timeout", 503), status_code=503)
        except UnsupportedModelError as exc:
            return JSONResponse(openai_adapter.create_error_response(
                str(exc), "unsupported_model", 422), status_code=422)
        except (ModelTooLargeError, InsufficientMemoryError) as exc:
            return JSONResponse(
                openai_adapter.create_error_response(str(exc), "insufficient_memory", 503),
                status_code=503,
            )
        await _record_benchmark(result, concurrency=c,
                                params={"requests": n, "concurrency": c, "max_tokens": mt,
                                        "mode": req.mode, "device": req.device},
                                share=req.share, model_id=model_id)
        return result

    # ------------- background benchmark jobs (admission-gated) ------------- #
    async def _bench_once(job, *, device: Optional[str], progress_base: int,
                          force_reload: bool) -> dict:
        """One pinned-and-loaded benchmark pass with progress/cancel wiring."""
        from infermesh.core.benchmark import run_benchmark
        spec = job.spec
        model_id = spec["model_id"]
        if device:
            pool.set_device(model_id, device)
        if device or force_reload:
            await pool.unload_if_idle_unpinned(model_id, force=True)
        job.progress["phase"] = "load"
        async with pool.acquire(model_id):  # load up front: unsupported models fail fast
            pass
        job.progress["phase"] = "running"

        def _prog(done_n: int, total: int) -> None:
            job.progress["current"] = progress_base + done_n

        bench = run_benchmark(pool, model_id,
                              requests=spec["requests"], concurrency=spec["concurrency"],
                              max_tokens=spec["max_tokens"], prompt=spec["prompt"],
                              mode=spec["mode"], should_stop=job.cancel_event.is_set,
                              on_progress=_prog)
        # pinned/reloaded runs get the same load-hang bound as the sync endpoint
        if device or force_reload:
            return await asyncio.wait_for(bench, timeout=240)
        return await bench

    async def _run_bench_job(job) -> tuple:
        """Dispatch: sweep vs data parallel (devices, no tp) vs single/tp."""
        spec = job.spec
        if (spec.get("mode") or "") == "concurrency_sweep":
            return await _run_sweep_bench_job(job)
        devices = [str(d) for d in (spec.get("devices") or [])][:8]
        try:
            tp = int((spec.get("parallelism") or {}).get("tp") or 0)
        except (TypeError, ValueError):
            tp = 0
        if len(devices) >= 2 and tp < 2:
            return await _run_dp_bench_job(job, devices)
        return await _run_single_bench_job(job, devices=devices, tp=tp)

    async def _run_sweep_bench_job(job) -> tuple:
        """Concurrency sweep: sequential levels; every level records as a
        child run (batch_size = level), the parent frontier lands in history
        and in the job result. Goodput is NOT stored — /api/analysis computes
        it against the current slo_p99_ttft_s setting."""
        from infermesh.core.sweep import DEFAULT_LEVELS, run_concurrency_sweep
        spec = job.spec
        model_id = spec["model_id"]
        device = spec.get("device") or ((spec.get("devices") or [None])[0])
        if device:
            pool.set_device(model_id, device)
            await pool.unload_if_idle_unpinned(model_id, force=True)
        job.progress["phase"] = "load"
        async with pool.acquire(model_id):
            pass
        if job.cancel_event.is_set():
            return None, []
        levels = spec.get("levels") or list(DEFAULT_LEVELS)
        window = float(spec.get("window_s") or 30.0)
        job.progress.update({"current": 0, "total": len(levels), "phase": "running"})

        def _lvl(done_n: int, total: int) -> None:
            job.progress["current"] = done_n
            job.progress["total"] = total

        parent = await run_concurrency_sweep(
            pool, model_id, levels=levels, window_s=window,
            max_tokens=spec["max_tokens"], prompt=spec["prompt"],
            should_stop=job.cancel_event.is_set, on_level=_lvl)
        if job.cancel_event.is_set():
            return parent, []  # cancelled: keep partial numbers, record nothing
        run_ids: list[str] = []
        for child in parent["children"]:
            extras = {"percentiles": child.get("percentiles"),
                      "cv_itl": child.get("cv_itl"),
                      "n_requests": child.get("n_requests"),
                      "device_count": 1}
            rid = await _record_benchmark(
                child, concurrency=child["concurrency"],
                params={"mode": "concurrency_sweep", "level": child["concurrency"],
                        "window_s": window, "max_tokens": spec["max_tokens"],
                        "device": device},
                share=spec.get("share"), model_id=model_id, extras=extras)
            run_ids.append(rid)
        # the parent frontier is a history-level artifact, not a community row
        parent_id = uuid.uuid4().hex[:12]
        append_benchmark({"t": time.time(), "model": model_id, "run_id": parent_id,
                          "params": {"mode": "concurrency_sweep", "levels": levels,
                                     "window_s": window, "device": device},
                          "result": {k: v for k, v in parent.items() if k != "children"},
                          "system": _sysinfo()})
        parent["run_id"] = parent_id
        parent["child_run_ids"] = run_ids
        return parent, run_ids

    async def _run_single_bench_job(job, *, devices: list, tp: int) -> tuple:
        """Single device or tensor-parallel group: exactly one run, one record.
        (The manager already holds this job's admission slot.)"""
        spec = job.spec
        model_id = spec["model_id"]
        device = spec.get("device") or (devices[0] if devices and tp < 2 else None)
        force_reload = False
        if tp >= 2:
            # record the intent neutrally; the backend maps it at load time
            # (vLLM: tensor_parallel_size) — mapping code lives in backends/vllm
            entry = pool.get_entry(model_id)
            if entry is not None:
                extra = dict(entry.spec.extra or {})
                extra["parallelism"] = {"tp": tp}
                if devices:
                    extra["devices"] = list(devices)
                entry.spec.extra = extra
            force_reload = True
        result = await _bench_once(job, device=device, progress_base=0,
                                   force_reload=force_reload)
        if job.cancel_event.is_set():
            return result, []  # cancelled: keep partial numbers, record nothing
        device_count = max(tp, len(devices)) if tp >= 2 else 1
        parallelism = {"tp": tp} if tp >= 2 else None
        interconnect = None
        if device_count > 1:  # nvidia-smi topo (to_thread) or the specs registry
            interconnect = await asyncio.to_thread(
                detect_interconnect, result.get("vendor"), result.get("device_name"))
        extras = {"device_count": device_count, "parallelism": parallelism,
                  "interconnect": interconnect}
        result = dict(result, **extras)
        run_id = await _record_benchmark(
            result, concurrency=spec["concurrency"],
            params={**{k: spec[k] for k in ("requests", "concurrency", "max_tokens", "mode", "device")},
                    **({"devices": devices} if devices else {})},
            share=spec.get("share"), model_id=model_id, extras=extras)
        return result, [run_id]

    async def _run_dp_bench_job(job, devices: list) -> tuple:
        """Data parallel: one child run per card, each recorded separately and
        each holding its own admission slot while it runs. Sub-runs execute
        sequentially — the pool keeps one backend instance per model, so a
        card's numbers are never polluted by a concurrent sibling. (The
        manager was given gate=None for this job.)"""
        spec = job.spec
        model_id = spec["model_id"]
        per_dev = spec["requests"]
        job.progress.update({"current": 0, "total": per_dev * len(devices)})
        children: list[dict] = []
        run_ids: list[str] = []
        for idx, dev in enumerate(devices):
            if job.cancel_event.is_set():
                break
            job.progress["phase"] = f"waiting ({dev})"
            await bench_jobs.acquire_or_cancel(gate, job)  # one slot per card sub-run
            try:
                result = await _bench_once(job, device=dev, progress_base=idx * per_dev,
                                           force_reload=True)
            finally:
                await gate.release()
            if job.cancel_event.is_set():
                break
            extras = {"device_count": 1, "parallelism": {"dp": len(devices)},
                      "interconnect": None}
            result = dict(result, **extras)
            run_id = await _record_benchmark(
                result, concurrency=spec["concurrency"],
                params={**{k: spec[k] for k in ("requests", "concurrency", "max_tokens", "mode")},
                        "device": dev, **extras},
                share=spec.get("share"), model_id=model_id, extras=extras)
            children.append({"device": dev, "run_id": run_id, "result": result})
            run_ids.append(run_id)
        combined = round(sum((c["result"].get("output_tokens_per_sec") or 0.0)
                             for c in children), 1)
        summary = {"mode": "data_parallel", "devices": devices, "children": children,
                   "combined_output_tokens_per_sec": combined}
        return summary, run_ids

    @app.post("/api/bench/jobs", status_code=202)
    async def api_bench_job_create(req: BenchmarkRequest, _: None = Depends(require_auth)):
        """Start a benchmark as a background job. The job takes one admission
        slot while running, so benchmarks share the concurrency budget with
        live inference instead of stampeding it."""
        model_id = pool.resolve_model_id(req.model)
        if pool.get_entry(model_id) is None:
            return JSONResponse(
                openai_adapter.create_error_response(f"model '{req.model}' not found", "model_not_found", 404),
                status_code=404,
            )
        devices = [str(d) for d in (req.devices or [])][:8]
        try:
            tp = int((req.parallelism or {}).get("tp") or 0)
        except (TypeError, ValueError):
            tp = 0
        job = bench_jobs.create({
            "model": req.model, "model_id": model_id,
            "requests": max(1, min(req.requests, 200)),
            "concurrency": max(1, min(req.concurrency, 32)),
            "max_tokens": max(1, min(req.max_tokens, 1024)),
            "prompt": req.prompt, "mode": req.mode,
            "device": req.device, "share": req.share,
            "devices": devices or None,
            "parallelism": ({"tp": tp} if tp >= 2 else None),
            "levels": (lambda ls: ls or None)([
                max(1, min(int(x), 64)) for x in (req.levels or [])[:8]
                if isinstance(x, (int, float)) or (isinstance(x, str) and x.isdigit())
            ]),
            "window_s": (max(0.2, min(float(req.window_s), 120.0))
                         if req.window_s else None),
        })
        # Data-parallel jobs take one slot per card sub-run inside the runner,
        # so the manager must not also hold a job-wide slot for them.
        data_parallel = len(devices) >= 2 and tp < 2
        job.task = asyncio.create_task(
            bench_jobs.run(job, _run_bench_job, gate=None if data_parallel else gate))
        return {"job_id": job.job_id, "state": job.state}

    @app.get("/api/bench/jobs")
    async def api_bench_job_list(_: None = Depends(require_auth)):
        return {"jobs": bench_jobs.list()}

    @app.get("/api/bench/jobs/{job_id}")
    async def api_bench_job_get(job_id: str, _: None = Depends(require_auth)):
        job = bench_jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"unknown job '{job_id}'")
        return job.to_dict()

    @app.post("/api/bench/jobs/{job_id}/cancel")
    async def api_bench_job_cancel(job_id: str, _: None = Depends(require_auth)):
        job = bench_jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"unknown job '{job_id}'")
        accepted = bench_jobs.request_cancel(job_id)
        return {"ok": accepted, "state": job.state}

    # --------------------------- chip spec registry --------------------------- #
    @app.get("/api/specs")
    async def api_get_specs(_: None = Depends(require_auth)):
        data = await asyncio.to_thread(_specs.load)
        return {"specs": data, "user_path": str(_specs.user_path())}

    @app.put("/api/specs")
    async def api_put_specs(body: SpecsPutRequest, _: None = Depends(require_auth)):
        try:
            merged = await asyncio.to_thread(_specs.save_user, body.specs)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"specs": merged, "user_path": str(_specs.user_path())}

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
        if patch.slo_p99_ttft_s is not None:
            settings.slo_p99_ttft_s = max(0.01, float(patch.slo_p99_ttft_s))
            changed.append("slo_p99_ttft_s")
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
        if patch.submitter_label is not None:
            settings.submitter_label = patch.submitter_label.strip() or None
            changed.append("submitter_label")
        if patch.auto_publish is not None:
            settings.auto_publish = bool(patch.auto_publish)
            changed.append("auto_publish")
        if patch.hub_url is not None:
            settings.hub_url = patch.hub_url.strip() or None
            changed.append("hub_url")
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

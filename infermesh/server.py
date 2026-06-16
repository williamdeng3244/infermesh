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


# Rolling per-request metrics for the dashboard's latency/throughput charts.
_METRICS: deque = deque(maxlen=300)


def _record_metric(model: Optional[str], latency_ms: float, completion_tokens: int) -> None:
    tokens = int(completion_tokens or 0)
    tps = (tokens / (latency_ms / 1000.0)) if latency_ms > 0 and tokens else 0.0
    _METRICS.append({
        "t": time.time(),
        "model": model or "",
        "latency_ms": round(latency_ms, 1),
        "tokens": tokens,
        "tps": round(tps, 1),
    })


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
        # Startup: warm pinned models, start the (always-on) TTL reaper.
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
        internal = adapter.parse_request(request)
        model_id = pool.resolve_model_id(request.model)

        if internal.stream:
            try:
                backend = await pool.get_engine(model_id, _lease=True)
            except ModelNotFoundError as exc:
                return JSONResponse(
                    adapter.create_error_response(str(exc), "model_not_found", 404),
                    status_code=404,
                )
            except (ModelTooLargeError, InsufficientMemoryError) as exc:
                return JSONResponse(
                    adapter.create_error_response(str(exc), "insufficient_memory", 503),
                    status_code=503,
                )

            start = time.monotonic()

            async def event_stream():
                completion = 0
                try:
                    async for chunk in backend.chat_stream(internal):
                        if chunk.completion_tokens:
                            completion = chunk.completion_tokens
                        yield adapter.format_stream_chunk(chunk, request)
                    tail = adapter.format_stream_end(request)
                    if tail:
                        yield tail
                finally:
                    await pool.release_engine(model_id)
                    _record_metric(request.model, (time.monotonic() - start) * 1000.0, completion)

            return StreamingResponse(event_stream(), media_type="text/event-stream")

        # Non-streaming
        start = time.monotonic()
        try:
            async with pool.acquire(model_id) as backend:
                response = await backend.chat(internal)
        except ModelNotFoundError as exc:
            return JSONResponse(
                adapter.create_error_response(str(exc), "model_not_found", 404),
                status_code=404,
            )
        except (ModelTooLargeError, InsufficientMemoryError) as exc:
            return JSONResponse(
                adapter.create_error_response(str(exc), "insufficient_memory", 503),
                status_code=503,
            )
        except PoolError as exc:
            return JSONResponse(
                adapter.create_error_response(str(exc), "server_error", 500),
                status_code=500,
            )

        _record_metric(request.model, (time.monotonic() - start) * 1000.0, response.completion_tokens)
        formatted = adapter.format_response(response, request)
        if hasattr(formatted, "model_dump"):
            return JSONResponse(formatted.model_dump(exclude_none=True))
        return JSONResponse(formatted)

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
    async def load_model(model_id: str, _: None = Depends(require_auth)):
        mid = pool.resolve_model_id(model_id)
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
        return {"status": "ok", "loaded_models": pool.get_loaded_model_ids()}

    @app.get("/api/status")
    async def api_status(_: None = Depends(require_auth)):
        return pool.get_status()

    @app.get("/api/logs")
    async def api_logs(
        limit: int = Query(default=200, ge=1, le=500),
        _: None = Depends(require_auth),
    ):
        return {"lines": list(_LOG_BUFFER)[-limit:]}

    @app.get("/api/metrics")
    async def api_metrics(_: None = Depends(require_auth)):
        return {"samples": list(_METRICS)}

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
        if changed:
            try:
                settings.save()
            except OSError as exc:
                logger.error("settings save failed: %s", exc)
        data = asdict(settings)
        data["api_key"] = bool(settings.api_key)
        return {"updated": changed, "settings": data}

    return app

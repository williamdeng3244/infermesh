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
import logging
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse

from infermesh import __version__
from infermesh.api.adapters import AnthropicAdapter, OpenAIAdapter
from infermesh.api.anthropic_models import MessagesRequest
from infermesh.api.openai_models import ChatCompletionRequest
from infermesh.core.pool import (
    InsufficientMemoryError,
    ModelNotFoundError,
    ModelPool,
    ModelTooLargeError,
    PoolError,
)
from infermesh.core.settings import Settings

logger = logging.getLogger("infermesh.server")


def create_app(pool: ModelPool, settings: Optional[Settings] = None) -> FastAPI:
    """Build the FastAPI app around a (pre-populated) ModelPool."""
    settings = settings or Settings()
    openai_adapter = OpenAIAdapter()
    anthropic_adapter = AnthropicAdapter()

    async def _ttl_loop() -> None:
        interval = max(1.0, float(settings.ttl_check_interval))
        while True:
            await asyncio.sleep(interval)
            try:
                await pool.check_ttl_expirations(settings.idle_timeout)
            except Exception as exc:  # noqa: BLE001
                logger.error("TTL check failed: %s", exc)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup: warm pinned models, start the TTL reaper if enabled.
        ttl_task: Optional[asyncio.Task] = None
        try:
            await pool.preload_pinned_models()
        except Exception as exc:  # noqa: BLE001
            logger.error("preload_pinned_models failed: %s", exc)
        if settings.idle_timeout and settings.idle_timeout > 0:
            ttl_task = asyncio.create_task(_ttl_loop())
        try:
            yield
        finally:
            if ttl_task is not None:
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

            async def event_stream():
                try:
                    async for chunk in backend.chat_stream(internal):
                        yield adapter.format_stream_chunk(chunk, request)
                    tail = adapter.format_stream_end(request)
                    if tail:
                        yield tail
                finally:
                    await pool.release_engine(model_id)

            return StreamingResponse(event_stream(), media_type="text/event-stream")

        # Non-streaming
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

    @app.get("/health")
    async def health():
        return {"status": "ok", "loaded_models": pool.get_loaded_model_ids()}

    @app.get("/api/status")
    async def api_status(_: None = Depends(require_auth)):
        return pool.get_status()

    return app

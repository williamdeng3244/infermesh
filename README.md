# infermesh

A hardware-agnostic LLM inference serving platform. Functionally inspired by
[oMLX](https://github.com/jundot/omlx), but the compute backend is a **pluggable
seam decided at runtime** — run on NVIDIA, AMD, CPU, or a future in-house
accelerator without touching the control plane.

infermesh reuses oMLX's framework-agnostic protocol layer (OpenAI/Anthropic
adapters, model-pool orchestration) and replaces its MLX compute/cache layers
with a single pluggable backend interface.

**Milestones:** **M1** — foundation (pluggable backends, OpenAI + Anthropic chat,
multi-model LRU/pin/TTL pool). **M2** — embeddings + reranker endpoints. **M3** —
admin dashboard. 21 tests green on the mock backend (no GPU).

## The one architectural rule

The control plane (`infermesh/core/`, `infermesh/api/`, `server.py`, `cli.py`)
**must not** import `mlx`, `torch.cuda`, or any vendor SDK. All hardware-specific
code lives under `infermesh/backends/<name>/` behind one interface,
`InferenceBackend`. This is enforced by `tests/test_no_vendor_imports.py`.

```
HTTP JSON (OpenAI or Anthropic)
  -> {OpenAI,Anthropic}Adapter.parse_request()   -> InternalRequest
  -> ModelPool.acquire(model)                     -> InferenceBackend (leased)
  -> backend.chat_stream(InternalRequest)         -> async StreamChunk
  -> adapter.format_stream_chunk / format_response
  -> SSE  or  JSON
```

The **only** types that cross the api ↔ backend boundary are `InternalRequest`,
`InternalResponse`, and `StreamChunk`. Backends never see OpenAI/Anthropic JSON;
the gateway never sees vendor tensors.

## Install

With [uv](https://docs.astral.sh/uv/) (recommended):

```bash
uv venv
uv pip install -e ".[dev]"
```

Or with pip:

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
```

## Quickstart — mock backend (no GPU, no model download)

The `mock` backend echoes your prompt back as a token stream, so the whole stack
is runnable with zero hardware. A "model" is just a directory name; with
`--backend mock` its contents are ignored.

```bash
mkdir -p ~/models/echo
uv run infermesh serve --backend mock --model-dir ~/models --port 8000
# (or, with the venv activated: infermesh serve --backend mock --model-dir ~/models)
```

In another terminal — these all return 200:

```bash
# List models (OpenAI shape)
curl -s http://127.0.0.1:8000/v1/models

# OpenAI chat completion (non-streaming) — echoes the prompt
curl -s http://127.0.0.1:8000/v1/chat/completions \
  -H 'content-type: application/json' \
  -d '{"model":"echo","messages":[{"role":"user","content":"hello from curl"}]}'

# OpenAI chat completion (streaming SSE, terminated by [DONE])
curl -s -N http://127.0.0.1:8000/v1/chat/completions \
  -H 'content-type: application/json' \
  -d '{"model":"echo","messages":[{"role":"user","content":"stream me"}],"stream":true}'

# Anthropic messages (non-streaming)
curl -s http://127.0.0.1:8000/v1/messages \
  -H 'content-type: application/json' \
  -d '{"model":"echo","max_tokens":64,"messages":[{"role":"user","content":"hello from curl"}]}'

# Anthropic messages (streaming: message_start … content_block_delta … message_stop)
curl -s -N http://127.0.0.1:8000/v1/messages \
  -H 'content-type: application/json' \
  -d '{"model":"echo","max_tokens":64,"messages":[{"role":"user","content":"stream me"}],"stream":true}'

# OpenAI-compatible embeddings (deterministic mock vectors)
curl -s http://127.0.0.1:8000/v1/embeddings \
  -H 'content-type: application/json' \
  -d '{"model":"echo","input":["hello world","second text"]}'

# Cohere/Jina-compatible rerank (scored, sorted by query overlap)
curl -s http://127.0.0.1:8000/v1/rerank \
  -H 'content-type: application/json' \
  -d '{"model":"echo","query":"cat dog","documents":["cat dog bird","cat fish","unrelated"]}'

# Pool/memory status
curl -s http://127.0.0.1:8000/api/status
```

### Endpoints

| Method & path | Behavior |
|---|---|
| `POST /v1/chat/completions` | OpenAI adapter; stream + non-stream |
| `POST /v1/messages` | Anthropic adapter; stream + non-stream |
| `POST /v1/embeddings` | OpenAI embeddings (float/base64, optional `dimensions`) |
| `POST /v1/rerank` | Cohere/Jina rerank (`top_n`, `return_documents`, sorted) |
| `GET  /v1/models` | discovered model ids (OpenAI list shape) |
| `GET  /v1/models/status` | per-model loaded/pinned/stats |
| `POST /v1/models/{id}/load` | warm a model (acquire then release) |
| `POST /v1/models/{id}/unload` | unload if idle+unpinned (`?force=true` to force) |
| `POST /v1/models/{id}/pin` · `/unpin` | pin (never evict) / unpin |
| `GET  / · /admin` | admin dashboard (HTML) |
| `GET  /health` | liveness |
| `GET  /api/status` | pool status (loaded models, memory, tps) |

Optional single API key: pass `--api-key KEY`, then send `Authorization: Bearer KEY`
or `x-api-key: KEY`. Off by default.

## Admin dashboard

Open **http://127.0.0.1:8000/** (or `/admin`) in a browser while the server runs.
It is a self-contained dark page (no build step, no JS deps) that auto-refreshes
`/api/status` every 2s: a memory gauge, per-model status / leases / throughput,
and **Load / Unload / Pin / Unpin** buttons. If an API key is enabled, paste it
into the field in the header and the page sends it with every request.

## Run the tests

```bash
uv run pytest          # or:  .venv/bin/pytest
```

21 tests, all green with `MockEchoBackend` — **no GPU, no model, and vllm not
installed**: vendor-import guard, pool lifecycle (discovery / LRU eviction /
pinning / TTL), the OpenAI + Anthropic chat endpoints (stream + non-stream), the
embeddings + rerank endpoints, and the admin dashboard + pin/unpin.

## Run against vLLM (real tokens — manual, needs a GPU + a model)

Not gated in CI. vLLM serves one model per process and has no Anthropic API and
no multi-model management; infermesh's control plane adds exactly that on top.

```bash
pip install '.[vllm]'
infermesh serve --backend vllm --model-dir /path/to/models --max-process-memory 80%
```

`load()` spawns `python -m vllm.entrypoints.openai.api_server --model <dir> --port <free>`,
polls its `/health` until ready (logs under `~/.infermesh/logs/`), then streams
real tokens through `/v1/chat/completions` and `/v1/messages`. Loading a second
model when memory is tight triggers LRU eviction of the first (pinned models are
never evicted). The vendor (`nvidia`/`amd`/`cpu`) is auto-detected.

## What is lifted from oMLX vs. written new

**Lifted ~verbatim** from oMLX `omlx/api/` (zero vendor imports) into
`infermesh/api/` — 14 files, ≈7.1k lines of battle-tested protocol code reused
as-is (imports re-rooted `omlx.*` → `infermesh.*`):

* `adapters/` — `base.py`, `openai.py`, `anthropic.py`, `sse_formatter.py`, `__init__.py`
* `openai_models.py`, `anthropic_models.py`, `shared_models.py`
* `tool_calling.py`, `anthropic_utils.py`, `thinking.py`, `utils.py`
* `embedding_models.py`, `rerank_models.py` (M2)

The only edit beyond import re-rooting: `thinking.py`'s mlx-only
`ThinkingBudgetProcessor` (a logits processor) was removed — it is compute-layer
code with no caller in M1, and the API layer must import with no vendor SDK.

**Adapted** from oMLX `omlx/engine_pool.py` → `infermesh/core/pool.py`: the public
API and the evict-before-load / pin / TTL / in-use-lease *semantics* are preserved;
the bodies were reimplemented against `InferenceBackend` because that cut of
`engine_pool.py` (1408 lines) is deeply MLX-coupled (`mlx_lm.load`,
`mx.clear_cache`, `mx.get_active_memory`, dflash/VLM/speculative). Memory
accounting now sums backends' `stats().used_mem_mb` + a `MemoryProbe`.

**Written new** (the pluggable seam and everything around it):

* `core/backend.py` — `InferenceBackend` interface + dataclasses
* `core/factory.py`, `core/registry.py`, `core/memory.py`, `core/settings.py`
* `backends/mock/mock_backend.py`, `backends/vllm/vllm_backend.py`
* `server.py` (FastAPI gateway — chat + embeddings + rerank), `dashboard.py` (admin UI), `cli.py` (`infermesh serve`), `tests/`

## Project layout

```
infermesh/
├── infermesh/
│   ├── core/        # control plane — ZERO vendor imports
│   │   ├── backend.py factory.py registry.py pool.py memory.py settings.py
│   ├── api/         # protocol layer lifted from oMLX (ZERO vendor imports)
│   │   ├── adapters/ openai_models.py anthropic_models.py tool_calling.py …
│   ├── backends/    # ALL hardware-specific code
│   │   ├── mock/mock_backend.py
│   │   └── vllm/vllm_backend.py
│   ├── server.py    # FastAPI app + routes
│   └── cli.py       # `infermesh serve …`
└── tests/           # green with the mock backend (no GPU)
```

## License

Apache-2.0. Portions adapted from [oMLX](https://github.com/jundot/omlx)
(Apache-2.0); see [`NOTICE`](./NOTICE). Lifted files keep their original
`SPDX-License-Identifier` headers.

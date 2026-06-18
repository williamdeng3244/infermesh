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
admin dashboard. **M4** — furnished dashboard (Chat / Logs / Settings) + runtime
config. **M5** — real vLLM GPU backend (verified on an RTX 5070, Blackwell) + latency/throughput charts. **M6** — light/dark theme + real multi-model LRU eviction on the GPU. **M7** — benchmark suite (latency percentiles · TTFT · throughput). **M8** — hosted-model proxy backend: register OpenAI / Anthropic / OpenRouter / any OpenAI-compatible endpoint via `--providers`, so remote models join the same pool, dashboard, and OpenAI+Anthropic gateway as local vLLM models. **M9** — Claude Code hardening: SSE keep-alives during long prefill, `response_format` parity on the hosted path, and cross-platform background service management (`start` / `stop` / `restart` / `status`). **M10** — in-process **Transformers backend** (`AutoModelForCausalLM` on CUDA / CPU / MPS), the bring-your-own-accelerator path; decoding raw text locally also activates the model-family tool-call parsers (Qwen-XML / Hermes / Llama-bracket / Gemma4) — **verified generating on an RTX 5070**. **M11** — observability: a **Devices** tab (enumerate NVIDIA / AMD / CPU + a per-model GPU picker) and **Metrics + Benchmark history** persisted to `~/.infermesh` so past tests survive a restart. **M12** — comprehensive benchmark: prefill (PP) + decode (TG) tok/s, TTFT, TPOT, E2E percentiles, peak GPU memory, and `same` vs `different` prompt modes (prefix-cache effect), with a single-request profile and copy-to-clipboard. **M13** — **Model Downloader**: search HuggingFace from the dashboard and one-click download a repo into the model dir (background, with progress), auto-registered into the pool when finished. **M14** — **MCP server**: `infermesh mcp` exposes 14 tools (list/load/unload/pin models, run_benchmark, chat, devices, metrics, search/download HF) over stdio so Claude Code and other agents can drive infermesh and run tests themselves. **M15** — **vision-language models**: OpenAI/Anthropic image inputs (base64 / URL / file) flow through a new `InternalMessage.images` to a Transformers vision path (`AutoModelForImageTextToText`) — **verified on an RTX 5070** (SmolVLM correctly read a test image). 77 tests green on the mock backend (no GPU).

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
| `GET  /api/logs` | recent server logs (in-memory ring buffer) |
| `GET · PUT /api/settings` | view / live-edit settings (idle_timeout, api_key) |
| `GET  /api/metrics` | recent per-request latency/throughput samples |
| `POST /api/benchmark` | load benchmark: PP/TG tok/s, TTFT, TPOT, E2E percentiles, peak mem, `mode` |
| `GET  /api/devices` | enumerate compute devices (NVIDIA/AMD/CPU + VRAM) |
| `GET  /api/history` | past benchmark runs + metric samples (persisted) |
| `GET  /api/hf/search` | search HuggingFace models (id, downloads, likes, task) |
| `POST /api/hf/download` | download a repo into the model dir (background) |
| `GET  /api/hf/downloads` | download progress; registers finished models into the pool |

Optional single API key: pass `--api-key KEY`, then send `Authorization: Bearer KEY`
or `x-api-key: KEY`. Off by default.

## Run as a background service

`serve` runs in the foreground; `start` runs the same gateway detached and writes a
pidfile + log under `~/.infermesh/`. Works the same on WSL/Linux and Windows
(dependency-free: POSIX signals or `taskkill`; no systemd/launchd required).

```bash
infermesh start --backend vllm --model-dir ~/models --port 8000   # spawn, wait for /health
infermesh status     # -> running (pid 12345) on 127.0.0.1:8000 [health: ok]
infermesh restart    # stop (if running) then start with the same flags
infermesh stop       # SIGTERM, escalate to SIGKILL after ~5s, remove pidfile
```

`start`/`restart` take all the `serve` flags and forward them to the child. Logs
stream to `~/.infermesh/logs/server-<port>.log`.

### Long-prefill keep-alives (for Claude Code and other long-lived clients)

While a big model is still prefilling and hasn't emitted a token, the stream sends
periodic `: keep-alive` SSE comments so clients (Claude Code especially) don't hit a
read timeout. Tune with `--sse-keepalive SECONDS` (default 15; `0` disables).

## Admin dashboard

Open **http://127.0.0.1:8000/** (or `/admin`) in a browser while the server runs —
a self-contained dark panel (no build step, no JS deps, no CDN) with a sidebar and
eight sections:

- **Models** — memory gauge + live table with **Load / Unload / Pin / Unpin**, plus a **device picker** so a model loads on a chosen GPU/CPU
- **Chat** — pick a model and stream a completion in a chat playground
- **Logs** — live tail of the server's ring-buffered logs, level-colored
- **Metrics** — latency + throughput sparkline charts (canvas, no chart lib)
- **Devices** — detected accelerators (NVIDIA / AMD / CPU) with VRAM used/free/total
- **Download** — search HuggingFace, browse downloads/likes/task, one-click download into the model dir with a progress bar (`pip install '.[downloader]'`)
- **Benchmark** — prefill/decode tok/s, TTFT, TPOT, E2E percentiles, peak GPU memory; `same`/`different` prompt modes, a single-request profile, copy-to-clipboard, and a **persisted history of past runs**
- **Settings** — view all settings and live-edit idle-timeout / API key

If an API key is enabled, paste it into the header field (or set it from the
Settings tab) and the page sends it with every request. A sun/moon button in the
header toggles **light / dark** mode (persisted in the browser; defaults dark).

## Run the tests

```bash
uv run pytest          # or:  .venv/bin/pytest
```

77 tests, all green with `MockEchoBackend` — **no GPU, no model, and vllm/torch not
installed**: vendor-import guard, pool lifecycle (discovery / LRU eviction /
pinning / TTL), the OpenAI + Anthropic chat endpoints (stream + non-stream), the
embeddings + rerank endpoints, the admin dashboard + pin/unpin, the logs / settings
/ metrics endpoints, the vLLM launch-arg builder, the benchmark runner, the
OpenAI-compat proxy backend (key resolution / request body / provider-file registration),
SSE keep-alives during prefill, `response_format` forwarding, the background-service
helpers (arg forwarding / pidfile / liveness / status), the family tool-call parsers
(Qwen-XML, …), and the Transformers backend's registration / prompt / tool wiring.
The Transformers backend's actual GPU generation is verified out-of-band (an RTX
5070), not in this suite, which stays hardware-free by design.

## Run against vLLM (real tokens on a GPU)

**Verified** end-to-end on an NVIDIA RTX 5070 Laptop GPU (Blackwell, sm_120, 8 GB):
infermesh loaded `Qwen2.5-0.5B-Instruct` (real tokens at ~60 tok/s) and demonstrated
**LRU eviction** — loading `Qwen2.5-1.5B-Instruct` evicts the 0.5B, since 8 GB holds
one at a time, then serves the bigger model. Pinned models are never evicted.
vLLM serves one model per process and has no Anthropic API and no multi-model
management; infermesh's control plane adds exactly that on top.

```bash
pip install '.[vllm]'
infermesh serve --backend vllm --model-dir /path/to/models --max-process-memory 80%
```

`load()` spawns `python -m vllm.entrypoints.openai.api_server` per model, polls its
`/health` (logs under `~/.infermesh/logs/`), then streams real tokens through
`/v1/chat/completions` and `/v1/messages`; the **Metrics** tab fills in with real
latency/throughput. Loading a second model under memory pressure LRU-evicts the
first (pinned never evicted); vendor (`nvidia`/`amd`/`cpu`) is auto-detected.

Per-model tuning rides on `ModelSpec.extra`: `vllm_args` (e.g.
`{"enforce-eager": true, "gpu-memory-utilization": 0.8, "max-model-len": 4096}`)
and `env` for the sidecar's environment. On a host with only the CUDA **runtime**
(no toolkit): install a C compiler (`build-essential python3-dev`) so Triton can
JIT, and set `env={"VLLM_USE_FLASHINFER_SAMPLER": "0"}` so vLLM uses its native
sampler instead of JIT-compiling FlashInfer kernels (which needs `nvcc`).

## Run on a local GPU/CPU in-process (Transformers backend)

The `transformers` backend loads a HuggingFace causal LM **in-process** with
`torch` and decodes locally — no sidecar, no HTTP API. It's the "bring your own
accelerator" path: NVIDIA, AMD (ROCm torch), Apple `mps`, CPU, or a custom device
with a torch backend. **Verified** generating `Qwen2.5-0.5B-Instruct` on an NVIDIA
RTX 5070 (fp16, ~950 MB VRAM) and on CPU.

```bash
pip install '.[transformers]'        # torch + transformers + accelerate
infermesh serve --backend transformers --model-dir /path/to/hf/models
```

A "model" is a HuggingFace repo id or a local snapshot dir. Per-model knobs ride on
`ModelSpec.extra`: `device` (`cuda`/`cpu`/`mps`/`cuda:1`, default auto), `dtype`
(`float16`/`bfloat16`/`float32`), `trust_remote_code`, `max_new_tokens`. Streaming
uses `TextIteratorStreamer`; `unload()` frees the model and empties the CUDA cache
so the pool's LRU eviction reclaims VRAM.

**Local tool calling.** Because this backend decodes raw text, it runs model output
through `infermesh.api.tool_calling.parse_tool_calls` — the family-format parsers
lifted from oMLX (Qwen/GLM `<tool_call>` XML, Hermes, Llama-bracket, Gemma4,
namespaced/MiniMax). When a request supplies `tools`, the decoded text is parsed and
returned as OpenAI-shaped `tool_calls` (with `finish_reason: "tool_calls"`). vLLM and
the hosted proxy get tool calls from their servers; this backend parses them itself.

**Vision-language models.** Set `extra={"vision": true}` (or load a model whose
`config.json` is a VLM) and the backend uses `AutoModelForImageTextToText` +
`AutoProcessor`. OpenAI `image_url` parts and Anthropic `image` blocks (base64 /
URL / file path) ride on `InternalMessage.images` and are fed to the processor.
Verified on an RTX 5070: `HuggingFaceTB/SmolVLM-256M-Instruct` (~490 MB) read a
test image and answered correctly.

## Connect hosted models (OpenAI / Anthropic / OpenRouter / …)

The `openai` backend is a **proxy**: instead of running a model locally it forwards
each request to any OpenAI-compatible HTTP API. Hosted models then live in the same
pool, dashboard, and OpenAI + Anthropic gateway as local vLLM models — and since
they use no local VRAM, they're registered at **0 MB** and never evict (or get
evicted by) a GPU model.

Register them with a `--providers` JSON file:

```json
{
  "models": [
    { "id": "gpt-4o-mini",
      "base_url": "https://api.openai.com/v1",
      "api_key": "env:OPENAI_API_KEY" },

    { "id": "claude-3-5-sonnet",
      "base_url": "https://api.anthropic.com/v1",
      "upstream_model": "claude-3-5-sonnet-20241022",
      "api_key": "env:ANTHROPIC_API_KEY" },

    { "id": "llama-3.3-70b",
      "base_url": "https://openrouter.ai/api/v1",
      "upstream_model": "meta-llama/llama-3.3-70b-instruct",
      "api_key": "env:OPENROUTER_API_KEY" }
  ]
}
```

* `id` — the model id clients use against infermesh (in `/v1/chat/completions`, the dashboard, etc.).
* `base_url` — the provider's OpenAI-compatible root (default `https://api.openai.com/v1`). Anthropic exposes one at `https://api.anthropic.com/v1`. A local server (e.g. another vLLM) works too.
* `upstream_model` — the provider's own model name (defaults to `id`).
* `api_key` — `"env:VAR"` reads `VAR` from the environment, so **keys never live in the file or in git**. A literal string also works but isn't recommended.

```bash
export OPENAI_API_KEY=sk-...           # keys stay in your shell, never committed
export ANTHROPIC_API_KEY=sk-ant-...
# mix local GPU models and hosted models in one gateway:
infermesh serve --backend vllm --model-dir /path/to/models --providers ~/providers.json
# or hosted-only, no GPU needed:
infermesh serve --providers ~/providers.json
```

Now `curl http://127.0.0.1:8000/v1/models` lists local and hosted models together,
the dashboard's **Chat** tab can talk to `gpt-4o-mini`, and both the OpenAI
(`/v1/chat/completions`) and Anthropic (`/v1/messages`) endpoints route to whichever
backend the chosen model uses. Streaming, usage tokens, and embeddings are
forwarded; the control plane still imports no vendor SDK (the proxy is just `httpx`).

## Drive it from an agent (MCP server)

`infermesh mcp` runs a stdio [MCP](https://modelcontextprotocol.io) server that
proxies to a running gateway, so an agent (Claude Code included) can list / load /
unload / pin models, run benchmarks, chat, inspect devices/metrics, and search +
download HuggingFace models — i.e. run tests itself.

```bash
pip install '.[mcp]'
infermesh start --backend transformers --model-dir ~/models   # a gateway must be running
```

Register it with Claude Code (`.mcp.json`):

```json
{
  "mcpServers": {
    "infermesh": { "command": "infermesh", "args": ["mcp", "--base-url", "http://127.0.0.1:8000"] }
  }
}
```

Tools: `list_models`, `pool_status`, `load_model`, `unload_model`, `pin_model`,
`unpin_model`, `run_benchmark`, `chat`, `recent_metrics`, `benchmark_history`,
`list_devices`, `search_models`, `download_model`, `download_status`. Pass
`--api-key` if the gateway has auth enabled. The server is a thin httpx wrapper
over the HTTP API (no vendor SDK); `mcp` is imported lazily.

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
* `backends/mock/mock_backend.py`, `backends/vllm/vllm_backend.py`, `backends/openai/openai_backend.py` (hosted-model proxy), `backends/transformers/transformers_backend.py` (in-process GPU/CPU)
* `server.py` (FastAPI gateway — chat + embeddings + rerank + logs/settings/metrics/benchmark), `dashboard.py` (6-section admin UI), `core/benchmark.py`, `cli.py` (`infermesh serve`), `tests/`

## Project layout

```
infermesh/
├── infermesh/
│   ├── core/        # control plane — ZERO vendor imports
│   │   ├── backend.py factory.py registry.py pool.py memory.py settings.py
│   ├── api/         # protocol layer lifted from oMLX (ZERO vendor imports)
│   │   ├── adapters/ openai_models.py anthropic_models.py tool_calling.py …
│   ├── backends/    # ALL hardware-specific (and remote-provider) code
│   │   ├── mock/mock_backend.py
│   │   ├── vllm/vllm_backend.py
│   │   ├── openai/openai_backend.py   # proxy to OpenAI/Anthropic/… (httpx, no SDK)
│   │   └── transformers/transformers_backend.py  # in-process torch on GPU/CPU/MPS
│   ├── server.py    # FastAPI app + routes
│   └── cli.py       # `infermesh serve …`
└── tests/           # green with the mock backend (no GPU)
```

## License

Apache-2.0. Portions adapted from [oMLX](https://github.com/jundot/omlx)
(Apache-2.0); see [`NOTICE`](./NOTICE). Lifted files keep their original
`SPDX-License-Identifier` headers.

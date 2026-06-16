# infermesh

A hardware-agnostic LLM inference serving platform. Functionally inspired by
[oMLX](https://github.com/jundot/omlx), but with the compute backend as a
pluggable seam decided at runtime — run on NVIDIA, AMD, CPU, or a future in-house
accelerator without changing the control plane.

> **Status:** Milestone 1 (foundation). See the build summary at the end of this
> file for what is lifted from oMLX vs. written new.

## The one architectural rule

The control plane (`infermesh/core/`, `infermesh/api/`, `server.py`, `cli.py`)
**must not** import `mlx`, `torch.cuda`, or any vendor SDK. All hardware-specific
code lives under `infermesh/backends/<name>/` behind a single `InferenceBackend`
interface. This is enforced by `tests/test_no_vendor_imports.py`.

```
HTTP (OpenAI or Anthropic JSON)
  -> {OpenAI,Anthropic}Adapter.parse_request()  -> InternalRequest
  -> ModelPool.acquire(model)                    -> InferenceBackend (leased)
  -> backend.chat_stream(InternalRequest)        -> async StreamChunk
  -> {OpenAI,Anthropic}SSEFormatter | format_response()
  -> HTTP (SSE or JSON)
```

The only types that cross the api <-> backend boundary are `InternalRequest`,
`InternalResponse`, and `StreamChunk`.

## Quickstart

_(Filled in once the gateway is running — see Milestone 1 tasks.)_

## License

Apache-2.0. Portions adapted from [oMLX](https://github.com/jundot/omlx)
(Apache-2.0); see [`NOTICE`](./NOTICE).

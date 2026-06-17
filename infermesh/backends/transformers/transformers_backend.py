# SPDX-License-Identifier: Apache-2.0
"""TransformersBackend — run a HuggingFace model in-process on a local GPU/CPU.

This is the "bring your own accelerator" backend: it loads a causal LM with
``transformers`` + ``torch`` and decodes locally, so it works on NVIDIA, AMD
(ROCm torch), Apple (mps), CPU, or a custom accelerator with a torch backend —
no sidecar server, no vendor HTTP API. Because it decodes *raw text*, it is also
where the model-family tool-call parsers in :mod:`infermesh.api.tool_calling`
(Qwen-XML / Hermes / Llama-bracket / GLM / Gemma4 …) come alive: after generation
the raw output is run through :func:`parse_tool_calls`.

``torch``/``transformers`` are imported lazily inside methods so importing this
module (and the control plane) never requires them. Install the extra:
``pip install 'infermesh[transformers]'``.

Per-model config via ``ModelSpec.extra``:
  * ``device``            "cuda" | "cpu" | "mps" | explicit "cuda:1" (default: auto)
  * ``dtype``             "float16" | "bfloat16" | "float32" (default: fp16 on GPU, fp32 on CPU)
  * ``trust_remote_code`` bool (default False)
  * ``max_new_tokens``    default cap when a request doesn't set max_tokens (default 512)
  * ``estimated_mb``      override the pool's memory estimate (else computed from weights)
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import threading
from typing import Any, AsyncIterator, Optional

from infermesh.api.adapters.base import InternalRequest, InternalResponse, StreamChunk
from infermesh.api.tool_calling import parse_tool_calls
from infermesh.core.backend import (
    BackendCaps,
    EngineStats,
    HardwareInfo,
    HealthStatus,
    InferenceBackend,
    ModelSpec,
)

logger = logging.getLogger("infermesh.backends.transformers")

_DTYPES = {
    "float16": "float16", "fp16": "float16", "half": "float16",
    "bfloat16": "bfloat16", "bf16": "bfloat16",
    "float32": "float32", "fp32": "float32", "float": "float32",
}
_SENTINEL = object()


class TransformersBackend(InferenceBackend):
    """One HuggingFace causal LM loaded in-process, decoding on a local device."""

    def __init__(self) -> None:
        self._spec: Optional[ModelSpec] = None
        self._model: Any = None
        self._tokenizer: Any = None
        self._device: str = "cpu"
        self._loaded: bool = False
        self._estimated_mb: int = 0
        self._hardware: Optional[HardwareInfo] = None

    @property
    def backend_name(self) -> str:
        return "transformers"

    def capabilities(self) -> BackendCaps:
        return BackendCaps(streaming=True, tool_calling=True, embeddings=False)

    def hardware(self) -> HardwareInfo:
        if self._hardware is None:
            self._hardware = self._detect_hardware()
        return self._hardware

    @staticmethod
    def _detect_hardware() -> HardwareInfo:
        try:
            import torch
        except Exception:  # torch not installed yet
            return HardwareInfo(vendor="cpu", device_count=0)
        if torch.cuda.is_available():
            count = torch.cuda.device_count()
            # ROCm builds of torch also report through cuda.* but set torch.version.hip.
            vendor = "amd" if getattr(torch.version, "hip", None) else "nvidia"
            total_mb = int(torch.cuda.get_device_properties(0).total_memory // (1024 * 1024))
            return HardwareInfo(vendor=vendor, device_count=count, mem_per_device_mb=total_mb)
        if getattr(getattr(torch, "backends", None), "mps", None) and torch.backends.mps.is_available():
            return HardwareInfo(vendor="apple", device_count=1)
        return HardwareInfo(vendor="cpu", device_count=0)

    # ------------------------------ lifecycle ------------------------------ #
    async def load(self, spec: ModelSpec) -> None:
        self._spec = spec
        if importlib.util.find_spec("transformers") is None or importlib.util.find_spec("torch") is None:
            raise RuntimeError(
                "transformers/torch are not installed. Install the extra: "
                "pip install 'infermesh[transformers]'"
            )
        await asyncio.to_thread(self._load_sync, spec)
        self._loaded = True
        logger.info("Loaded '%s' on %s (%d MB weights)", spec.model_id, self._device, self._estimated_mb)

    def _load_sync(self, spec: ModelSpec) -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        extra = spec.extra or {}
        device = extra.get("device") or ("cuda" if torch.cuda.is_available() else "cpu")
        dtype_name = _DTYPES.get(str(extra.get("dtype", "")).lower())
        if dtype_name is None:
            dtype_name = "float16" if str(device).startswith("cuda") else "float32"
        torch_dtype = getattr(torch, dtype_name)
        trust = bool(extra.get("trust_remote_code", False))

        self._tokenizer = AutoTokenizer.from_pretrained(spec.source, trust_remote_code=trust)
        try:  # transformers v5 renamed torch_dtype -> dtype
            self._model = AutoModelForCausalLM.from_pretrained(
                spec.source, dtype=torch_dtype, trust_remote_code=trust,
            )
        except TypeError:
            self._model = AutoModelForCausalLM.from_pretrained(
                spec.source, torch_dtype=torch_dtype, trust_remote_code=trust,
            )
        self._model.to(device)
        self._model.eval()
        self._device = str(device)

        weight_bytes = sum(p.numel() * p.element_size() for p in self._model.parameters())
        self._estimated_mb = int(extra.get("estimated_mb") or (weight_bytes // (1024 * 1024)))

    async def unload(self) -> None:
        self._loaded = False
        model, self._model, self._tokenizer = self._model, None, None
        del model
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:  # best-effort
            pass

    async def health(self) -> HealthStatus:
        return HealthStatus(self._loaded, detail="loaded" if self._loaded else "not loaded")

    # ------------------------------ inference ------------------------------ #
    def _build_prompt(self, req: InternalRequest) -> str:
        messages = [{"role": m.role, "content": m.content} for m in req.messages]
        tok = self._tokenizer
        if getattr(tok, "chat_template", None):
            try:
                return tok.apply_chat_template(
                    messages, tools=(req.tools or None),
                    add_generation_prompt=True, tokenize=False,
                )
            except TypeError:  # older template without a `tools` kwarg
                return tok.apply_chat_template(
                    messages, add_generation_prompt=True, tokenize=False,
                )
        return "\n".join(f"{m['role']}: {m['content']}" for m in messages) + "\nassistant:"

    def _sampling_kwargs(self, req: InternalRequest) -> dict:
        extra = self._spec.extra if self._spec else {}
        max_new = req.max_tokens or int(extra.get("max_new_tokens", 512))
        kwargs: dict = {"max_new_tokens": max_new}
        if req.temperature and req.temperature > 0:
            kwargs.update(do_sample=True, temperature=req.temperature, top_p=req.top_p or 1.0)
            if req.top_k:
                kwargs["top_k"] = req.top_k
        else:
            kwargs["do_sample"] = False
        return kwargs

    def _generate_sync(self, prompt: str, req: InternalRequest) -> tuple[str, int, int]:
        import torch
        inputs = self._tokenizer(prompt, return_tensors="pt").to(self._device)
        pad_id = self._tokenizer.pad_token_id
        if pad_id is None:
            pad_id = self._tokenizer.eos_token_id
        with torch.no_grad():
            out = self._model.generate(**inputs, pad_token_id=pad_id, **self._sampling_kwargs(req))
        prompt_len = inputs["input_ids"].shape[1]
        gen_ids = out[0][prompt_len:]
        text = self._tokenizer.decode(gen_ids, skip_special_tokens=True)
        return text, int(prompt_len), int(gen_ids.shape[0])

    def _parse_tools(self, text: str, req: InternalRequest) -> tuple[str, Optional[list], str]:
        """Run the family tool-call parsers; return (text, tool_call_dicts, finish_reason)."""
        if not req.tools:
            return text, None, "stop"
        cleaned, tool_calls = parse_tool_calls(text, self._tokenizer, req.tools)
        if tool_calls:
            return cleaned, [tc.model_dump() for tc in tool_calls], "tool_calls"
        return text, None, "stop"

    async def chat(self, req: InternalRequest) -> InternalResponse:
        """Native non-streaming path — needed so tool calls are parsed from the
        full decoded text (the base aggregator does not collect tool calls)."""
        if not self._loaded:
            raise RuntimeError("TransformersBackend.chat() called before load()")
        prompt = self._build_prompt(req)
        text, pt, ct = await asyncio.to_thread(self._generate_sync, prompt, req)
        text, tool_calls, finish = self._parse_tools(text, req)
        return InternalResponse(
            text=text, finish_reason=finish, prompt_tokens=pt, completion_tokens=ct,
            tool_calls=tool_calls, model=req.model,
        )

    async def chat_stream(self, req: InternalRequest) -> AsyncIterator[StreamChunk]:
        if not self._loaded:
            raise RuntimeError("TransformersBackend.chat_stream() called before load()")

        # Tool-call requests buffer-then-parse (avoids leaking raw <tool_call>
        # markup mid-stream); plain chat streams token-by-token live.
        if req.tools:
            resp = await self.chat(req)
            if resp.text:
                yield StreamChunk(text=resp.text, is_first=True)
            for tc in (resp.tool_calls or []):
                yield StreamChunk(text="", tool_call_delta=tc)
            yield StreamChunk(text="", is_last=True, finish_reason=resp.finish_reason,
                              prompt_tokens=resp.prompt_tokens, completion_tokens=resp.completion_tokens)
            return

        from transformers import TextIteratorStreamer

        prompt = self._build_prompt(req)
        inputs = self._tokenizer(prompt, return_tensors="pt").to(self._device)
        prompt_len = int(inputs["input_ids"].shape[1])
        pad_id = self._tokenizer.pad_token_id or self._tokenizer.eos_token_id
        streamer = TextIteratorStreamer(self._tokenizer, skip_prompt=True, skip_special_tokens=True)
        gen_kwargs = {**inputs, "pad_token_id": pad_id, "streamer": streamer, **self._sampling_kwargs(req)}
        thread = threading.Thread(target=self._model.generate, kwargs=gen_kwargs)
        thread.start()

        first = True
        acc = ""
        try:
            while True:
                piece = await asyncio.to_thread(next, streamer, _SENTINEL)
                if piece is _SENTINEL:
                    break
                if piece:
                    acc += piece
                    yield StreamChunk(text=piece, is_first=first)
                    first = False
        finally:
            await asyncio.to_thread(thread.join)

        completion_tokens = len(self._tokenizer(acc, add_special_tokens=False)["input_ids"]) if acc else 0
        yield StreamChunk(text="", is_first=first, is_last=True, finish_reason="stop",
                          prompt_tokens=prompt_len, completion_tokens=completion_tokens)

    # ------------------------------ stats ---------------------------------- #
    def stats(self) -> EngineStats:
        return EngineStats(
            model_id=self._spec.model_id if self._spec else "",
            loaded=self._loaded,
            used_mem_mb=self._estimated_mb if self._loaded else 0,
            extra={"device": self._device, "vendor": self.hardware().vendor},
        )

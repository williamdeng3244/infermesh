# SPDX-License-Identifier: Apache-2.0
"""VLLMBackend — drive a vLLM OpenAI-compatible server as a per-model sidecar.

vLLM already exposes an OpenAI-compatible server, but it serves one model per
process and has no Anthropic API and no multi-model management — exactly the
value infermesh's control plane adds on top. This backend spawns the vLLM
sidecar in ``load()``, talks to it over HTTP via ``httpx``, and tears it down in
``unload()``. It runs on NVIDIA / AMD / CPU depending on the vLLM build.

``vllm`` is NOT imported at module level: the sidecar (a separate process) is the
only thing that needs it, so importing this module never requires vllm. ``load()``
verifies vllm is importable (via find_spec) before spawning. Install with the
extra: ``pip install 'infermesh[vllm]'``.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
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
from infermesh.core.settings import LOG_DIR

logger = logging.getLogger("infermesh.backends.vllm")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _run(cmd: list[str]) -> Optional[str]:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def _metric(text: str, name: str) -> float:
    """Read the first value of a Prometheus gauge ``name`` from /metrics text."""
    for line in text.splitlines():
        if line.startswith(name) and not line.startswith("#"):
            try:
                return float(line.rsplit(" ", 1)[1])
            except (IndexError, ValueError):
                return 0.0
    return 0.0


class VLLMBackend(InferenceBackend):
    """One vLLM sidecar process serving one model, fronted by HTTP."""

    def __init__(self) -> None:
        self._spec: Optional[ModelSpec] = None
        self._proc: Optional[subprocess.Popen] = None
        self._log_file = None
        self._log_path = None
        self._port: Optional[int] = None
        self._base_url: Optional[str] = None
        self._loaded: bool = False
        self._estimated_mb: int = 0
        self._hardware: Optional[HardwareInfo] = None

    @property
    def backend_name(self) -> str:
        return "vllm"

    def capabilities(self) -> BackendCaps:
        # TODO: wire LMCache for tiered/SSD KV (tiered_kv=True) in a later milestone.
        return BackendCaps(
            streaming=True,
            tool_calling=True,
            tensor_parallel=True,
            tiered_kv=False,
        )

    def hardware(self) -> HardwareInfo:
        if self._hardware is None:
            self._hardware = self._detect_hardware()
        return self._hardware

    @staticmethod
    def _detect_hardware() -> HardwareInfo:
        nv = _run(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"])
        if nv is not None:
            mems = [int(x) for x in nv.split() if x.strip().isdigit()]
            return HardwareInfo(
                vendor="nvidia",
                device_count=len(mems),
                mem_per_device_mb=mems[0] if mems else 0,
                detail={"per_device_mb": mems},
            )
        rocm = _run(["rocm-smi", "--showproductname"])
        if rocm is not None:
            count = sum(1 for line in rocm.splitlines() if "GPU" in line)
            return HardwareInfo(vendor="amd", device_count=max(count, 1))
        return HardwareInfo(vendor="cpu", device_count=0)

    # ------------------------------ lifecycle ------------------------------ #
    async def load(self, spec: ModelSpec) -> None:
        self._spec = spec
        if importlib.util.find_spec("vllm") is None:
            raise RuntimeError(
                "vllm is not installed. Install the extra: pip install 'infermesh[vllm]'"
            )

        self._port = _free_port()
        self._base_url = f"http://127.0.0.1:{self._port}"
        self._estimated_mb = int(spec.extra.get("estimated_mb", 8192))

        LOG_DIR.mkdir(parents=True, exist_ok=True)
        safe_id = spec.model_id.replace("/", "_")
        self._log_path = LOG_DIR / f"vllm-{safe_id}-{self._port}.log"

        cmd = [
            sys.executable, "-m", "vllm.entrypoints.openai.api_server",
            "--model", spec.source,
            "--port", str(self._port),
            "--served-model-name", spec.model_id,
        ]
        if spec.max_context:
            cmd += ["--max-model-len", str(spec.max_context)]
        if spec.quantization:
            cmd += ["--quantization", spec.quantization]
        # Arbitrary passthrough flags, e.g. extra={"vllm_args": {"tensor-parallel-size": 2}}
        for key, value in (spec.extra.get("vllm_args") or {}).items():
            cmd += [f"--{key}", str(value)]

        logger.info("Spawning vLLM sidecar: %s (logs -> %s)", " ".join(cmd), self._log_path)
        self._log_file = open(self._log_path, "ab")
        # start_new_session detaches into its own process group so unload() can
        # signal the whole group (vLLM spawns workers).
        self._proc = subprocess.Popen(
            cmd, stdout=self._log_file, stderr=subprocess.STDOUT, start_new_session=True
        )

        timeout = float(spec.extra.get("startup_timeout", 300.0))
        await self._await_health(timeout)
        self._loaded = True
        logger.info("vLLM sidecar for '%s' healthy at %s", spec.model_id, self._base_url)

    async def _await_health(self, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        async with httpx.AsyncClient(timeout=5.0) as client:
            while time.monotonic() < deadline:
                if self._proc is not None and self._proc.poll() is not None:
                    raise RuntimeError(
                        f"vLLM exited early (code {self._proc.returncode}); see {self._log_path}"
                    )
                try:
                    resp = await client.get(f"{self._base_url}/health")
                    if resp.status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                await asyncio.sleep(1.0)
        raise TimeoutError(
            f"vLLM did not become healthy within {timeout:.0f}s; see {self._log_path}"
        )

    async def unload(self) -> None:
        self._loaded = False
        proc, self._proc = self._proc, None
        if proc is not None and proc.poll() is None:
            self._signal_group(proc, signal.SIGTERM)
            for _ in range(50):  # ~5s grace
                if proc.poll() is not None:
                    break
                await asyncio.sleep(0.1)
            if proc.poll() is None:
                self._signal_group(proc, signal.SIGKILL)
        if self._log_file is not None:
            try:
                self._log_file.close()
            except OSError:
                pass
            self._log_file = None

    @staticmethod
    def _signal_group(proc: subprocess.Popen, sig: int) -> None:
        try:
            os.killpg(os.getpgid(proc.pid), sig)
        except (ProcessLookupError, PermissionError):
            try:
                proc.send_signal(sig)
            except ProcessLookupError:
                pass

    async def health(self) -> HealthStatus:
        if not self._loaded or not self._base_url:
            return HealthStatus(healthy=False, detail="not loaded")
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._base_url}/health")
                return HealthStatus(resp.status_code == 200, detail=f"http {resp.status_code}")
        except httpx.HTTPError as exc:
            return HealthStatus(healthy=False, detail=str(exc))

    # ------------------------------ inference ------------------------------ #
    def _build_openai_body(self, req: InternalRequest) -> dict:
        body: dict = {
            "model": req.model or (self._spec.model_id if self._spec else ""),
            "messages": [{"role": m.role, "content": m.content} for m in req.messages],
            "max_tokens": req.max_tokens,
            "temperature": req.temperature,
            "top_p": req.top_p,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if req.top_k:
            body["top_k"] = req.top_k
        if req.min_p:
            body["min_p"] = req.min_p
        if req.presence_penalty:
            body["presence_penalty"] = req.presence_penalty
        if req.frequency_penalty:
            body["frequency_penalty"] = req.frequency_penalty
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
            raise RuntimeError("VLLMBackend.chat_stream() called before load()")

        body = self._build_openai_body(req)
        url = f"{self._base_url}/v1/chat/completions"
        first = True
        finish_reason: Optional[str] = None
        prompt_tokens = completion_tokens = cached_tokens = 0

        async with httpx.AsyncClient(timeout=None) as client:
            async with client.stream("POST", url, json=body) as resp:
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
                        details = usage.get("prompt_tokens_details") or {}
                        cached_tokens = details.get("cached_tokens", cached_tokens)

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
                            text=text,
                            reasoning_content=reasoning,
                            tool_call_delta=tool_calls,
                            is_first=first,
                            is_last=False,
                        )
                        first = False

        # Terminal chunk carries finish_reason + final usage (mirrors MockEchoBackend
        # and the standard OpenAI empty-delta final chunk).
        yield StreamChunk(
            text="",
            is_first=first,
            is_last=True,
            finish_reason=finish_reason or "stop",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
        )

    # ------------------------------ stats ---------------------------------- #
    def stats(self) -> EngineStats:
        running = waiting = 0.0
        gen_tps = prompt_tps = 0.0
        if self._loaded and self._base_url:
            try:
                with urllib.request.urlopen(f"{self._base_url}/metrics", timeout=0.3) as resp:
                    text = resp.read().decode("utf-8", "replace")
                running = _metric(text, "vllm:num_requests_running")
                waiting = _metric(text, "vllm:num_requests_waiting")
                gen_tps = _metric(text, "vllm:avg_generation_throughput_toks_per_s")
                prompt_tps = _metric(text, "vllm:avg_prompt_throughput_toks_per_s")
            except Exception:  # noqa: BLE001 - metrics are best-effort
                pass
        return EngineStats(
            model_id=self._spec.model_id if self._spec else "",
            loaded=self._loaded,
            prompt_tps=prompt_tps,
            generation_tps=gen_tps,
            queue_depth=int(waiting),
            active_requests=int(running),
            used_mem_mb=self._estimated_mb if self._loaded else 0,
            extra={"base_url": self._base_url, "vendor": self.hardware().vendor},
        )

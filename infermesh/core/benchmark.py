# SPDX-License-Identifier: Apache-2.0
"""Benchmark runner — fire concurrent streaming completions at a pooled model and
aggregate prefill (PP) / decode (TG) throughput, TTFT, TPOT, latency, and peak GPU
memory.

Backend-agnostic: drives the model through ``pool.acquire`` + ``chat_stream``, so it
works identically against the mock backend or a real GPU model. Two prompt modes
exercise prefix caching: ``"same"`` (every request shares one prompt → cacheable
prefill) vs ``"different"`` (each request gets a unique *leading* prompt → no
prefix sharing, a more realistic number). Imports no vendor SDK; peak GPU memory is
sampled best-effort via ``nvidia-smi`` (subprocess).

Per request we measure: TTFT (time to first token), E2E latency, prompt tokens, and
completion tokens. From those:
  * PP TPS  = prompt_tokens / TTFT            (prefill throughput)
  * TG TPS  = (out_tokens - 1) / (E2E - TTFT) (decode throughput)
  * TPOT ms = (E2E - TTFT) / (out_tokens - 1) (time per output token)
A single-request profile is just ``requests=1, concurrency=1``.
"""

from __future__ import annotations

import asyncio
import subprocess
import time
from statistics import mean
from typing import Callable, Optional

from infermesh.api.adapters.base import InternalMessage, InternalRequest

DEFAULT_PROMPT = "Write one concise sentence about distributed systems."


def _pct(values: list[float], p: float) -> float:
    """Nearest-rank percentile of a pre-sorted list."""
    if not values:
        return 0.0
    idx = min(len(values) - 1, max(0, int(round((p / 100.0) * (len(values) - 1)))))
    return values[idx]


def _stats(values: list[float]) -> dict:
    """mean / p50 / p90 / p99 / min / max for a list (rounded)."""
    s = sorted(v for v in values if v is not None)
    if not s:
        return {"mean": 0.0, "p50": 0.0, "p90": 0.0, "p99": 0.0, "min": 0.0, "max": 0.0}
    return {
        "mean": round(mean(s), 1), "p50": round(_pct(s, 50), 1),
        "p90": round(_pct(s, 90), 1), "p99": round(_pct(s, 99), 1),
        "min": round(s[0], 1), "max": round(s[-1], 1),
    }


def _gpu_mem_used_mb() -> Optional[int]:
    """Highest per-GPU memory.used in MB via nvidia-smi, or None if unavailable."""
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=2,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    vals: list[int] = []
    for tok in r.stdout.split():
        try:
            vals.append(int(float(tok)))
        except ValueError:
            continue
    return max(vals) if vals else None


def _prompt_for(mode: str, prompt: str, i: int) -> str:
    # "different" varies the LEADING text so no prefix is shared across requests.
    return f"[req {i}] {prompt}" if mode == "different" else prompt


async def run_benchmark(
    pool,
    model_id: str,
    *,
    requests: int = 20,
    concurrency: int = 4,
    max_tokens: int = 64,
    prompt: str = DEFAULT_PROMPT,
    mode: str = "same",
    should_stop: Optional[Callable[[], bool]] = None,
    on_progress: Optional[Callable[[int, int], None]] = None,
) -> dict:
    """Fire ``requests`` streaming completions (≤ ``concurrency`` at once) and return
    latency / TTFT / TPOT / prefill+decode throughput / peak-memory statistics.

    ``should_stop`` is polled at request boundaries (cooperative cancellation:
    remaining requests are skipped, completed samples still aggregate).
    ``on_progress(completed, total)`` fires after each request finishes."""
    requests = max(1, requests)
    mode = "different" if str(mode).lower() == "different" else "same"
    sem = asyncio.Semaphore(max(1, concurrency))
    samples: list[dict] = []
    dev = {"device": None, "vendor": None}   # captured from the backend during the run

    async def _one(i: int) -> None:
        async with sem:
            if should_stop and should_stop():
                return  # cancelled at the request boundary — issue nothing further
            req = InternalRequest(
                messages=[InternalMessage(role="user", content=_prompt_for(mode, prompt, i))],
                max_tokens=max_tokens,
                stream=True,
            )
            start = time.perf_counter()
            ttft: Optional[float] = None
            comp = 0
            prompt_toks = 0
            ok = True
            try:
                async with pool.acquire(model_id) as backend:
                    if dev["device"] is None:
                        try:
                            _e = backend.stats().extra or {}
                            dev["device"], dev["vendor"] = _e.get("device"), _e.get("vendor")
                        except Exception:
                            pass
                    async for chunk in backend.chat_stream(req):
                        if ttft is None and (chunk.text or chunk.reasoning_content):
                            ttft = (time.perf_counter() - start) * 1000.0
                        if chunk.completion_tokens:
                            comp = chunk.completion_tokens
                        if chunk.prompt_tokens:
                            prompt_toks = chunk.prompt_tokens
            except Exception:  # noqa: BLE001 - a failed request is itself a data point
                ok = False
            samples.append({
                "latency_ms": (time.perf_counter() - start) * 1000.0,
                "ttft_ms": ttft, "tokens": comp, "prompt_tokens": prompt_toks, "ok": ok,
            })
            if on_progress:
                try:
                    on_progress(len(samples), requests)
                except Exception:  # noqa: BLE001 - progress reporting is best-effort
                    pass

    # Best-effort peak device-memory sampler: nvidia-smi first, else the backend's
    # own report via pool.get_status() (covers Enflame GCU / any accelerator).
    peak = [0]
    stop = asyncio.Event()

    def _mem_now() -> Optional[int]:
        m = _gpu_mem_used_mb()
        if m is not None:
            return m
        try:
            for mm in pool.get_status().get("models", []):
                if mm.get("id") == model_id:
                    um = (mm.get("stats") or {}).get("used_mem_mb") or 0
                    return int(um) or None
        except Exception:
            pass
        return None

    async def _sampler() -> None:
        # Sample throughout (the model may only load partway through a cold run, so
        # never early-exit on an initial None — that's how GCU/late-load mem appears).
        while not stop.is_set():
            m = await asyncio.to_thread(_mem_now)
            if m is not None:
                peak[0] = max(peak[0], m)
            try:
                await asyncio.wait_for(stop.wait(), timeout=0.25)
            except asyncio.TimeoutError:
                pass

    sampler_task = asyncio.ensure_future(_sampler())
    t0 = time.perf_counter()
    await asyncio.gather(*[_one(i) for i in range(requests)])
    wall = time.perf_counter() - t0
    stop.set()
    try:
        await sampler_task
    except Exception:  # noqa: BLE001 - sampling is best-effort
        pass

    ok_s = [s for s in samples if s["ok"]]
    lat = [s["latency_ms"] for s in ok_s]
    ttfts = [s["ttft_ms"] for s in ok_s if s["ttft_ms"] is not None]
    total_tokens = sum(s["tokens"] for s in ok_s)
    total_prompt = sum(s["prompt_tokens"] for s in ok_s)

    pp: list[float] = []   # prefill tok/s
    tg: list[float] = []   # decode tok/s
    tpot: list[float] = []  # ms per output token
    for s in ok_s:
        t, n, pt = s["ttft_ms"], s["tokens"], s["prompt_tokens"]
        if t and t > 0 and pt:
            pp.append(pt / (t / 1000.0))
        gen_ms = (s["latency_ms"] - t) if t is not None else None
        if gen_ms and gen_ms > 0 and n and n > 1:
            tg.append((n - 1) / (gen_ms / 1000.0))
            tpot.append(gen_ms / (n - 1))

    dname = None
    try:
        from infermesh.core.devices import enumerate_devices
        for _d in enumerate_devices():
            if _d.get("vendor") == dev["vendor"]:
                dname = _d.get("name"); break
    except Exception:
        pass
    return {
        "model": model_id,
        "device": dev["device"],
        "vendor": dev["vendor"],
        "device_name": dname,
        "mode": mode,
        "requests": requests,
        "concurrency": concurrency,
        "max_tokens": max_tokens,
        "succeeded": len(ok_s),
        "failed": len(samples) - len(ok_s),
        "wall_time_s": round(wall, 3),
        "requests_per_sec": round(len(ok_s) / wall, 2) if wall > 0 else 0.0,
        "output_tokens_per_sec": round(total_tokens / wall, 1) if wall > 0 else 0.0,
        "total_output_tokens": total_tokens,
        "total_prompt_tokens": total_prompt,
        "peak_mem_mb": (peak[0] or None),
        "latency_ms": _stats(lat),
        "ttft_ms": _stats(ttfts),
        "tpot_ms": _stats(tpot),
        "pp_tps": {"mean": round(mean(pp), 1) if pp else 0.0,
                   "max": round(max(pp), 1) if pp else 0.0},
        "tg_tps": {"mean": round(mean(tg), 1) if tg else 0.0,
                   "max": round(max(tg), 1) if tg else 0.0},
    }

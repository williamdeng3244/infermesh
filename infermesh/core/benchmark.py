# SPDX-License-Identifier: Apache-2.0
"""Benchmark runner — fire concurrent streaming completions at a pooled model and
aggregate latency / TTFT / throughput.

Backend-agnostic: it drives the model through ``pool.acquire`` + ``chat_stream``,
so it works identically against the mock backend or a real vLLM GPU model. Imports
no vendor SDK.
"""

from __future__ import annotations

import asyncio
import time
from statistics import mean
from typing import Optional

from infermesh.api.adapters.base import InternalMessage, InternalRequest

DEFAULT_PROMPT = "Write one concise sentence about distributed systems."


def _pct(values: list[float], p: float) -> float:
    """Nearest-rank percentile of a pre-sorted list."""
    if not values:
        return 0.0
    idx = min(len(values) - 1, max(0, int(round((p / 100.0) * (len(values) - 1)))))
    return values[idx]


async def run_benchmark(
    pool,
    model_id: str,
    *,
    requests: int = 20,
    concurrency: int = 4,
    max_tokens: int = 64,
    prompt: str = DEFAULT_PROMPT,
) -> dict:
    """Fire ``requests`` streaming completions (at most ``concurrency`` at once)
    and return aggregate latency / TTFT / throughput statistics."""
    requests = max(1, requests)
    sem = asyncio.Semaphore(max(1, concurrency))
    samples: list[dict] = []

    async def _one() -> None:
        async with sem:
            req = InternalRequest(
                messages=[InternalMessage(role="user", content=prompt)],
                max_tokens=max_tokens,
                stream=True,
            )
            start = time.perf_counter()
            ttft: Optional[float] = None
            tokens = 0
            ok = True
            try:
                async with pool.acquire(model_id) as backend:
                    async for chunk in backend.chat_stream(req):
                        if ttft is None and (chunk.text or chunk.reasoning_content):
                            ttft = (time.perf_counter() - start) * 1000.0
                        if chunk.completion_tokens:
                            tokens = chunk.completion_tokens
            except Exception:  # noqa: BLE001 - a failed request is itself a data point
                ok = False
            samples.append({
                "latency_ms": (time.perf_counter() - start) * 1000.0,
                "ttft_ms": ttft,
                "tokens": tokens,
                "ok": ok,
            })

    t0 = time.perf_counter()
    await asyncio.gather(*[_one() for _ in range(requests)])
    wall = time.perf_counter() - t0

    ok_samples = [s for s in samples if s["ok"]]
    lat = sorted(s["latency_ms"] for s in ok_samples)
    ttfts = sorted(s["ttft_ms"] for s in ok_samples if s["ttft_ms"] is not None)
    total_tokens = sum(s["tokens"] for s in ok_samples)

    return {
        "model": model_id,
        "requests": requests,
        "concurrency": concurrency,
        "max_tokens": max_tokens,
        "succeeded": len(ok_samples),
        "failed": len(samples) - len(ok_samples),
        "wall_time_s": round(wall, 3),
        "requests_per_sec": round(len(ok_samples) / wall, 2) if wall > 0 else 0.0,
        "output_tokens_per_sec": round(total_tokens / wall, 1) if wall > 0 else 0.0,
        "total_output_tokens": total_tokens,
        "latency_ms": {
            "mean": round(mean(lat), 1) if lat else 0.0,
            "p50": round(_pct(lat, 50), 1),
            "p90": round(_pct(lat, 90), 1),
            "p99": round(_pct(lat, 99), 1),
            "min": round(lat[0], 1) if lat else 0.0,
            "max": round(lat[-1], 1) if lat else 0.0,
        },
        "ttft_ms": {
            "mean": round(mean(ttfts), 1) if ttfts else 0.0,
            "p50": round(_pct(ttfts, 50), 1),
            "p90": round(_pct(ttfts, 90), 1),
        },
    }

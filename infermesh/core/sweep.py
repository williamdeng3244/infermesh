# SPDX-License-Identifier: Apache-2.0
"""Concurrency sweep — the throughput–latency frontier measurement.

For each level ``k`` in ``levels``, keep exactly ``k`` requests in flight
(closed loop: ``k`` workers that re-issue immediately) for ``window_s``
seconds, recording per-request TTFT and the full inter-token-latency (ITL)
sequence. Each level produces a *child* result shaped like a
``run_benchmark`` result (so it records/publishes through the same path,
appearing in the Explorer as a normal run with ``batch_size = k``) plus
distribution fields (``percentiles`` / ``cv_itl`` / ``n_requests``). The
*parent* aggregates the frontier array ``[{concurrency, throughput,
p99_ttft_s}, ...]`` that the capacity view plots.

Goodput is intentionally NOT stored: the read-side API computes it against
the *current* ``slo_p99_ttft_s`` setting, so retuning the SLO reprices
history for free. Control-plane pure: asyncio + stdlib only.
"""

from __future__ import annotations

import asyncio
import time
from statistics import mean
from typing import Callable, Optional

from infermesh.api.adapters.base import InternalMessage, InternalRequest
from infermesh.core import derive
from infermesh.core.benchmark import DEFAULT_PROMPT, _stats

DEFAULT_LEVELS = (1, 2, 4, 8, 16, 32)


def _pcts(values_ms: list[float]) -> Optional[dict]:
    """p50/p90/p99/p999 (ms) via linear interpolation; None when empty."""
    if not values_ms:
        return None
    return {
        "p50": round(derive.percentile(values_ms, 0.50), 2),
        "p90": round(derive.percentile(values_ms, 0.90), 2),
        "p99": round(derive.percentile(values_ms, 0.99), 2),
        "p999": round(derive.percentile(values_ms, 0.999), 2),
    }


async def _run_level(pool, model_id: str, *, k: int, window_s: float,
                     max_tokens: int, prompt: str,
                     should_stop: Optional[Callable[[], bool]],
                     dev: dict) -> dict:
    """One sweep level: k closed-loop workers for window_s seconds."""
    samples: list[dict] = []
    itl_all: list[float] = []
    t0 = time.perf_counter()
    deadline = t0 + window_s
    seq = 0

    async def _worker(worker_idx: int) -> None:
        nonlocal seq
        while time.perf_counter() < deadline:
            if should_stop and should_stop():
                return
            seq += 1
            # unique leading text per request: no prefix sharing, like mode=different
            req = InternalRequest(
                messages=[InternalMessage(role="user",
                                          content=f"[sweep {k}:{worker_idx}:{seq}] {prompt}")],
                max_tokens=max_tokens,
                stream=True,
            )
            start = time.perf_counter()
            ttft: Optional[float] = None
            last_chunk: Optional[float] = None
            itl: list[float] = []
            comp = 0
            prompt_toks = 0
            ok = True
            try:
                async with pool.acquire(model_id) as backend:
                    if dev.get("device") is None:
                        try:
                            _e = backend.stats().extra or {}
                            dev["device"], dev["vendor"] = _e.get("device"), _e.get("vendor")
                        except Exception:  # noqa: BLE001
                            pass
                    async for chunk in backend.chat_stream(req):
                        now = time.perf_counter()
                        if chunk.text or chunk.reasoning_content:
                            if ttft is None:
                                ttft = (now - start) * 1000.0
                            elif last_chunk is not None:
                                itl.append((now - last_chunk) * 1000.0)
                            last_chunk = now
                        if chunk.completion_tokens:
                            comp = chunk.completion_tokens
                        if chunk.prompt_tokens:
                            prompt_toks = chunk.prompt_tokens
            except Exception:  # noqa: BLE001 - a failed request is a data point
                ok = False
            samples.append({
                "latency_ms": (time.perf_counter() - start) * 1000.0,
                "ttft_ms": ttft, "tokens": comp, "prompt_tokens": prompt_toks,
                "ok": ok,
            })
            if ok:
                itl_all.extend(itl)

    await asyncio.gather(*[_worker(i) for i in range(max(1, k))])
    elapsed = max(1e-6, time.perf_counter() - t0)

    ok_s = [s for s in samples if s["ok"]]
    lat = [s["latency_ms"] for s in ok_s]
    ttfts = [s["ttft_ms"] for s in ok_s if s["ttft_ms"] is not None]
    total_tokens = sum(s["tokens"] for s in ok_s)
    total_prompt = sum(s["prompt_tokens"] for s in ok_s)
    pp: list[float] = []
    tg: list[float] = []
    tpot: list[float] = []
    for s in ok_s:
        t, n, pt = s["ttft_ms"], s["tokens"], s["prompt_tokens"]
        if t and t > 0 and pt:
            pp.append(pt / (t / 1000.0))
        gen_ms = (s["latency_ms"] - t) if t is not None else None
        if gen_ms and gen_ms > 0 and n and n > 1:
            tg.append((n - 1) / (gen_ms / 1000.0))
            tpot.append(gen_ms / (n - 1))

    return {
        # --- run_benchmark-compatible shape (records via the same path) ---
        "model": model_id,
        "device": dev.get("device"), "vendor": dev.get("vendor"),
        "device_name": None,
        "mode": "concurrency_sweep",
        "requests": len(samples), "concurrency": k, "max_tokens": max_tokens,
        "succeeded": len(ok_s), "failed": len(samples) - len(ok_s),
        "wall_time_s": round(elapsed, 3),
        "requests_per_sec": round(len(ok_s) / elapsed, 2),
        "output_tokens_per_sec": round(total_tokens / elapsed, 1),
        "total_output_tokens": total_tokens,
        "total_prompt_tokens": total_prompt,
        "peak_mem_mb": None,
        "power_avg_w": None, "energy_j": None,
        "latency_ms": _stats(lat), "ttft_ms": _stats(ttfts),
        "tpot_ms": _stats(tpot),
        "pp_tps": {"mean": round(mean(pp), 1) if pp else 0.0,
                   "max": round(max(pp), 1) if pp else 0.0},
        "tg_tps": {"mean": round(mean(tg), 1) if tg else 0.0,
                   "max": round(max(tg), 1) if tg else 0.0},
        # --- distribution fields (schema v2) ---
        "percentiles": ({"ttft": _pcts(ttfts), "itl": _pcts(itl_all)}
                        if (ttfts or itl_all) else None),
        "cv_itl": (round(derive.cv(itl_all), 4) if len(itl_all) >= 2 else None),
        "n_requests": len(ok_s),
    }


async def run_concurrency_sweep(
    pool,
    model_id: str,
    *,
    levels=DEFAULT_LEVELS,
    window_s: float = 30.0,
    max_tokens: int = 64,
    prompt: str = DEFAULT_PROMPT,
    should_stop: Optional[Callable[[], bool]] = None,
    on_level: Optional[Callable[[int, int], None]] = None,
) -> dict:
    """Run the sweep; returns the parent aggregate with per-level children.

    ``on_level(done, total)`` fires after each level. ``should_stop`` is
    honoured between levels and at request boundaries inside a level
    (a cancelled sweep returns the levels finished so far)."""
    lv = sorted({max(1, int(k)) for k in (levels or DEFAULT_LEVELS)})
    children: list[dict] = []
    dev: dict = {"device": None, "vendor": None}
    for i, k in enumerate(lv):
        if should_stop and should_stop():
            break
        child = await _run_level(pool, model_id, k=k, window_s=float(window_s),
                                 max_tokens=max_tokens, prompt=prompt,
                                 should_stop=should_stop, dev=dev)
        children.append(child)
        if on_level:
            try:
                on_level(i + 1, len(lv))
            except Exception:  # noqa: BLE001 - progress is best-effort
                pass
    frontier = []
    for c in children:
        p99 = ((c.get("percentiles") or {}).get("ttft") or {}).get("p99")
        frontier.append({
            "concurrency": c["concurrency"],
            "throughput": c["output_tokens_per_sec"],
            "p99_ttft_s": round(p99 / 1000.0, 4) if p99 is not None else None,
        })
    return {
        "mode": "concurrency_sweep",
        "model": model_id,
        "levels": lv[:len(children)],
        "window_s": float(window_s),
        "device": dev.get("device"), "vendor": dev.get("vendor"),
        "frontier": frontier,
        "children": children,
    }

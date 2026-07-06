# SPDX-License-Identifier: Apache-2.0
"""Derived hardware-efficiency metrics — pure functions, no I/O, no state.

Formula-compatible with the console-redesign-v2 prototype JS (``pct`` /
``cvOf`` / ``mbu`` / ``mfu`` / ``tokJ`` / ``goodput``), so the dashboard and
the read-side analysis API agree to the digit. All functions return ``None``
when a denominator makes the metric undefined (the UI renders "—"), never a
fake zero.
"""

from __future__ import annotations

import math
from typing import Optional, Sequence

#: bytes per parameter by quantization (prototype BPP table + synonyms)
QUANT_BPP = {
    "fp16": 2.0, "bf16": 2.0,
    "int8": 1.0, "8bit": 1.0,
    "int4": 0.5, "4bit": 0.5,
    "fp32": 4.0,
}


def percentile(samples: Sequence[float], p: float) -> float:
    """Linear-interpolation percentile; ``p`` in [0, 1] (0.99 == p99).

    Matches the prototype's ``pct``: sort, index (n-1)·p, interpolate between
    the neighbouring order statistics. Raises ``ValueError`` on empty input."""
    if not samples:
        raise ValueError("percentile of empty sample set")
    s = sorted(samples)
    p = min(1.0, max(0.0, float(p)))
    i = (len(s) - 1) * p
    lo = math.floor(i)
    hi = math.ceil(i)
    return float(s[lo] + (s[hi] - s[lo]) * (i - lo))


def cv(samples: Sequence[float]) -> Optional[float]:
    """Coefficient of variation: population standard deviation / mean
    (prototype ``cvOf``). ``None`` for empty input or zero mean."""
    n = len(samples)
    if n == 0:
        return None
    m = sum(samples) / n
    if m == 0:
        return None
    var = sum((x - m) ** 2 for x in samples) / n
    return math.sqrt(var) / m


def weight_bytes(params: float, quant: Optional[str]) -> float:
    """Model weight footprint in bytes: parameter count × bytes/param for the
    quantization. Unknown/absent quant assumes fp16 (2 bytes)."""
    bpp = QUANT_BPP.get(str(quant or "").lower(), 2.0)
    return float(params) * bpp


def mbu(weight_bytes_: float, tg_tok_s: float, peak_bw_gbps: float) -> Optional[float]:
    """Memory-bandwidth utilization: every decoded token re-reads the weights,
    so achieved bytes/s is weights × tg; divide by peak bandwidth.

        mbu = weight_bytes × tg ÷ (peak_bw_gbps × 1e9)
    """
    if not peak_bw_gbps or peak_bw_gbps <= 0 or weight_bytes_ <= 0 or tg_tok_s < 0:
        return None
    return (weight_bytes_ * tg_tok_s) / (peak_bw_gbps * 1e9)


def mfu(params: float, pp_tok_s: float, peak_tflops: float) -> Optional[float]:
    """Model-FLOPs utilization on prefill: ~2 FLOPs per parameter per token.

        mfu = 2 × params × pp ÷ (peak_tflops × 1e12)
    """
    if not peak_tflops or peak_tflops <= 0 or params <= 0 or pp_tok_s < 0:
        return None
    return (2.0 * params * pp_tok_s) / (peak_tflops * 1e12)


def tokens_per_joule(tg_tok_s: float, power_w: float) -> Optional[float]:
    """tok/s ÷ J/s == tokens per joule. ``None`` when power is unknown/zero."""
    if not power_w or power_w <= 0 or tg_tok_s < 0:
        return None
    return tg_tok_s / power_w


def goodput(frontier_points: Sequence[dict], slo_p99_s: float) -> tuple[float, Optional[int]]:
    """Highest throughput among sweep levels whose p99 TTFT meets the SLO.

    ``frontier_points``: ``[{"concurrency", "throughput", "p99_ttft_s"}, ...]``
    (one per concurrency level). Returns ``(goodput, concurrency)``;
    ``(0.0, None)`` when no level satisfies the SLO — the prototype's
    "no concurrency satisfies this SLO (prefill-bound)" empty state."""
    best_thr = 0.0
    best_k: Optional[int] = None
    for pt in frontier_points:
        p99 = pt.get("p99_ttft_s")
        thr = pt.get("throughput")
        if p99 is None or thr is None:
            continue
        if p99 <= slo_p99_s and thr > best_thr:
            best_thr = float(thr)
            best_k = int(pt.get("concurrency") or 0) or None
    return best_thr, best_k

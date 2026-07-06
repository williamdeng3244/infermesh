# SPDX-License-Identifier: Apache-2.0
"""Read-side hardware-efficiency analysis over the community store.

Everything here is *derived on read*: efficiency (MBU / MFU / tok/J),
throughput–latency frontiers with goodput against the current SLO, multi-card
scaling, per-driver timelines, and run-vs-run comparison. Nothing is written
back — retuning a spec or the SLO reprices history for free.

All entry points are synchronous (called via ``asyncio.to_thread`` from the
routes) and memoized for 5 seconds per argument tuple, so a dashboard poll
doesn't hammer SQLite. Control-plane pure: community + specs + derive only.

Parameter counts for MBU/MFU come from the model name ("Qwen2.5-7B-Instruct"
→ 7e9): the control plane has no tokenizer or config reader for remote rows.
Unparseable names yield null efficiency metrics, never a guess.
"""

from __future__ import annotations

import re
import time
from statistics import median
from typing import Optional

from infermesh.core import community, derive, specs

_TTL_S = 5.0
_cache: dict = {}

# metric name -> (community column, higher_is_better)
TIMELINE_METRICS = {
    "tg": ("tg_tps", True),
    "pp": ("pp_tps", True),
    "ttft": ("ttft_ms", False),
    "tpot": ("tpot_ms", False),
    "throughput": ("total_throughput", True),
}

_HIGHER_BETTER = {"pp_tps", "tg_tps", "total_throughput"}
_LOWER_BETTER = {"ttft_ms", "tpot_ms", "e2e_latency_s", "peak_mem_gb",
                 "power_avg_w", "energy_j", "cv_itl"}
_COMPARE_FIELDS = tuple(list(_HIGHER_BETTER) + list(_LOWER_BETTER))


def _cached(key: tuple, fn):
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and hit[0] > now:
        return hit[1]
    val = fn()
    _cache[key] = (now + _TTL_S, val)
    # opportunistic sweep so the dict can't grow unboundedly
    if len(_cache) > 256:
        for k in [k for k, (exp, _) in _cache.items() if exp <= now]:
            _cache.pop(k, None)
    return val


def cache_clear() -> None:
    _cache.clear()


def params_from_model(model: Optional[str]) -> Optional[float]:
    """Parameter count parsed from the model name: '…-7B…' → 7e9, '0.5B' →
    5e8, '70b' → 7e10. None when the name carries no size."""
    if not model:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*[bB](?![a-zA-Z0-9])", str(model))
    return float(m.group(1)) * 1e9 if m else None


def _chip_spec(chip: str) -> Optional[dict]:
    hit = specs.resolve(chip)
    return hit[1] if hit else None


def _chip_key(chip: str) -> Optional[str]:
    hit = specs.resolve(chip)
    return hit[0] if hit else None


# ------------------------------- efficiency ------------------------------- #

def efficiency() -> dict:
    """Per chip: MBU / MFU / tokens-per-joule / soak delta, from that chip's
    most recent run (spec denominators from the registry)."""
    return _cached(("efficiency",), _efficiency)


def _efficiency() -> dict:
    rows = community.query_runs(sort="recent", limit=2000)
    chips: dict[str, dict] = {}
    for r in rows:
        chip = r.get("chip") or "—"
        bucket = chips.setdefault(chip, {"runs": []})
        bucket["runs"].append(r)
    out = []
    for chip, bucket in chips.items():
        runs = bucket["runs"]                      # newest first (sort=recent)
        latest = runs[0]
        spec = _chip_spec(chip)
        params = params_from_model(latest.get("model"))
        quant = latest.get("quant")
        tg = latest.get("tg_tps")
        pp = latest.get("pp_tps")
        mbu = mfu = None
        if spec and params and tg is not None:
            mbu = derive.mbu(derive.weight_bytes(params, quant), tg,
                             spec.get("peak_bw_gbps"))
        if spec and params and pp is not None:
            mfu = derive.mfu(params, pp, spec.get("peak_tflops_fp16"))
        power = latest.get("power_avg_w")
        basis = "measured"
        if not power and spec:
            power, basis = spec.get("tdp_w"), "tdp"
        tok_j = derive.tokens_per_joule(tg, power) if (tg is not None and power) else None
        # soak delta: newest run's tg vs the median of its predecessors for the
        # same model+quant — long-run drift; null under 3 comparable runs
        same = [x.get("tg_tps") for x in runs
                if x.get("model") == latest.get("model")
                and x.get("quant") == quant and x.get("tg_tps") is not None]
        soak = None
        if len(same) >= 3:
            base = median(same[1:])
            if base:
                soak = round((same[0] - base) / base * 100.0, 2)
        out.append({
            "chip": chip, "spec_key": _chip_key(chip),
            "model": latest.get("model"), "quant": quant,
            "tg_tps": tg, "pp_tps": pp,
            "mbu": round(mbu, 4) if mbu is not None else None,
            "mfu": round(mfu, 4) if mfu is not None else None,
            "tok_j": round(tok_j, 4) if tok_j is not None else None,
            "tok_j_basis": basis if tok_j is not None else None,
            "soak_delta_pct": soak,
            "n_runs": len(runs),
        })
    out.sort(key=lambda x: x["chip"])
    return {"chips": out}


# -------------------------------- frontier -------------------------------- #

def frontier(chips: str = "", slo_p99_ttft_s: float = 2.0) -> dict:
    """Per chip: sweep points (one per concurrency level, latest wins) and
    goodput against the given SLO. Throughput basis: total_throughput
    (prompt+output tokens/s), the system token rate the store carries."""
    return _cached(("frontier", chips, round(float(slo_p99_ttft_s), 4)),
                   lambda: _frontier(chips, float(slo_p99_ttft_s)))


def _frontier(chips: str, slo: float) -> dict:
    want = {c.strip() for c in chips.split(",") if c.strip()} if chips else None
    rows = community.query_runs(sort="recent", limit=2000)
    per_chip: dict[str, dict[int, dict]] = {}
    for r in rows:
        p99 = (((r.get("percentiles") or {}).get("ttft")) or {}).get("p99")
        k = r.get("batch_size")
        if p99 is None or not k:
            continue  # not a sweep child
        chip = r.get("chip") or "—"
        if want and chip not in want:
            continue
        levels = per_chip.setdefault(chip, {})
        if k not in levels:  # rows are newest-first: first hit per level wins
            levels[k] = {"concurrency": int(k),
                         "throughput": r.get("total_throughput"),
                         "p99_ttft_s": round(p99 / 1000.0, 4),
                         "cv_itl": r.get("cv_itl"),
                         "n_requests": r.get("n_requests"),
                         "percentiles": r.get("percentiles"),
                         "run_id": r.get("run_id")}
    out = []
    for chip, levels in per_chip.items():
        points = [levels[k] for k in sorted(levels)]
        g, k = derive.goodput(points, slo)
        out.append({"chip": chip, "points": points,
                    "goodput": g or None, "goodput_concurrency": k,
                    "slo_p99_ttft_s": slo,
                    "slo_met": k is not None})
    out.sort(key=lambda x: x["chip"])
    return {"series": out, "slo_p99_ttft_s": slo}


# -------------------------------- scaling --------------------------------- #

def scaling(model: str = "", quant: str = "") -> dict:
    """Speedup / parallel efficiency grouped by device_count, with the
    1-device median as baseline."""
    return _cached(("scaling", model, quant), lambda: _scaling(model, quant))


def _scaling(model: str, quant: str) -> dict:
    rows = community.query_runs(model=model, quant=quant, sort="recent", limit=2000)
    groups: dict[int, list[float]] = {}
    for r in rows:
        n = r.get("device_count") or 1
        thr = r.get("total_throughput")
        if thr is None:
            continue
        groups.setdefault(int(n), []).append(float(thr))
    if not groups:
        return {"points": [], "baseline_median": None, "model": model, "quant": quant}
    base = median(groups[1]) if groups.get(1) else None
    points = []
    for n in sorted(groups):
        med = median(groups[n])
        speedup = (med / base) if base else None
        points.append({
            "device_count": n,
            "median_throughput": round(med, 1),
            "n_runs": len(groups[n]),
            "speedup": round(speedup, 3) if speedup is not None else None,
            "efficiency": round(speedup / n, 3) if speedup is not None else None,
        })
    return {"points": points,
            "baseline_median": round(base, 1) if base else None,
            "model": model, "quant": quant}


# -------------------------------- timeline -------------------------------- #

def timeline(chip: str = "", metric: str = "tg") -> dict:
    """Median of ``metric`` grouped by driver_version (ordered by when each
    driver first appeared), adjacent steps flagged as regressions when they
    move >1% in the bad direction."""
    return _cached(("timeline", chip, metric), lambda: _timeline(chip, metric))


def _timeline(chip: str, metric: str) -> dict:
    col, higher_better = TIMELINE_METRICS.get(metric, TIMELINE_METRICS["tg"])
    rows = community.query_runs(chip=chip, sort="oldest", limit=5000)
    groups: dict[str, dict] = {}
    for r in rows:
        drv = r.get("driver_version")
        val = r.get(col)
        if not drv or val is None:
            continue
        g = groups.setdefault(drv, {"values": [], "first_seen": r.get("created_at")})
        g["values"].append(float(val))
    ordered = sorted(groups.items(), key=lambda kv: kv[1]["first_seen"] or 0)
    points = []
    prev_med = None
    for drv, g in ordered:
        med = median(g["values"])
        delta = None
        regression = False
        if prev_med:
            delta = round((med - prev_med) / prev_med * 100.0, 2)
            bad = -delta if higher_better else delta
            regression = bad > 1.0  # flags Δ < −1% throughput (or > +1% latency)
        points.append({"driver_version": drv, "median": round(med, 2),
                       "n": len(g["values"]), "first_seen": g["first_seen"],
                       "delta_pct": delta, "regression": regression})
        prev_med = med
    return {"chip": chip, "metric": metric, "column": col,
            "higher_is_better": higher_better, "points": points}


# --------------------------------- compare -------------------------------- #

def compare(a_id: str, b_id: str, threshold_pct: float = 2.0) -> Optional[dict]:
    """Both runs, per-metric Δ% (b vs a), verdicts at ±threshold. None when
    either run id is unknown. Not cached: run ids are immutable rows."""
    a = community.get(a_id)
    b = community.get(b_id)
    if a is None or b is None:
        return None
    deltas = {}
    for f in _COMPARE_FIELDS:
        va, vb = a.get(f), b.get(f)
        entry: dict = {"a": va, "b": vb, "delta_pct": None, "verdict": None}
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)) and va:
            d = (vb - va) / abs(va) * 100.0
            entry["delta_pct"] = round(d, 2)
            if abs(d) <= threshold_pct:
                entry["verdict"] = "same"
            else:
                improved = (d > 0) if f in _HIGHER_BETTER else (d < 0)
                entry["verdict"] = "better" if improved else "worse"
        deltas[f] = entry
    return {"a": a, "b": b, "deltas": deltas, "threshold_pct": threshold_pct}

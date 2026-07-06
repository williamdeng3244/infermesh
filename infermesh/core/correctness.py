# SPDX-License-Identifier: Apache-2.0
"""Numeric-correctness harness — does this backend decode the same tokens as
the reference implementation?

A *reference set* is an offline, pre-generated fp16 greedy decode of the fixed
prompt set (``fixtures/correctness/prompts.jsonl``): for each prompt, the
first N token ids and optionally the top-20 logprobs per step
(``fixtures/correctness/ref/<model_id>.jsonl``, written by
``scripts/gen_reference.py`` on a CUDA or plain-CPU machine — NEVER on a GCU
node, where torch_gcu hijacks the torch module at import time).

The backend under test exposes ids via the optional
``InferenceBackend.greedy_decode`` capability; the control plane has no
tokenizer, so it only ever compares integer sequences. Verdicts:
match ≥ pass_t → "pass", ≥ warn_t → "warn", else "fail".
"""

from __future__ import annotations

import json
import math
import os
from pathlib import Path
from statistics import mean
from typing import Optional

PASS_T = 0.99
WARN_T = 0.95

_DEFAULT_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "correctness"


def fixtures_dir() -> Path:
    """Prompt/reference base dir (env INFERMESH_CORRECTNESS_DIR overrides —
    installed wheels don't carry the repo fixtures)."""
    env = os.environ.get("INFERMESH_CORRECTNESS_DIR")
    return Path(env) if env else _DEFAULT_DIR


def load_prompts(base_dir: Optional[Path] = None) -> list[dict]:
    path = (base_dir or fixtures_dir()) / "prompts.jsonl"
    out: list[dict] = []
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if rec.get("id") and rec.get("prompt"):
                out.append(rec)
    except OSError:
        return []
    return out


def ref_path_for(model_id: str, base_dir: Optional[Path] = None) -> Path:
    safe = str(model_id).replace("/", "__")
    return (base_dir or fixtures_dir()) / "ref" / f"{safe}.jsonl"


def load_reference(model_id: str, base_dir: Optional[Path] = None) -> Optional[dict]:
    """{prompt_id: {"token_ids": [...], "top_logprobs": ...}, "_meta": {...}}
    or None when no reference set exists for this model."""
    path = ref_path_for(model_id, base_dir)
    if not path.exists():
        return None
    ref: dict = {"_meta": {}}
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            if "_meta" in rec:
                ref["_meta"] = rec["_meta"] or {}
            elif rec.get("id"):
                ref[rec["id"]] = {"token_ids": rec.get("token_ids") or [],
                                  "top_logprobs": rec.get("top_logprobs")}
    except (OSError, json.JSONDecodeError):
        return None
    return ref


def _match(ref_ids: list, got_ids: list) -> tuple[float, Optional[int]]:
    """Token-level agreement over the compared span + first divergence index."""
    n = min(len(ref_ids), len(got_ids))
    if n == 0:
        return 0.0, 0
    eq = 0
    div: Optional[int] = None
    for i in range(n):
        if int(ref_ids[i]) == int(got_ids[i]):
            eq += 1
        elif div is None:
            div = i
    return eq / n, div


def _mean_topk_kl(ref_tops, got_tops) -> Optional[float]:
    """Approximate mean KL(ref‖test) over the reference top-k support.

    The ref top-k logprobs are renormalized into a distribution; a token the
    test never ranked is floored at logprob −20. Null when either side lacks
    logits."""
    if not ref_tops or not got_tops:
        return None
    kls: list[float] = []
    for r, g in zip(ref_tops, got_tops):
        gmap = {int(t): float(lp) for t, lp in g}
        rp = [(int(t), math.exp(float(lp))) for t, lp in r]
        z = sum(p for _, p in rp) or 1.0
        kl = 0.0
        for t, p in rp:
            p /= z
            kl += p * (math.log(max(p, 1e-12)) - gmap.get(t, -20.0))
        kls.append(kl)
    return mean(kls) if kls else None


def grade(match_rate: float, pass_t: float = PASS_T, warn_t: float = WARN_T) -> str:
    if match_rate >= pass_t:
        return "pass"
    if match_rate >= warn_t:
        return "warn"
    return "fail"


async def evaluate_backend(backend, prompts: list[dict], reference: dict, *,
                           max_new_tokens: int = 128,
                           pass_t: float = PASS_T, warn_t: float = WARN_T) -> dict:
    """Greedy-decode every prompt on ``backend`` and compare to ``reference``."""
    per: list[dict] = []
    for p in prompts:
        ref = reference.get(p["id"])
        if not ref or not ref.get("token_ids"):
            continue
        out = await backend.greedy_decode(p["prompt"], max_new_tokens)
        if out is None:
            return {"error": "backend does not expose greedy token decode",
                    "grade": None}
        rate, div = _match(ref["token_ids"], out.get("token_ids") or [])
        kl = _mean_topk_kl(ref.get("top_logprobs"), out.get("top_logprobs"))
        per.append({"id": p["id"], "match": round(rate, 4),
                    "first_divergence": div,
                    "kl": round(kl, 6) if kl is not None else None})
    if not per:
        return {"error": "no overlap between the prompt set and the reference set",
                "grade": None}
    gm = round(mean(x["match"] for x in per), 4)
    divs = [x["first_divergence"] for x in per if x["first_divergence"] is not None]
    kls = [x["kl"] for x in per if x["kl"] is not None]
    return {
        "greedy_match": gm,
        "mean_kl": round(mean(kls), 6) if kls else None,
        "first_divergence": min(divs) if divs else None,
        "ref": (reference.get("_meta") or {}).get("ref") or "precomputed",
        "grade": grade(gm, pass_t, warn_t),
        "n_prompts": len(per),
        "per_prompt": per,
    }


async def run_correctness(pool, model_id: str, *, max_new_tokens: int = 128,
                          base_dir: Optional[Path] = None,
                          pass_t: float = PASS_T, warn_t: float = WARN_T) -> dict:
    """Pool-level entry: acquire the model, evaluate against its reference set."""
    prompts = load_prompts(base_dir)
    if not prompts:
        return {"error": "prompt set not found (fixtures/correctness/prompts.jsonl)",
                "grade": None}
    reference = load_reference(model_id, base_dir)
    if reference is None:
        return {"error": f"no reference set for '{model_id}' — generate one with "
                         "scripts/gen_reference.py on a CUDA/CPU machine "
                         "(never on a GCU node)",
                "grade": None}
    async with pool.acquire(model_id) as backend:
        return await evaluate_backend(backend, prompts, reference,
                                      max_new_tokens=max_new_tokens,
                                      pass_t=pass_t, warn_t=warn_t)

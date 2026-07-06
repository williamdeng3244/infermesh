#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Generate a numeric-correctness reference set (fp16 greedy decode).

Writes ``fixtures/correctness/ref/<model_id>.jsonl``: one meta line, then one
line per prompt with the first N greedily-decoded token ids and the top-20
logprobs per step. The correctness harness (core/correctness.py) compares a
backend under test against this file.

╔══════════════════════════════════════════════════════════════════════════╗
║  NEVER RUN THIS ON A GCU NODE. torch_gcu hijacks `import torch`, and CPU  ║
║  inference on such a box can hang the process. Generate references on a   ║
║  machine with CUDA (or a plain-CPU machine without torch_gcu installed),  ║
║  then copy the .jsonl file to the deployment.                             ║
╚══════════════════════════════════════════════════════════════════════════╝

Usage:
  # real reference (CUDA / plain-CPU machine):
  python scripts/gen_reference.py --backend transformers \
      --model-path /models/Qwen2.5-7B-Instruct --model-id Qwen2.5-7B-Instruct

  # demo reference for the mock backend (what CI exercises end-to-end):
  python scripts/gen_reference.py --backend mock --model-id echo-1
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from infermesh.core.correctness import load_prompts, ref_path_for  # noqa: E402


def _gen_mock(prompts: list[dict], n: int) -> list[dict]:
    from infermesh.backends.mock.mock_backend import _mock_token_ids
    return [{"id": p["id"], "token_ids": _mock_token_ids(p["prompt"], n),
             "top_logprobs": None} for p in prompts]


def _gen_transformers(prompts: list[dict], n: int, model_path: str, topk: int) -> list[dict]:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(model_path)
    model = AutoModelForCausalLM.from_pretrained(
        model_path, torch_dtype="float16",
        device_map="cuda" if torch.cuda.is_available() else "cpu")
    model.eval()
    out: list[dict] = []
    for p in prompts:
        toks = tokenizer(p["prompt"], return_tensors="pt").to(model.device)
        with torch.no_grad():
            gen = model.generate(**toks, do_sample=False, num_beams=1,
                                 max_new_tokens=n, output_scores=True,
                                 return_dict_in_generate=True)
        ids = gen.sequences[0][toks["input_ids"].shape[1]:].tolist()
        tops = []
        for sc in (gen.scores or []):
            lp = torch.log_softmax(sc[0].float(), dim=-1)
            v, ix = lp.topk(topk)
            tops.append([[int(i), round(float(x), 6)]
                         for i, x in zip(ix.tolist(), v.tolist())])
        out.append({"id": p["id"], "token_ids": [int(x) for x in ids],
                    "top_logprobs": tops or None})
        print(f"  {p['id']}: {len(ids)} tokens", file=sys.stderr)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", choices=("transformers", "mock"), default="transformers")
    ap.add_argument("--model-id", required=True,
                    help="pool model id — names the output file")
    ap.add_argument("--model-path", help="local checkpoint dir (transformers mode)")
    ap.add_argument("--max-new-tokens", type=int, default=128)
    ap.add_argument("--topk", type=int, default=20)
    ap.add_argument("--out", help="output path (default fixtures/correctness/ref/<id>.jsonl)")
    args = ap.parse_args()

    prompts = load_prompts()
    if not prompts:
        print("prompt set not found: fixtures/correctness/prompts.jsonl", file=sys.stderr)
        return 2

    if args.backend == "mock":
        rows = _gen_mock(prompts, args.max_new_tokens)
        ref_label = "mock-echo deterministic ids (demo)"
    else:
        if not args.model_path:
            print("--model-path is required for --backend transformers", file=sys.stderr)
            return 2
        rows = _gen_transformers(prompts, args.max_new_tokens, args.model_path, args.topk)
        ref_label = "fp16 greedy, transformers"

    out_path = Path(args.out) if args.out else ref_path_for(args.model_id)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as fh:
        fh.write(json.dumps({"_meta": {
            "ref": ref_label, "model_id": args.model_id,
            "max_new_tokens": args.max_new_tokens, "topk": args.topk,
            "generator": f"gen_reference.py on {platform.platform()}",
            "n_prompts": len(rows),
        }}) + "\n")
        for row in rows:
            fh.write(json.dumps(row) + "\n")
    print(f"wrote {out_path} ({len(rows)} prompts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

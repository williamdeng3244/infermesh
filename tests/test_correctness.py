# SPDX-License-Identifier: Apache-2.0
"""Numeric-correctness harness (Milestone 2, commit 7): grading of a perfect
decoder vs one that drifts at token 10, KL, missing-reference handling, and
the correctness=true bench-job flag end-to-end on the shipped mock reference."""

import math
import time

from infermesh.backends.mock.mock_backend import MockEchoBackend, _mock_token_ids
from infermesh.core import community, correctness
from infermesh.core.backend import ModelSpec


def _prompts(n=3):
    return [{"id": f"t{i:02d}", "prompt": f"prompt number {i}"} for i in range(n)]


def _reference(prompts, n_tokens=128):
    ref = {"_meta": {"ref": "unit-fixture"}}
    for p in prompts:
        ref[p["id"]] = {"token_ids": _mock_token_ids(p["prompt"], n_tokens),
                        "top_logprobs": None}
    return ref


class _DriftAt10(MockEchoBackend):
    """Decodes the reference ids faithfully until index 10, then drifts."""

    async def greedy_decode(self, prompt, max_new_tokens=128):
        ids = _mock_token_ids(prompt, max_new_tokens)
        return {"token_ids": ids[:10] + [(x + 1) % 32000 for x in ids[10:]],
                "top_logprobs": None}


class _ThreeWrong(MockEchoBackend):
    """Exactly 3 of 128 tokens wrong -> 125/128 ≈ 0.9766 -> warn band."""

    async def greedy_decode(self, prompt, max_new_tokens=128):
        ids = _mock_token_ids(prompt, max_new_tokens)
        for i in (40, 80, 120):
            ids[i] = (ids[i] + 7) % 32000
        return {"token_ids": ids, "top_logprobs": None}


async def test_perfect_decoder_passes():
    b = MockEchoBackend()
    await b.load(ModelSpec(model_id="m", source="/tmp/m"))
    prompts = _prompts()
    r = await correctness.evaluate_backend(b, prompts, _reference(prompts))
    assert r["grade"] == "pass"
    assert r["greedy_match"] == 1.0
    assert r["first_divergence"] is None
    assert r["n_prompts"] == 3 and r["mean_kl"] is None


async def test_drift_at_token_10_fails_with_divergence_index():
    b = _DriftAt10()
    await b.load(ModelSpec(model_id="m", source="/tmp/m"))
    prompts = _prompts()
    r = await correctness.evaluate_backend(b, prompts, _reference(prompts))
    assert r["grade"] == "fail"
    assert r["first_divergence"] == 10
    assert abs(r["greedy_match"] - 10 / 128) < 1e-3


async def test_three_wrong_tokens_is_warn():
    b = _ThreeWrong()
    await b.load(ModelSpec(model_id="m", source="/tmp/m"))
    prompts = _prompts()
    r = await correctness.evaluate_backend(b, prompts, _reference(prompts))
    assert r["grade"] == "warn"
    assert 0.95 <= r["greedy_match"] < 0.99


def test_grade_thresholds():
    assert correctness.grade(1.0) == "pass"
    assert correctness.grade(0.99) == "pass"     # boundary inclusive
    assert correctness.grade(0.9899) == "warn"
    assert correctness.grade(0.95) == "warn"
    assert correctness.grade(0.9499) == "fail"


def test_mean_topk_kl():
    tops = [[[1, math.log(0.6)], [2, math.log(0.3)], [3, math.log(0.1)]]]
    same = correctness._mean_topk_kl(tops, tops)
    assert same is not None and abs(same) < 1e-9  # identical dists -> KL 0
    shifted = [[[1, math.log(0.1)], [2, math.log(0.3)], [3, math.log(0.6)]]]
    assert correctness._mean_topk_kl(tops, shifted) > 0.1
    assert correctness._mean_topk_kl(None, tops) is None
    assert correctness._mean_topk_kl(tops, None) is None


async def test_unsupported_backend_reports_error():
    class _NoDecode(MockEchoBackend):
        async def greedy_decode(self, prompt, max_new_tokens=128):
            return None

    b = _NoDecode()
    await b.load(ModelSpec(model_id="m", source="/tmp/m"))
    prompts = _prompts()
    r = await correctness.evaluate_backend(b, prompts, _reference(prompts))
    assert r["grade"] is None and "greedy token decode" in r["error"]


async def test_missing_reference_points_at_generator(mock_pool):
    r = await correctness.run_correctness(mock_pool, "no-such-model")
    assert r["grade"] is None
    assert "gen_reference.py" in r["error"]


def test_shipped_prompt_set_and_mock_reference():
    prompts = correctness.load_prompts()
    assert len(prompts) == 20
    tags = {t for p in prompts for t in p.get("tags", [])}
    assert {"multilingual", "code", "math", "long-dependency"} <= tags
    ref = correctness.load_reference("echo-1")
    assert ref is not None
    assert sum(1 for k in ref if k != "_meta") == 20
    assert len(ref["p01"]["token_ids"]) == 128


def _wait_terminal(client, job_id: str, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    d: dict = {}
    while time.time() < deadline:
        d = client.get(f"/api/bench/jobs/{job_id}").json()
        if d["state"] in ("done", "failed", "cancelled"):
            return d
        time.sleep(0.05)
    raise AssertionError(f"job never reached a terminal state: {d}")


def test_bench_job_with_correctness_flag(jobs_client):
    r = jobs_client.post("/api/bench/jobs", json={
        "model": "echo-1", "requests": 2, "concurrency": 1, "max_tokens": 8,
        "correctness": True})
    d = _wait_terminal(jobs_client, r.json()["job_id"])
    assert d["state"] == "done", d["error"]
    c = d["result"]["correctness"]
    assert c["grade"] == "pass" and c["greedy_match"] == 1.0
    assert c["n_prompts"] == 20
    # the community row carries the verdict (without per-prompt detail)
    rows = [x for x in community.query_runs() if x.get("correctness")]
    assert rows and rows[0]["correctness"]["grade"] == "pass"
    assert "per_prompt" not in rows[0]["correctness"]

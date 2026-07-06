# SPDX-License-Identifier: Apache-2.0
"""core/derive.py (Milestone 2, commit 3): fixed-vector assertions to 4 decimal
places, matching the console-redesign-v2 prototype JS formulas."""

import pytest

from infermesh.core import derive

A4 = 1e-4  # "to 4 decimal places"


def test_percentile_linear_interpolation():
    s = [1.0, 2.0, 3.0, 4.0]
    assert derive.percentile(s, 0.0) == pytest.approx(1.0, abs=A4)
    assert derive.percentile(s, 1.0) == pytest.approx(4.0, abs=A4)
    assert derive.percentile(s, 0.5) == pytest.approx(2.5, abs=A4)      # (n-1)p = 1.5
    assert derive.percentile(s, 0.99) == pytest.approx(3.9700, abs=A4)  # 3 + 0.97
    assert derive.percentile([7.0], 0.9) == pytest.approx(7.0, abs=A4)
    assert derive.percentile([3.0, 1.0, 2.0], 0.5) == pytest.approx(2.0, abs=A4)  # sorts
    assert derive.percentile(s, 1.7) == pytest.approx(4.0, abs=A4)      # p clamped
    with pytest.raises(ValueError):
        derive.percentile([], 0.5)


def test_cv_population_stddev_over_mean():
    # mean 5, population variance 32/8 = 4, sd 2 -> cv 0.4
    assert derive.cv([2, 4, 4, 4, 5, 5, 7, 9]) == pytest.approx(0.4000, abs=A4)
    assert derive.cv([5, 5, 5]) == pytest.approx(0.0, abs=A4)
    assert derive.cv([]) is None
    assert derive.cv([1, -1]) is None  # zero mean -> undefined


def test_weight_bytes_by_quant():
    assert derive.weight_bytes(7e9, "fp16") == pytest.approx(14e9)
    assert derive.weight_bytes(7e9, "int8") == pytest.approx(7e9)
    assert derive.weight_bytes(7e9, "int4") == pytest.approx(3.5e9)
    assert derive.weight_bytes(7e9, "4bit") == pytest.approx(3.5e9)   # prototype key
    assert derive.weight_bytes(7e9, "fp32") == pytest.approx(28e9)
    assert derive.weight_bytes(7e9, None) == pytest.approx(14e9)      # default fp16
    assert derive.weight_bytes(7e9, "weird") == pytest.approx(14e9)


def test_mbu_formula():
    # 16e9 bytes × 10 tok/s ÷ (800 GB/s × 1e9) = 0.2 exactly
    assert derive.mbu(16e9, 10.0, 800.0) == pytest.approx(0.2000, abs=A4)
    # 7B fp16 on S60 at 12.1 tok/s vs 800 GB/s: 14×12.1/800
    assert derive.mbu(derive.weight_bytes(7e9, "fp16"), 12.1, 800.0) == \
        pytest.approx(0.211750, abs=A4)
    assert derive.mbu(16e9, 10.0, 0) is None
    assert derive.mbu(0, 10.0, 800.0) is None


def test_mfu_formula():
    # 2 × 7e9 × 300 ÷ (150 TFLOPS × 1e12) = 0.028 exactly
    assert derive.mfu(7e9, 300.0, 150.0) == pytest.approx(0.0280, abs=A4)
    # A100: 2 × 7e9 × 5200 ÷ 312e12
    assert derive.mfu(7e9, 5200.0, 312.0) == pytest.approx(0.233333, abs=A4)
    assert derive.mfu(7e9, 300.0, 0) is None
    assert derive.mfu(0, 300.0, 150.0) is None


def test_tokens_per_joule():
    assert derive.tokens_per_joule(12.0, 300.0) == pytest.approx(0.0400, abs=A4)
    assert derive.tokens_per_joule(95.0, 400.0) == pytest.approx(0.2375, abs=A4)
    assert derive.tokens_per_joule(12.0, 0) is None
    assert derive.tokens_per_joule(12.0, None) is None


def test_goodput_picks_best_level_meeting_slo():
    pts = [
        {"concurrency": 1, "throughput": 100.0, "p99_ttft_s": 0.5},
        {"concurrency": 2, "throughput": 180.0, "p99_ttft_s": 0.9},
        {"concurrency": 4, "throughput": 260.0, "p99_ttft_s": 1.8},
        {"concurrency": 8, "throughput": 300.0, "p99_ttft_s": 3.2},
    ]
    assert derive.goodput(pts, 2.0) == (260.0, 4)
    assert derive.goodput(pts, 10.0) == (300.0, 8)
    assert derive.goodput(pts, 0.3) == (0.0, None)  # prefill-bound empty state
    assert derive.goodput([], 2.0) == (0.0, None)
    # points with missing fields are skipped, order does not matter
    assert derive.goodput([{"concurrency": 2}, pts[0]], 2.0) == (100.0, 1)

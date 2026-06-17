# SPDX-License-Identifier: Apache-2.0
"""Persist Metrics + Benchmark runs under ``~/.infermesh/history`` so past tests
survive a server restart.

Two append-only JSONL files: ``metrics.jsonl`` (one per request — feeds the live
chart and is reloaded on startup) and ``benchmarks.jsonl`` (one per benchmark run
— the "previous tests" history). Timestamps are epoch seconds (``t``), not a
human format. Appends are cheap (no rewrite on the hot path); files are trimmed
to a cap once at startup via :func:`truncate_on_startup`.
"""

from __future__ import annotations

import json
from pathlib import Path

from infermesh.core.settings import HOME_DIR

HISTORY_DIR = HOME_DIR / "history"
METRICS_FILE = HISTORY_DIR / "metrics.jsonl"
BENCH_FILE = HISTORY_DIR / "benchmarks.jsonl"

_METRICS_CAP = 5000
_BENCH_CAP = 500


def _append(path: Path, record: dict) -> None:
    try:
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        with open(path, "a") as fh:
            fh.write(json.dumps(record) + "\n")
    except OSError:
        pass  # history is best-effort; never break a request


def _tail(path: Path, limit: int) -> list[dict]:
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []
    out: list[dict] = []
    for line in lines[-limit:]:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def _truncate(path: Path, cap: int) -> None:
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return
    if len(lines) > cap:
        try:
            path.write_text("\n".join(lines[-cap:]) + "\n")
        except OSError:
            pass


def append_metric(record: dict) -> None:
    _append(METRICS_FILE, record)


def append_benchmark(record: dict) -> None:
    _append(BENCH_FILE, record)


def load_metrics(limit: int = 300) -> list[dict]:
    return _tail(METRICS_FILE, limit)


def load_benchmarks(limit: int = 100) -> list[dict]:
    return _tail(BENCH_FILE, limit)


def truncate_on_startup() -> None:
    """Bound the on-disk files once, at startup (keeps appends cheap at runtime)."""
    _truncate(METRICS_FILE, _METRICS_CAP)
    _truncate(BENCH_FILE, _BENCH_CAP)

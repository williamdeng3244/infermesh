# SPDX-License-Identifier: Apache-2.0
"""Shared "community" benchmark library — a queryable store of everyone's runs.

This is the backend behind the **Performance Explorer** (compare box-plots) and
the **Community Benchmarks** list. Unlike :mod:`infermesh.core.history` (an
append-only JSONL of *this node's* runs), the community store is a small SQLite
database designed for filtering and aggregation across many submitters, so a
team can pool results into one shareable library.

One row == one (benchmark-run × context-length), mirroring the oMLX submission
schema so the two pages get parity for free. The instance that owns the DB acts
as the **hub**; other nodes submit to it over HTTP (see ``hub_url`` in Settings).

Control-plane pure: stdlib ``sqlite3`` only — no vendor SDK, no torch/mlx. A
fresh connection per call keeps it thread-safe under FastAPI's threadpool.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import uuid
from pathlib import Path
from statistics import mean
from typing import Optional

from infermesh.core.settings import HOME_DIR

#: Current on-disk schema. v2 (Milestone 2) adds driver fingerprints,
#: multi-device, energy, latency-distribution, and correctness columns —
#: all nullable, so v1 rows stay fully readable after migration.
SCHEMA_VERSION = 2

# Columns the box-plot / table read; also the whitelist of selectable metrics.
METRICS = (
    "pp_tps", "tg_tps", "ttft_ms", "tpot_ms",
    "peak_mem_gb", "e2e_latency_s", "total_throughput",
)

# v2 additions and their SQLite types. Columns marked (JSON) hold a
# JSON-encoded object in TEXT; they are decoded on read.
_V2_TYPES = {
    "driver_version": "TEXT", "firmware_version": "TEXT", "sdk_version": "TEXT",
    "device_count": "INTEGER",
    "parallelism": "TEXT",       # (JSON) {"tp": 2, "pp": 1}
    "interconnect": "TEXT",
    "power_avg_w": "REAL", "energy_j": "REAL",
    "percentiles": "TEXT",       # (JSON) {"ttft": {"p50":..,"p99":..}, "itl": {..}}
    "cv_itl": "REAL", "n_requests": "INTEGER",
    "correctness": "TEXT",       # (JSON) {"greedy_match":.., "mean_kl":.., "ref":..}
}
_JSON_COLUMNS = ("parallelism", "percentiles", "correctness")

# Full column set, in insert order. id/created_at/dedup_key are bookkeeping.
_COLUMNS = (
    "id", "created_at", "submitter", "submission_group", "run_id",
    "chip", "vendor", "accel_mem_gb", "cores",
    "infermesh_version", "os", "backend",
    "model", "quant", "context_length", "batch_size",
    "pp_tps", "tg_tps", "ttft_ms", "tpot_ms",
    "peak_mem_gb", "e2e_latency_s", "total_throughput",
    *(_V2_TYPES.keys()),
    "dedup_key",
)

_DDL = """
CREATE TABLE IF NOT EXISTS runs (
    id                TEXT PRIMARY KEY,
    created_at        REAL,
    submitter         TEXT,
    submission_group  TEXT,
    run_id            TEXT,
    chip              TEXT,
    vendor            TEXT,
    accel_mem_gb      REAL,
    cores             INTEGER,
    infermesh_version TEXT,
    os                TEXT,
    backend           TEXT,
    model             TEXT,
    quant             TEXT,
    context_length    INTEGER,
    batch_size        INTEGER,
    pp_tps            REAL,
    tg_tps            REAL,
    ttft_ms           REAL,
    tpot_ms           REAL,
    peak_mem_gb       REAL,
    e2e_latency_s     REAL,
    total_throughput  REAL,
    driver_version    TEXT,
    firmware_version  TEXT,
    sdk_version       TEXT,
    device_count      INTEGER,
    parallelism       TEXT,
    interconnect      TEXT,
    power_avg_w       REAL,
    energy_j          REAL,
    percentiles       TEXT,
    cv_itl            REAL,
    n_requests        INTEGER,
    correctness       TEXT,
    dedup_key         TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_runs_chip    ON runs(chip);
CREATE INDEX IF NOT EXISTS idx_runs_model   ON runs(model);
CREATE INDEX IF NOT EXISTS idx_runs_quant   ON runs(quant);
CREATE INDEX IF NOT EXISTS idx_runs_context ON runs(context_length);
"""


def _ensure_schema(conn: sqlite3.Connection) -> None:
    """Migrate an existing DB to :data:`SCHEMA_VERSION` (idempotent).

    v1→v2 is purely additive: ``ALTER TABLE .. ADD COLUMN`` for each missing
    nullable column, then stamp both the ``schema_version`` table and
    ``PRAGMA user_version``. Old rows read back unchanged with NULLs in the
    new columns."""
    have = {r[1] for r in conn.execute("PRAGMA table_info(runs)").fetchall()}
    for name, typ in _V2_TYPES.items():
        if name not in have:
            conn.execute("ALTER TABLE runs ADD COLUMN %s %s" % (name, typ))
    conn.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    if row is None:
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,))
    elif int(row[0]) != SCHEMA_VERSION:
        conn.execute("UPDATE schema_version SET version=?", (SCHEMA_VERSION,))
    conn.execute("PRAGMA user_version=%d" % SCHEMA_VERSION)
    conn.commit()


def _db_path() -> Path:
    env = os.environ.get("INFERMESH_COMMUNITY_DB")
    return Path(env) if env else (HOME_DIR / "community.db")


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")       # concurrent readers while one writes
    conn.executescript(_DDL)
    _ensure_schema(conn)                          # v1 DBs gain the v2 columns in place
    return conn


def _num(v) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _dedup_key(rec: dict) -> str:
    """Idempotency key: a re-submitted sweep collapses, a *new* run adds a point.

    Keyed by submission_group (or run_id, or the row's unique id) + context_length,
    so repeated POSTs of the same sweep dedupe, while a fresh benchmark (new group,
    or a group-less submission whose ``id`` is freshly generated) accumulates a new
    sample — exactly what the box-plot distribution needs. ``normalize`` assigns
    ``id`` before calling this, guaranteeing group-less rows never collapse."""
    base = rec.get("submission_group") or rec.get("run_id") or rec.get("id") or ""
    parts = [str(base), str(rec.get("context_length") or "")]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:24]


def normalize(rec: dict) -> dict:
    """Coerce a submitted dict into a full row (fill id/created_at/dedup_key)."""
    out = {c: rec.get(c) for c in _COLUMNS}
    out["id"] = rec.get("id") or uuid.uuid4().hex[:12]
    out["created_at"] = _num(rec.get("created_at")) or time.time()
    for c in ("accel_mem_gb", "power_avg_w", "energy_j", "cv_itl", *METRICS):
        out[c] = _num(rec.get(c))
    for c in ("cores", "context_length", "batch_size", "device_count", "n_requests"):
        try:
            out[c] = None if rec.get(c) is None else int(rec.get(c))
        except (TypeError, ValueError):
            out[c] = None
    for c in _JSON_COLUMNS:  # dict/list in, JSON text on disk; strings pass through
        v = rec.get(c)
        if isinstance(v, (dict, list)):
            out[c] = json.dumps(v)
        elif not (v is None or isinstance(v, str)):
            out[c] = None
    out["submitter"] = (rec.get("submitter") or "anonymous")
    out["model"] = rec.get("model") or "—"
    out["chip"] = rec.get("chip") or rec.get("device_name") or rec.get("vendor") or "CPU"
    out["quant"] = rec.get("quant") or "—"
    out["dedup_key"] = _dedup_key(out)
    return out


def _decode_row(d: dict) -> dict:
    """JSON-decode the (JSON) TEXT columns on the way out."""
    for c in _JSON_COLUMNS:
        v = d.get(c)
        if isinstance(v, str) and v:
            try:
                d[c] = json.loads(v)
            except ValueError:
                pass
    return d


def submit(rec: dict) -> dict:
    """Insert one run. Returns ``{id, url, duplicate}``; idempotent on dedup_key."""
    row = normalize(rec)
    conn = _connect()
    try:
        existing = conn.execute(
            "SELECT id FROM runs WHERE dedup_key=?", (row["dedup_key"],)).fetchone()
        if existing:
            return {"id": existing["id"], "duplicate": True,
                    "url": "/community?id=" + existing["id"]}
        conn.execute(
            "INSERT INTO runs (%s) VALUES (%s)" % (
                ",".join(_COLUMNS), ",".join("?" * len(_COLUMNS))),
            tuple(row[c] for c in _COLUMNS))
        conn.commit()
        return {"id": row["id"], "duplicate": False, "url": "/community?id=" + row["id"]}
    finally:
        conn.close()


def submit_many(recs: list[dict]) -> dict:
    ids = [submit(r) for r in recs]
    return {"submitted": len(ids), "ids": [r["id"] for r in ids],
            "duplicates": sum(1 for r in ids if r.get("duplicate"))}


# --------------------------- querying / filtering --------------------------- #

_SORTS = {
    "recent": "created_at DESC", "oldest": "created_at ASC",
    "pp": "pp_tps DESC", "tg": "tg_tps DESC",
    "model": "model ASC", "chip": "chip ASC", "context": "context_length ASC",
}


def query_runs(*, chip: str = "", vendor: str = "", model: str = "", quant: str = "",
               context: Optional[int] = None, min_pp: Optional[float] = None,
               min_tg: Optional[float] = None, submitter: str = "",
               sort: str = "recent", limit: int = 500) -> list[dict]:
    """Filtered list for the Community page. Empty/None filters are ignored."""
    where, args = [], []
    if chip:
        where.append("chip=?"); args.append(chip)
    if vendor:
        where.append("vendor=?"); args.append(vendor)
    if quant:
        where.append("quant=?"); args.append(quant)
    if model:
        where.append("model LIKE ?"); args.append("%" + model + "%")
    if submitter:
        where.append("submitter LIKE ?"); args.append("%" + submitter + "%")
    if context is not None:
        where.append("context_length=?"); args.append(int(context))
    if min_pp is not None:
        where.append("pp_tps >= ?"); args.append(float(min_pp))
    if min_tg is not None:
        where.append("tg_tps >= ?"); args.append(float(min_tg))
    sql = "SELECT * FROM runs"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY " + _SORTS.get(sort, _SORTS["recent"])
    sql += " LIMIT ?"; args.append(max(1, min(int(limit), 5000)))
    conn = _connect()
    try:
        return [_decode_row(dict(r)) for r in conn.execute(sql, args).fetchall()]
    finally:
        conn.close()


def facets() -> dict:
    """Distinct values for the filter dropdowns + a total count."""
    conn = _connect()
    try:
        def distinct(col):
            rows = conn.execute(
                "SELECT DISTINCT %s AS v FROM runs WHERE v IS NOT NULL ORDER BY v" % col
            ).fetchall()
            return [r["v"] for r in rows]
        total = conn.execute("SELECT COUNT(*) AS n FROM runs").fetchone()["n"]
        return {
            "chips": distinct("chip"), "vendors": distinct("vendor"),
            "models": distinct("model"), "quants": distinct("quant"),
            "contexts": distinct("context_length"),
            "submitters": distinct("submitter"), "total": total,
        }
    finally:
        conn.close()


def get(run_id: str) -> Optional[dict]:
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        return _decode_row(dict(row)) if row else None
    finally:
        conn.close()


# --------------------------- compare / box-plot ----------------------------- #

def _box(values: list[float]) -> dict:
    """Five-number summary (+mean, n) for a box plot. Pure-Python quantiles."""
    vs = sorted(v for v in values if v is not None)
    n = len(vs)
    if n == 0:
        return {"n": 0}
    if n == 1:
        v = vs[0]
        return {"n": 1, "min": v, "q1": v, "median": v, "q3": v, "max": v, "mean": v}

    def q(p):  # linear-interpolation quantile
        idx = p * (n - 1)
        lo = int(idx)
        frac = idx - lo
        return vs[lo] if lo + 1 >= n else vs[lo] + (vs[lo + 1] - vs[lo]) * frac
    return {"n": n, "min": vs[0], "q1": round(q(0.25), 2), "median": round(q(0.5), 2),
            "q3": round(q(0.75), 2), "max": vs[-1], "mean": round(mean(vs), 2)}


def compare(metric: str, series: list[dict]) -> dict:
    """Box-plot aggregation for the Explorer.

    ``series`` is a list of ``{chip, model, quant}`` selectors. For each series ×
    context-length, returns the five-number summary of ``metric`` plus the raw
    points (for the "show data points" overlay). Mirrors omlx.ai/compare.
    """
    metric = metric if metric in METRICS else "pp_tps"
    conn = _connect()
    try:
        contexts: set[int] = set()
        out_series = []
        for sel in series:
            chip = sel.get("chip") or ""
            model = sel.get("model") or ""
            quant = sel.get("quant") or ""
            where, args = [], []
            if chip:
                where.append("chip=?"); args.append(chip)
            if model:
                where.append("model=?"); args.append(model)
            if quant and quant != "*":
                where.append("quant=?"); args.append(quant)
            sql = ("SELECT context_length AS ctx, %s AS m FROM runs" % metric)
            if where:
                sql += " WHERE " + " AND ".join(where)
            buckets: dict[int, list] = {}
            for r in conn.execute(sql, args).fetchall():
                if r["ctx"] is None or r["m"] is None:
                    continue
                buckets.setdefault(int(r["ctx"]), []).append(float(r["m"]))
            cells = {}
            for ctx, vals in buckets.items():
                contexts.add(ctx)
                box = _box(vals)
                box["points"] = sorted(round(v, 2) for v in vals)
                cells[str(ctx)] = box
            key = " · ".join(p for p in (chip, model, (quant if quant != "*" else "")) if p)
            out_series.append({"key": key, "chip": chip, "model": model,
                               "quant": quant, "cells": cells})
        return {"metric": metric, "contexts": sorted(contexts), "series": out_series}
    finally:
        conn.close()


def count() -> int:
    conn = _connect()
    try:
        return conn.execute("SELECT COUNT(*) AS n FROM runs").fetchone()["n"]
    finally:
        conn.close()


def clear() -> int:
    """Remove every row (admin / one-time history-rebuild use). Returns the count
    removed. The store is a derived cache — callers rebuild from source after."""
    conn = _connect()
    try:
        n = conn.execute("SELECT COUNT(*) AS n FROM runs").fetchone()["n"]
        conn.execute("DELETE FROM runs")
        conn.commit()
        return n
    finally:
        conn.close()

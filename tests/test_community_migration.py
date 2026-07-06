# SPDX-License-Identifier: Apache-2.0
"""Community-store schema v1→v2 migration (Milestone 2, commit 1).

Builds a real v1 SQLite file from the frozen v1 DDL below, then exercises the
store through the public module API so `_connect()` performs the migration.
"""

import os
import sqlite3
from pathlib import Path

from infermesh.core import community

# The community-store schema exactly as shipped before Milestone 2 (v1).
_V1_DDL = """
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
    dedup_key         TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_runs_chip    ON runs(chip);
CREATE INDEX IF NOT EXISTS idx_runs_model   ON runs(model);
CREATE INDEX IF NOT EXISTS idx_runs_quant   ON runs(quant);
CREATE INDEX IF NOT EXISTS idx_runs_context ON runs(context_length);
"""

_V1_ROWS = [
    dict(id="v1row0000001", created_at=1751400000.0, submitter="bench-rig",
         submission_group="grp1", run_id="grp1", chip="Enflame S60",
         vendor="enflame", accel_mem_gb=48.0, cores=None,
         infermesh_version="0.5.0", os="Linux", backend="transformers",
         model="Qwen2.5-7B-Instruct", quant="fp16", context_length=2048,
         batch_size=4, pp_tps=350.5, tg_tps=12.1, ttft_ms=820.0, tpot_ms=83.0,
         peak_mem_gb=14.5, e2e_latency_s=6.2, total_throughput=410.0,
         dedup_key="k1"),
    dict(id="v1row0000002", created_at=1751400100.0, submitter="bench-rig",
         submission_group="grp2", run_id="grp2", chip="NVIDIA A100",
         vendor="nvidia", accel_mem_gb=80.0, cores=None,
         infermesh_version="0.5.0", os="Linux", backend="vllm",
         model="Qwen2.5-7B-Instruct", quant="int8", context_length=4096,
         batch_size=8, pp_tps=5200.0, tg_tps=95.0, ttft_ms=120.0, tpot_ms=10.5,
         peak_mem_gb=22.0, e2e_latency_s=1.4, total_throughput=6100.0,
         dedup_key="k2"),
]


def _db_path() -> Path:
    return Path(os.environ["INFERMESH_COMMUNITY_DB"])  # set by conftest autouse


def _make_v1_db() -> Path:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(_V1_DDL)
    cols = list(_V1_ROWS[0].keys())
    conn.executemany(
        "INSERT INTO runs (%s) VALUES (%s)" % (",".join(cols), ",".join("?" * len(cols))),
        [tuple(r[c] for c in cols) for r in _V1_ROWS])
    conn.commit()
    conn.close()
    return path


def test_v1_rows_survive_migration():
    path = _make_v1_db()
    rows = community.query_runs(sort="oldest")  # _connect() migrates in place
    assert [r["id"] for r in rows] == ["v1row0000001", "v1row0000002"]
    old = rows[0]
    assert old["chip"] == "Enflame S60" and old["quant"] == "fp16"
    assert old["pp_tps"] == 350.5 and old["tg_tps"] == 12.1
    assert old["peak_mem_gb"] == 14.5 and old["context_length"] == 2048
    for col in ("driver_version", "device_count", "parallelism", "interconnect",
                "power_avg_w", "energy_j", "percentiles", "cv_itl",
                "n_requests", "correctness"):
        assert old[col] is None, col  # new columns are NULL on old rows
    conn = sqlite3.connect(str(path))
    assert conn.execute("PRAGMA user_version").fetchone()[0] == community.SCHEMA_VERSION
    assert conn.execute("SELECT version FROM schema_version").fetchone()[0] \
        == community.SCHEMA_VERSION
    conn.close()


def test_v2_fields_roundtrip_after_migration():
    _make_v1_db()
    community.submit({
        "submitter": "bench-rig", "chip": "Enflame S60", "vendor": "enflame",
        "model": "Qwen2.5-7B-Instruct", "quant": "fp16", "context_length": 2048,
        "pp_tps": 355.0, "tg_tps": 12.4,
        "driver_version": "TopsRider 3.4.1", "firmware_version": "fw-1.9",
        "sdk_version": "sdk-2.2", "device_count": 2,
        "parallelism": {"tp": 2, "pp": 1}, "interconnect": "esl",
        "power_avg_w": 275.5, "energy_j": 8420.0,
        "percentiles": {"ttft": {"p50": 810.0, "p90": 950.0, "p99": 1200.0,
                                 "p999": 1500.0},
                        "itl": {"p50": 80.0, "p90": 95.0, "p99": 130.0}},
        "cv_itl": 0.18, "n_requests": 64,
        "correctness": {"greedy_match": 0.992, "mean_kl": 0.0031,
                        "ref": "fp16-cpu-precomputed", "first_divergence": 137},
    })
    got = [r for r in community.query_runs() if r["driver_version"]][0]
    assert got["driver_version"] == "TopsRider 3.4.1"
    assert got["device_count"] == 2 and got["interconnect"] == "esl"
    assert got["parallelism"] == {"tp": 2, "pp": 1}          # decoded on read
    assert got["percentiles"]["ttft"]["p99"] == 1200.0
    assert got["correctness"]["greedy_match"] == 0.992
    assert got["power_avg_w"] == 275.5 and got["cv_itl"] == 0.18
    assert got["n_requests"] == 64
    # single-row get() decodes too
    assert community.get(got["id"])["parallelism"] == {"tp": 2, "pp": 1}


def test_migration_is_idempotent():
    path = _make_v1_db()
    assert community.count() == 2   # first connect migrates
    assert community.count() == 2   # second connect must not re-alter
    conn = sqlite3.connect(str(path))
    names = [r[1] for r in conn.execute("PRAGMA table_info(runs)").fetchall()]
    assert len(names) == len(set(names))  # no duplicated columns
    assert conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == 1
    conn.close()


def test_fresh_db_is_born_v2():
    assert community.count() == 0   # creates a brand-new DB via the v2 DDL
    conn = sqlite3.connect(str(_db_path()))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(runs)").fetchall()}
    assert {"percentiles", "correctness", "device_count", "power_avg_w"} <= cols
    assert conn.execute("PRAGMA user_version").fetchone()[0] == community.SCHEMA_VERSION
    conn.close()

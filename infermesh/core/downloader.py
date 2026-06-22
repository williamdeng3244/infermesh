# SPDX-License-Identifier: Apache-2.0
"""HuggingFace model downloader for the dashboard.

Search the Hub, read a repo's total size, and pull it into the ``--model-dir`` in
the background with progress. ``huggingface_hub`` is imported lazily so the control
plane imports without it; install the extra: ``pip install 'infermesh[downloader]'``.

The thin ``_hf_*`` wrappers are the single seam tests monkeypatch to avoid network.
A download lands at ``<model_dir>/<repo-basename>`` so the registry's discovery and
the downloader agree on ``model_id`` (== the basename).
"""

from __future__ import annotations

import os
import threading
from pathlib import Path


def _require_hf():
    try:
        import huggingface_hub
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "huggingface_hub is not installed. Install the extra: "
            "pip install 'infermesh[downloader]'"
        ) from exc
    return huggingface_hub


_endpoint = None  # optional HF mirror endpoint (e.g. https://hf-mirror.com)


def set_endpoint(url) -> None:
    """Point search/download at a HuggingFace mirror (None = the default hub)."""
    global _endpoint
    _endpoint = url or None


def _api(hf):
    return hf.HfApi(endpoint=_endpoint) if _endpoint else hf.HfApi()


def _hf_list_models(query: str, limit: int, sort: str = "downloads", task=None) -> list:
    hf = _require_hf()
    kw = {"limit": limit, "sort": sort}
    if query:
        kw["search"] = query
    if task:
        kw["pipeline_tag"] = task
    return list(_api(hf).list_models(**kw))


def _hf_model_info(repo_id: str):
    hf = _require_hf()
    return _api(hf).model_info(repo_id, files_metadata=True)


def _hf_snapshot(repo_id: str, dest: str) -> str:
    hf = _require_hf()
    kw = {"endpoint": _endpoint} if _endpoint else {}
    return hf.snapshot_download(repo_id, local_dir=dest, **kw)


def search_models(query: str = "", limit: int = 20, sort: str = "downloads", task=None) -> list[dict]:
    out: list[dict] = []
    for m in _hf_list_models(query, limit, sort=sort, task=task):
        out.append({
            "id": getattr(m, "id", None) or getattr(m, "modelId", ""),
            "downloads": int(getattr(m, "downloads", 0) or 0),
            "likes": int(getattr(m, "likes", 0) or 0),
            "pipeline_tag": getattr(m, "pipeline_tag", None),
            "gated": bool(getattr(m, "gated", False)),
        })
    return out


def model_size_bytes(repo_id: str) -> int:
    info = _hf_model_info(repo_id)
    total = 0
    for sib in (getattr(info, "siblings", None) or []):
        total += int(getattr(sib, "size", 0) or 0)
    return total


_JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()


def _dir_size(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def _dest_for(repo_id: str, model_dir: str) -> Path:
    return Path(model_dir).expanduser() / repo_id.split("/")[-1]


def start_download(repo_id: str, model_dir: str) -> dict:
    """Kick off a background snapshot download; returns the initial job record."""
    dest = _dest_for(repo_id, model_dir)
    with _LOCK:
        existing = _JOBS.get(repo_id)
        if existing and existing["status"] in ("queued", "downloading"):
            return dict(existing)
        _JOBS[repo_id] = {
            "repo_id": repo_id, "status": "queued", "total_bytes": 0,
            "downloaded_bytes": 0, "path": str(dest), "model_id": dest.name, "error": None,
        }

    def _run() -> None:
        try:
            total = model_size_bytes(repo_id)
            with _LOCK:
                _JOBS[repo_id]["total_bytes"] = total
                _JOBS[repo_id]["status"] = "downloading"
            _hf_snapshot(repo_id, str(dest))
            with _LOCK:
                _JOBS[repo_id]["status"] = "done"
                _JOBS[repo_id]["downloaded_bytes"] = _JOBS[repo_id]["total_bytes"] or _dir_size(str(dest))
        except Exception as exc:  # noqa: BLE001 - surface to the UI, never crash
            with _LOCK:
                _JOBS[repo_id]["status"] = "error"
                _JOBS[repo_id]["error"] = str(exc)[:300]

    threading.Thread(target=_run, daemon=True).start()
    with _LOCK:
        return dict(_JOBS[repo_id])


def downloads_status() -> list[dict]:
    """All jobs, with live progress (downloading jobs are sized from disk)."""
    with _LOCK:
        jobs = [dict(j) for j in _JOBS.values()]
    for j in jobs:
        if j["status"] == "downloading":
            j["downloaded_bytes"] = _dir_size(j["path"])
        total = j.get("total_bytes") or 0
        if total:
            j["progress"] = round(min(1.0, j["downloaded_bytes"] / total), 3)
        else:
            j["progress"] = 1.0 if j["status"] == "done" else 0.0
    return jobs


def completed_jobs() -> list[dict]:
    """Done jobs — the server registers these into the pool."""
    with _LOCK:
        return [dict(j) for j in _JOBS.values() if j["status"] == "done"]

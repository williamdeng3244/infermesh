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


def _require_ms():
    try:
        import modelscope  # noqa: F401
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "modelscope is not installed. Install the extra: "
            "pip install 'infermesh[modelscope]'"
        ) from exc
    return modelscope


def _ms_snapshot(repo_id: str, dest: str) -> str:
    ms = _require_ms()
    return ms.snapshot_download(repo_id, local_dir=dest)


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
_PROCS: dict[str, object] = {}   # repo_id -> killable handle (Popen, or a thread handle in tests)
_LOCK = threading.Lock()

# Production downloads run as a killable subprocess so they can be paused/cancelled
# (a daemon thread running snapshot_download can't be stopped). Tests flip this to
# run the (monkeypatched) snapshot in-process.
subprocess_downloads = True


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


class _ThreadHandle:
    """In-process fallback handle (tests / no-subprocess). Not killable — terminate
    is a no-op, which is fine because the snapshot seam is mocked to be instant."""

    def __init__(self, fn):
        self._rc = None
        self._t = threading.Thread(target=self._run, args=(fn,), daemon=True)
        self._t.start()

    def _run(self, fn):
        try:
            fn()
            self._rc = 0
        except Exception:  # noqa: BLE001
            self._rc = 1

    def wait(self, timeout=None):
        self._t.join(timeout)
        return 0 if self._rc is None else self._rc

    def poll(self):
        return self._rc

    def terminate(self):
        pass


def _spawn_worker(repo_id: str, dest: str, source: str):
    """Start the download and return a killable handle. The single seam for tests."""
    if not subprocess_downloads:
        snap = _ms_snapshot if source == "modelscope" else _hf_snapshot
        return _ThreadHandle(lambda: snap(repo_id, dest))
    import subprocess
    import sys
    argv = [sys.executable, "-m", "infermesh.core._dlworker", repo_id, dest, source, _endpoint or ""]
    return subprocess.Popen(argv)


def start_download(repo_id: str, model_dir: str, source: str = "hf") -> dict:
    """Kick off a background (killable) snapshot download; returns the job record.
    ``source`` is ``"hf"`` (HuggingFace) or ``"modelscope"``. Re-calling a paused or
    errored repo *resumes* it — snapshot_download skips already-fetched files."""
    dest = _dest_for(repo_id, model_dir)
    with _LOCK:
        existing = _JOBS.get(repo_id)
        if existing and existing["status"] == "downloading" and repo_id in _PROCS:
            return dict(existing)
        _JOBS[repo_id] = {
            "repo_id": repo_id, "status": "downloading",
            "total_bytes": (existing or {}).get("total_bytes", 0),
            "downloaded_bytes": 0, "path": str(dest), "model_id": dest.name,
            "error": None, "source": source,
        }
    handle = _spawn_worker(repo_id, str(dest), source)
    with _LOCK:
        _PROCS[repo_id] = handle
    threading.Thread(target=_monitor, args=(repo_id, source), daemon=True).start()
    with _LOCK:
        return dict(_JOBS[repo_id])


def _monitor(repo_id: str, source: str) -> None:
    if source != "modelscope":  # repo size (a network call) — kept off the request path
        try:
            total = model_size_bytes(repo_id)
            with _LOCK:
                if repo_id in _JOBS and not _JOBS[repo_id].get("total_bytes"):
                    _JOBS[repo_id]["total_bytes"] = total
        except Exception:  # noqa: BLE001
            pass
    handle = _PROCS.get(repo_id)
    if handle is None:
        return
    try:
        rc = handle.wait()
    except Exception:  # noqa: BLE001
        rc = -1
    with _LOCK:
        job = _JOBS.get(repo_id)
        _PROCS.pop(repo_id, None)
        if job is None or job["status"] == "paused":
            return  # deleted, or deliberately paused — don't overwrite the status
        if rc == 0:
            job["status"] = "done"
            job["downloaded_bytes"] = job.get("total_bytes") or _dir_size(job["path"])
        else:
            job["status"] = "error"
            job["error"] = job.get("error") or ("download worker exited with code %s" % rc)


def pause_download(repo_id: str) -> dict:
    """Stop an in-progress download, keeping partial files; resume by downloading again."""
    with _LOCK:
        job = _JOBS.get(repo_id)
        handle = _PROCS.get(repo_id)
        if job is not None and job["status"] in ("downloading", "queued"):
            job["status"] = "paused"
    if handle is not None:
        try:
            handle.terminate()
        except Exception:  # noqa: BLE001
            pass
    with _LOCK:
        return dict(_JOBS.get(repo_id) or {"repo_id": repo_id, "status": "unknown"})


def delete_download(repo_id: str) -> dict:
    """Cancel (if running) and remove a download job + its files from disk."""
    import shutil
    with _LOCK:
        job = _JOBS.pop(repo_id, None)
        handle = _PROCS.pop(repo_id, None)
    if handle is not None:
        try:
            handle.terminate()
            handle.wait(timeout=5)
        except Exception:  # noqa: BLE001
            pass
    removed = False
    path = (job or {}).get("path")
    if path:
        try:
            shutil.rmtree(path)
            removed = True
        except FileNotFoundError:
            removed = True
        except OSError:
            pass
    return {"repo_id": repo_id, "deleted": True, "files_removed": removed, "path": path}


def downloads_status() -> list[dict]:
    """All jobs, with live progress (active/paused jobs are sized from disk)."""
    with _LOCK:
        jobs = [dict(j) for j in _JOBS.values()]
    for j in jobs:
        if j["status"] in ("downloading", "paused"):
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

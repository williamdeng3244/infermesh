# SPDX-License-Identifier: Apache-2.0
"""``infermesh`` CLI — foreground ``serve`` plus background ``start``/``stop``/
``restart``/``status`` service management.

CLI flags mirror oMLX where sensible and take precedence over the persisted
``~/.infermesh/settings.json`` (resolved settings are written back). This module
imports no vendor SDK; FastAPI/uvicorn/server are imported lazily inside the
serve command so ``infermesh --help`` stays light.

Service management is cross-platform (WSL/Linux and Windows) and dependency-free:
``start`` spawns a detached ``python -m infermesh.cli serve ...`` child, writes a
JSON pidfile under ``~/.infermesh/``, and redirects its output to a log file;
``stop``/``restart``/``status`` operate on that pidfile.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Sequence

from infermesh.core.backend import ModelSpec
from infermesh.core.factory import BackendFactory
from infermesh.core.memory import SystemMemoryProbe
from infermesh.core.pool import ModelPool
from infermesh.core.registry import ModelRegistry
from infermesh.core.settings import HOME_DIR, LOG_DIR, Settings, parse_memory_limit

PID_PATH = HOME_DIR / "infermesh.pid"


# --------------------------------------------------------------------------- #
# Argument parsing
# --------------------------------------------------------------------------- #
def _add_serve_args(p: argparse.ArgumentParser) -> None:
    """Flags shared by ``serve``, ``start``, and ``restart``."""
    p.add_argument("--model-dir", default=None,
                   help="Directory containing model subdirectories")
    p.add_argument("--host", default=None, help="Bind host (default 127.0.0.1)")
    p.add_argument("--port", type=int, default=None, help="Bind port (default 8000)")
    p.add_argument("--backend", choices=["mock", "vllm", "transformers"], default=None,
                   help="Default backend for models that don't force one")
    p.add_argument("--max-concurrent-requests", type=int, default=None,
                   help="Soft concurrency hint (stored; not enforced in M1)")
    p.add_argument("--idle-timeout", type=float, default=None,
                   help="Idle seconds before unloading a model (0 = never)")
    p.add_argument("--max-process-memory", default=None,
                   help="Memory ceiling for loaded models: '80%%' | '12GB' | '512MB'")
    p.add_argument("--api-key", default=None,
                   help="Optional single API key (Authorization: Bearer / x-api-key)")
    p.add_argument("--pin", action="append", default=None, metavar="MODEL_ID",
                   help="Pin a model so it is preloaded and never evicted (repeatable)")
    p.add_argument("--providers", default=None, metavar="FILE",
                   help="JSON file of remote OpenAI-compatible models to register "
                        "(OpenAI / Anthropic / OpenRouter / a local server). See README.")
    p.add_argument("--sse-keepalive", type=float, default=None, metavar="SECONDS",
                   help="Seconds between SSE ': keep-alive' comments during long prefill "
                        "(0 = off; default 15)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="infermesh",
        description="Hardware-agnostic LLM inference serving platform.",
    )
    sub = parser.add_subparsers(dest="command")
    _add_serve_args(sub.add_parser("serve", help="Run the gateway in the foreground"))
    _add_serve_args(sub.add_parser("start", help="Start the gateway in the background (pidfile)"))
    _add_serve_args(sub.add_parser("restart", help="Restart the background gateway"))
    sub.add_parser("stop", help="Stop the background gateway")
    sub.add_parser("status", help="Show background gateway status + health")
    return parser


# --------------------------------------------------------------------------- #
# Settings + providers
# --------------------------------------------------------------------------- #
def _load_providers(path: object) -> list[ModelSpec]:
    """Parse a providers JSON file into OpenAI-compat-backed ModelSpecs.

    File shape: ``{"models": [{"id", "base_url", "api_key", "upstream_model"}, ...]}``
    (a bare list is also accepted). ``api_key`` may be ``"env:VAR"`` so secrets
    stay out of the file. Remote models are registered at 0 MB so they never count
    against the VRAM ceiling or evict a local model.
    """
    data = json.loads(Path(str(path)).expanduser().read_text())
    entries = data.get("models", []) if isinstance(data, dict) else data
    specs: list[ModelSpec] = []
    for e in entries:
        base_url = e.get("base_url") or "https://api.openai.com/v1"
        specs.append(ModelSpec(
            model_id=e["id"],
            source=base_url,
            backend="openai",
            extra={
                "base_url": base_url,
                "api_key": e.get("api_key"),
                "upstream_model": e.get("upstream_model") or e["id"],
                "estimated_mb": 0,
            },
        ))
    return specs


def _resolve_settings(args: argparse.Namespace) -> Settings:
    persisted = Settings.load()
    settings = persisted.merge_cli(
        model_dir=args.model_dir,
        host=args.host,
        port=args.port,
        backend=args.backend,
        max_concurrent_requests=args.max_concurrent_requests,
        idle_timeout=args.idle_timeout,
        max_process_memory=args.max_process_memory,
        api_key=args.api_key,
        sse_keepalive_interval=getattr(args, "sse_keepalive", None),
    )
    settings.save()
    return settings


# --------------------------------------------------------------------------- #
# foreground serve
# --------------------------------------------------------------------------- #
def cmd_serve(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = _resolve_settings(args)

    probe = SystemMemoryProbe()
    ceiling_mb = parse_memory_limit(settings.max_process_memory, probe.total_mb())
    factory = BackendFactory(default_backend=settings.backend)
    pool = ModelPool(
        factory,
        probe=probe,
        max_memory_mb=ceiling_mb,
        idle_timeout=settings.idle_timeout,
    )

    registry = ModelRegistry(default_backend=settings.backend)
    log = logging.getLogger("infermesh.cli")
    specs: list[ModelSpec] = []
    if settings.model_dir:
        local = registry.discover(settings.model_dir)
        specs.extend(local)
        log.info("Discovered %d local models under %s (backend=%s)",
                 len(local), settings.model_dir, settings.backend)
    if getattr(args, "providers", None):
        remote = _load_providers(args.providers)
        specs.extend(remote)
        log.info("Registered %d remote provider models from %s", len(remote), args.providers)
    if specs:
        pool.discover_models(specs, pinned=args.pin)
        log.info("Pool ready: %d models, ceiling=%d MB", len(specs), ceiling_mb)
    else:
        log.warning("No --model-dir or --providers given; serving with an empty model pool.")

    # Lazy imports: keep `infermesh --help` from importing the web stack.
    import uvicorn

    from infermesh.server import create_app

    app = create_app(pool, settings)
    uvicorn.run(app, host=settings.host, port=settings.port)
    return 0


# --------------------------------------------------------------------------- #
# background service management (cross-platform, dependency-free)
# --------------------------------------------------------------------------- #
def _read_pidfile() -> Optional[dict]:
    try:
        return json.loads(PID_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _write_pidfile(info: dict) -> None:
    PID_PATH.parent.mkdir(parents=True, exist_ok=True)
    PID_PATH.write_text(json.dumps(info, indent=2))


def _remove_pidfile() -> None:
    try:
        PID_PATH.unlink()
    except OSError:
        pass


def _pid_alive(pid: object) -> bool:
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        SYNCHRONIZE = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
            return True
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _terminate(pid: int, force: bool = False) -> None:
    if os.name == "nt":
        cmd = ["taskkill", "/PID", str(pid), "/T"] + (["/F"] if force else [])
        subprocess.run(cmd, capture_output=True)
    else:
        os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)


def _detach_kwargs() -> dict:
    if os.name == "nt":
        DETACHED_PROCESS = 0x00000008
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        return {"creationflags": DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _http_health(host: object, port: object, timeout: float = 3.0) -> str:
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://{host}:{port}/health", timeout=timeout) as resp:
            return "ok" if resp.status == 200 else f"http {resp.status}"
    except Exception as exc:  # connection refused / timeout / etc.
        return f"unreachable ({type(exc).__name__})"


def _serve_argv(args: argparse.Namespace) -> list[str]:
    """Rebuild the canonical ``serve`` arg list to forward to the spawned child."""
    out: list[str] = []
    pairs = [
        ("--model-dir", "model_dir"), ("--host", "host"), ("--port", "port"),
        ("--backend", "backend"), ("--max-concurrent-requests", "max_concurrent_requests"),
        ("--idle-timeout", "idle_timeout"), ("--max-process-memory", "max_process_memory"),
        ("--api-key", "api_key"), ("--providers", "providers"), ("--sse-keepalive", "sse_keepalive"),
    ]
    for flag, attr in pairs:
        value = getattr(args, attr, None)
        if value is not None:
            out += [flag, str(value)]
    for model_id in (getattr(args, "pin", None) or []):
        out += ["--pin", model_id]
    return out


def cmd_start(args: argparse.Namespace) -> int:
    settings = _resolve_settings(args)  # persist + resolve host/port
    existing = _read_pidfile()
    if existing and _pid_alive(existing.get("pid")):
        print(f"infermesh already running (pid {existing['pid']}) on "
              f"{existing.get('host')}:{existing.get('port')}")
        return 1

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"server-{settings.port}.log"
    argv = [sys.executable, "-m", "infermesh.cli", "serve", *_serve_argv(args)]
    logf = open(log_path, "a")
    try:
        proc = subprocess.Popen(
            argv, stdout=logf, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, **_detach_kwargs(),
        )
    finally:
        logf.close()  # child has its own dup'd fd

    _write_pidfile({"pid": proc.pid, "host": settings.host, "port": settings.port,
                    "log": str(log_path), "started_at": time.time()})

    deadline = time.time() + 10.0
    health = "starting"
    while time.time() < deadline:
        if not _pid_alive(proc.pid):
            _remove_pidfile()
            print(f"infermesh failed to start (pid {proc.pid} exited); see {log_path}")
            return 1
        if _http_health(settings.host, settings.port, timeout=1.0) == "ok":
            health = "ok"
            break
        time.sleep(0.3)
    print(f"infermesh started (pid {proc.pid}) on {settings.host}:{settings.port} "
          f"[health: {health}]\n  logs: {log_path}")
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    info = _read_pidfile()
    if not info:
        print("infermesh: not running (no pidfile)")
        return 1
    pid = info.get("pid")
    if not _pid_alive(pid):
        _remove_pidfile()
        print(f"infermesh: not running (removed stale pidfile, pid {pid})")
        return 1
    _terminate(int(pid))
    for _ in range(50):  # up to ~5s for a graceful shutdown
        if not _pid_alive(pid):
            break
        time.sleep(0.1)
    else:
        _terminate(int(pid), force=True)
    _remove_pidfile()
    print(f"infermesh: stopped (pid {pid})")
    return 0


def cmd_restart(args: argparse.Namespace) -> int:
    info = _read_pidfile()
    if info and _pid_alive(info.get("pid")):
        cmd_stop(args)
    return cmd_start(args)


def cmd_status(args: argparse.Namespace) -> int:
    info = _read_pidfile()
    if not info:
        print("infermesh: not running")
        return 1
    pid = info.get("pid")
    if not _pid_alive(pid):
        print(f"infermesh: not running (stale pidfile, pid {pid})")
        return 1
    host, port = info.get("host"), info.get("port")
    print(f"infermesh: running (pid {pid}) on {host}:{port} "
          f"[health: {_http_health(host, port)}]")
    print(f"  logs: {info.get('log')}")
    return 0


# --------------------------------------------------------------------------- #
def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    dispatch = {
        "serve": cmd_serve, "start": cmd_start, "stop": cmd_stop,
        "restart": cmd_restart, "status": cmd_status,
    }
    handler = dispatch.get(args.command)
    if handler is None:
        parser.print_help()
        return 1
    return handler(args)


if __name__ == "__main__":
    raise SystemExit(main())

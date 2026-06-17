# SPDX-License-Identifier: Apache-2.0
"""``infermesh serve`` — start the gateway over a --model-dir.

CLI flags mirror oMLX where sensible and take precedence over the persisted
``~/.infermesh/settings.json`` (resolved settings are written back). This module
imports no vendor SDK; FastAPI/uvicorn/server are imported lazily inside the
serve command so ``infermesh --help`` stays light.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Optional, Sequence

from infermesh.core.backend import ModelSpec
from infermesh.core.factory import BackendFactory
from infermesh.core.memory import SystemMemoryProbe
from infermesh.core.pool import ModelPool
from infermesh.core.registry import ModelRegistry
from infermesh.core.settings import Settings, parse_memory_limit


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="infermesh",
        description="Hardware-agnostic LLM inference serving platform.",
    )
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="Run the inference gateway")
    serve.add_argument("--model-dir", default=None,
                       help="Directory containing model subdirectories")
    serve.add_argument("--host", default=None, help="Bind host (default 127.0.0.1)")
    serve.add_argument("--port", type=int, default=None, help="Bind port (default 8000)")
    serve.add_argument("--backend", choices=["mock", "vllm"], default=None,
                       help="Default backend for models that don't force one")
    serve.add_argument("--max-concurrent-requests", type=int, default=None,
                       help="Soft concurrency hint (stored; not enforced in M1)")
    serve.add_argument("--idle-timeout", type=float, default=None,
                       help="Idle seconds before unloading a model (0 = never)")
    serve.add_argument("--max-process-memory", default=None,
                       help="Memory ceiling for loaded models: '80%%' | '12GB' | '512MB'")
    serve.add_argument("--api-key", default=None,
                       help="Optional single API key (Authorization: Bearer / x-api-key)")
    serve.add_argument("--pin", action="append", default=None, metavar="MODEL_ID",
                       help="Pin a model so it is preloaded and never evicted (repeatable)")
    serve.add_argument("--providers", default=None, metavar="FILE",
                       help="JSON file of remote OpenAI-compatible models to register "
                            "(OpenAI / Anthropic / OpenRouter / a local server). See README.")
    return parser


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
    )
    settings.save()
    return settings


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


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "serve":
        return cmd_serve(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

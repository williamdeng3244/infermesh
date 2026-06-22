# SPDX-License-Identifier: Apache-2.0
"""Configuration + CLI-flag persistence (slim).

Resolved settings persist to ``~/.infermesh/settings.json``. CLI flags take
precedence over persisted values (oMLX convention): load persisted settings,
then :meth:`Settings.merge_cli` the non-``None`` CLI overrides on top, then
:meth:`Settings.save`.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Optional

HOME_DIR = Path.home() / ".infermesh"
SETTINGS_PATH = HOME_DIR / "settings.json"
LOG_DIR = HOME_DIR / "logs"


@dataclass
class Settings:
    """Server + pool configuration. Mirrors the ``infermesh serve`` CLI flags."""

    model_dir: Optional[str] = None
    host: str = "127.0.0.1"
    port: int = 8000
    backend: str = "mock"                 # default backend when a spec doesn't force one
    max_concurrent_requests: int = 8
    idle_timeout: float = 0.0             # seconds; 0 => never idle-unload
    max_process_memory: str = "80%"       # "80%" | "12GB" | "512MB" | bare MB
    api_key: Optional[str] = None         # optional single bearer/x-api-key; None => auth off
    ttl_check_interval: float = 30.0      # seconds between pool.check_ttl_expirations()
    sse_keepalive_interval: float = 15.0  # emit ': keep-alive' SSE comment if no token for N s (0 => off)
    kv_hot_capacity: int = 0              # Transformers tiered-KV hot entries (0 => off); applied to new model loads
    kv_cold_dir: Optional[str] = None     # cold (SSD) dir for the tiered KV cache

    @classmethod
    def load(cls, path: Path = SETTINGS_PATH) -> "Settings":
        if path.exists():
            try:
                data = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                data = {}
            known = {f.name for f in fields(cls)}
            return cls(**{k: v for k, v in data.items() if k in known})
        return cls()

    def save(self, path: Path = SETTINGS_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), indent=2, sort_keys=True))

    def merge_cli(self, **overrides) -> "Settings":
        """Return a copy with non-``None`` CLI overrides applied (CLI wins)."""
        data = asdict(self)
        for key, value in overrides.items():
            if value is not None and key in data:
                data[key] = value
        return Settings(**data)


def parse_memory_limit(spec: object, total_mb: int) -> int:
    """Resolve a memory ceiling in MB from ``'80%'`` / ``'12GB'`` / ``'512MB'``.

    Percentages are of ``total_mb``; size suffixes are absolute; a bare number is
    treated as MB. Falls back to ``total_mb`` on a parse error.
    """
    s = str(spec).strip().lower().replace(" ", "")
    try:
        if s.endswith("%"):
            return max(0, int(total_mb * float(s[:-1]) / 100.0))
        for suffix, mult in (("gb", 1024), ("g", 1024), ("mb", 1), ("m", 1)):
            if s.endswith(suffix):
                return max(0, int(float(s[: -len(suffix)]) * mult))
        return max(0, int(float(s)))  # bare number => MB
    except (ValueError, TypeError):
        return total_mb

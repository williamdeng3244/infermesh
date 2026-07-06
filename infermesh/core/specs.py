# SPDX-License-Identifier: Apache-2.0
"""Chip spec registry — the denominators for MBU / MFU / tokens-per-joule.

Built-in entries ship with the package (``infermesh/config/chip_specs.json``,
values annotated ``source: datasheet`` or ``estimated``); a user file at
``~/.infermesh/chip_specs.json`` overrides or extends them per chip — that is
where an in-house card (GX series) gets added without touching the package.

Deliberately dumb: static JSON, no hardware counters. The first version of
hardware-efficiency metrics only needs peak bandwidth / peak fp16 TFLOPS /
TDP per chip. Control-plane pure (stdlib json only).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from infermesh.core.settings import HOME_DIR

REQUIRED_NUMERIC = ("peak_bw_gbps", "peak_tflops_fp16", "tdp_w")

_BUILTIN_PATH = Path(__file__).resolve().parent.parent / "config" / "chip_specs.json"


def user_path() -> Path:
    """The per-user override file (chip → partial or full spec)."""
    return HOME_DIR / "chip_specs.json"


def _read_json(path: Path) -> dict:
    try:
        with open(path) as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def validate(specs: dict) -> list[str]:
    """Return a list of problems ([] = clean). Checked on the *merged* view, so
    a user override may be partial as long as the merge is complete."""
    errors: list[str] = []
    if not isinstance(specs, dict):
        return ["specs must be an object of {chip_key: spec}"]
    for key, spec in specs.items():
        if not isinstance(spec, dict):
            errors.append(f"{key}: spec must be an object")
            continue
        for field in REQUIRED_NUMERIC:
            v = spec.get(field)
            if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0:
                errors.append(f"{key}.{field}: must be a positive number (got {v!r})")
        aliases = spec.get("aliases")
        if aliases is not None and not (
                isinstance(aliases, list) and all(isinstance(a, str) for a in aliases)):
            errors.append(f"{key}.aliases: must be a list of strings")
    return errors


def load() -> dict:
    """Built-ins merged with the user file (user wins per field, per chip)."""
    merged = {k: dict(v) for k, v in _read_json(_BUILTIN_PATH).items()}
    for key, spec in _read_json(user_path()).items():
        if isinstance(spec, dict):
            base = merged.get(key, {})
            merged[key] = {**base, **spec}
    return merged


def save_user(overrides: dict) -> dict:
    """Persist the user override file after validating the resulting merge.

    ``overrides`` replaces the whole user file (the dashboard round-trips it).
    Raises ``ValueError`` listing every problem; nothing is written on error."""
    if not isinstance(overrides, dict):
        raise ValueError("specs must be an object of {chip_key: spec}")
    builtin = _read_json(_BUILTIN_PATH)
    merged = {k: dict(v) for k, v in builtin.items()}
    for key, spec in overrides.items():
        if not isinstance(spec, dict):
            raise ValueError(f"{key}: spec must be an object")
        merged[key] = {**merged.get(key, {}), **spec}
    errors = validate(merged)
    if errors:
        raise ValueError("; ".join(errors))
    path = user_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as fh:
        json.dump(overrides, fh, indent=2, ensure_ascii=False)
    return merged


def _norm(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())


def resolve(chip: str) -> Optional[tuple[str, dict]]:
    """Map a chip string as it appears in community rows ("Enflame S60",
    "NVIDIA GeForce RTX 4090", …) to ``(key, spec)`` — by key, name, or alias,
    case/punctuation-insensitive. Returns None for unknown chips."""
    if not chip:
        return None
    want = _norm(str(chip))
    if not want:
        return None
    specs = load()
    for key, spec in specs.items():
        candidates = [key, spec.get("name") or ""] + list(spec.get("aliases") or [])
        if any(_norm(c) == want for c in candidates if c):
            return key, spec
    return None

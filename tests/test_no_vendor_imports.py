# SPDX-License-Identifier: Apache-2.0
"""Enforce the one architectural rule (S1): the control plane imports no vendor SDK.

Source-scans infermesh/core/, infermesh/api/, server.py and cli.py for
``import mlx`` / ``from mlx`` / ``import torch`` / ``from torch`` / ``torch.cuda``
(ignoring comments), and asserts the lifted thinking.py imports cleanly without
mlx present.
"""

import importlib
import re
from pathlib import Path

import infermesh

CONTROL_PLANE_ROOT = Path(infermesh.__file__).parent
SCANNED_DIRS = ("core", "api")
SCANNED_FILES = ("server.py", "cli.py")

FORBIDDEN = re.compile(
    r"\b(?:import\s+mlx|from\s+mlx|import\s+torch|from\s+torch|torch\.cuda)\b"
)


def _python_files():
    for d in SCANNED_DIRS:
        yield from sorted((CONTROL_PLANE_ROOT / d).rglob("*.py"))
    for f in SCANNED_FILES:
        yield CONTROL_PLANE_ROOT / f


def _strip_comments(source: str) -> str:
    # Drop everything after a '#': enough to keep prose/attribution that mentions
    # vendor names from tripping an import scan, while still catching real imports
    # (a commented-out `import mlx` is not an import anyway).
    return "\n".join(line.split("#", 1)[0] for line in source.splitlines())


def test_no_vendor_imports_in_control_plane():
    offenders = []
    for path in _python_files():
        code = _strip_comments(path.read_text(encoding="utf-8"))
        if FORBIDDEN.search(code):
            offenders.append(str(path.relative_to(CONTROL_PLANE_ROOT)))
    assert not offenders, f"vendor imports found in control plane: {offenders}"


def test_thinking_module_imports_without_mlx():
    import sys

    # mlx is not installed in CI; the lifted thinking.py must still import and
    # expose its pure-Python helper.
    module = importlib.import_module("infermesh.api.thinking")
    assert hasattr(module, "extract_thinking")
    assert "mlx" not in sys.modules


def test_control_plane_modules_import_clean():
    for name in (
        "infermesh.core.backend",
        "infermesh.core.pool",
        "infermesh.core.factory",
        "infermesh.core.registry",
        "infermesh.core.memory",
        "infermesh.core.settings",
        "infermesh.api.adapters",
        "infermesh.server",
        "infermesh.cli",
    ):
        importlib.import_module(name)

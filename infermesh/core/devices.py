# SPDX-License-Identifier: Apache-2.0
"""Enumerate local compute devices for the dashboard's GPU picker.

Vendor-free: probes via the vendor CLIs (``nvidia-smi`` / ``rocm-smi``) over
subprocess — no ``torch`` or vendor SDK — so the control plane stays
import-clean. A ``cpu`` entry is always included. Each device is a dict:
``{id, vendor, name, mem_total_mb, mem_used_mb, mem_free_mb}`` where ``id`` is
what you'd pass as ``ModelSpec.extra["device"]`` (e.g. ``"cuda:0"``).
"""

from __future__ import annotations

import subprocess
from typing import Optional


def _run(cmd: list[str]) -> Optional[str]:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def _nvidia() -> list[dict]:
    out = _run([
        "nvidia-smi",
        "--query-gpu=index,name,memory.total,memory.used,memory.free",
        "--format=csv,noheader,nounits",
    ])
    if not out:
        return []
    devices: list[dict] = []
    for line in out.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 5:
            continue
        idx, name, total, used, free = parts[:5]
        try:
            devices.append({
                "id": f"cuda:{idx}", "vendor": "nvidia", "name": name,
                "mem_total_mb": int(float(total)),
                "mem_used_mb": int(float(used)),
                "mem_free_mb": int(float(free)),
            })
        except ValueError:
            continue
    return devices


def _amd() -> list[dict]:
    # rocm-smi output format varies across versions; best-effort (untested here):
    # detect presence + GPU names, leave VRAM at 0 when we can't parse it reliably.
    out = _run(["rocm-smi", "--showproductname"])
    if not out:
        return []
    names = [
        line.split(":", 1)[-1].strip()
        for line in out.splitlines()
        if "series" in line.lower() or "card" in line.lower()
    ]
    names = [n for n in names if n] or ["AMD GPU"]
    return [
        {"id": f"rocm:{i}", "vendor": "amd", "name": name,
         "mem_total_mb": 0, "mem_used_mb": 0, "mem_free_mb": 0}
        for i, name in enumerate(names)
    ]


def _enflame() -> list[dict]:
    """Enflame GCU accelerators (e.g. S60) via the ``efsmi`` CLI. Best-effort parse
    of the management table: pair each ``Enflame <model>`` line with its ``NNNNMiB``
    total-memory token. Stays vendor-free (subprocess only, no torch/SDK import)."""
    out = _run(["efsmi"])
    if not out:
        return []
    import re
    devices: list[dict] = []
    name: Optional[str] = None
    for line in out.splitlines():
        m = re.search(r"Enflame\s+[A-Za-z0-9-]+", line)
        if m:
            name = m.group(0).strip()
        mem = re.search(r"(\d{3,})\s*MiB", line)
        if name and mem:
            total = int(mem.group(1))
            devices.append({
                "id": f"gcu:{len(devices)}", "vendor": "enflame", "name": name,
                "mem_total_mb": total, "mem_used_mb": 0, "mem_free_mb": total,
            })
            name = None
    return devices


def enumerate_devices() -> list[dict]:
    """Detected accelerators (NVIDIA, AMD, Enflame GCU) followed by a ``cpu`` entry."""
    devices = _nvidia() + _amd() + _enflame()
    devices.append({
        "id": "cpu", "vendor": "cpu", "name": "CPU",
        "mem_total_mb": 0, "mem_used_mb": 0, "mem_free_mb": 0,
    })
    return devices

# SPDX-License-Identifier: Apache-2.0
"""infermesh control plane — ZERO vendor imports (no mlx, no torch).

Everything hardware-specific lives under ``infermesh.backends`` behind the
``InferenceBackend`` interface defined in :mod:`infermesh.core.backend`.
"""

# SPDX-License-Identifier: Apache-2.0
"""ModelRegistry — discover servable models under a --model-dir into ModelSpecs.

Supports flat (``model-dir/<model>/``) and two-level (``model-dir/<org>/<model>/``)
layouts, like oMLX. Model type is detected from ``config.json`` when present
(lightweight, no vendor SDK). Directories with no recognizable model files are
still registered (so tests can use empty fixture dirs).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from infermesh.core.backend import ModelSpec

# Files whose presence marks a directory as an actual model (vs. an org folder).
_MODEL_FILE_GLOBS = (
    "config.json",
    "*.safetensors",
    "*.gguf",
    "*.bin",
    "tokenizer.json",
    "params.json",
)


class ModelRegistry:
    def __init__(self, default_backend: Optional[str] = None) -> None:
        self.default_backend = default_backend

    def discover(self, model_dir: object) -> list[ModelSpec]:
        """Scan ``model_dir`` one or two levels deep and return ModelSpecs."""
        root = Path(str(model_dir)).expanduser()
        if not root.is_dir():
            return []

        specs: list[ModelSpec] = []
        for child in sorted(p for p in root.iterdir() if p.is_dir()):
            if self._is_model_dir(child):
                specs.append(self._make_spec(child.name, child))
                continue
            # Maybe an org folder: register any model subdirectories as org/model.
            grandchildren = [
                g for g in sorted(child.iterdir())
                if g.is_dir() and self._is_model_dir(g)
            ]
            if grandchildren:
                for g in grandchildren:
                    specs.append(self._make_spec(f"{child.name}/{g.name}", g))
            else:
                # Empty/fixture directory — still a servable id.
                specs.append(self._make_spec(child.name, child))
        return specs

    @staticmethod
    def _is_model_dir(path: Path) -> bool:
        return any(any(path.glob(pattern)) for pattern in _MODEL_FILE_GLOBS)

    def _make_spec(self, model_id: str, path: Path) -> ModelSpec:
        model_type = "llm"
        max_context: Optional[int] = None
        config_path = path / "config.json"
        if config_path.is_file():
            try:
                config = json.loads(config_path.read_text())
            except (json.JSONDecodeError, OSError):
                config = {}
            if isinstance(config, dict):
                model_type = self._detect_model_type(config)
                max_context = self._detect_context(config)
        return ModelSpec(
            model_id=model_id,
            source=str(path),
            model_type=model_type,
            max_context=max_context,
            backend=self.default_backend,
        )

    @staticmethod
    def _detect_model_type(config: dict) -> str:
        """Lightweight model_type detection from config.json (no mlx)."""
        archs = " ".join(config.get("architectures") or []).lower()
        blob = archs + " " + str(config.get("model_type", "")).lower()
        if "rerank" in blob:
            return "reranker"
        if any(k in blob for k in ("embedding", "bert", "roberta", "bge", "gte", "e5")):
            return "embedding"
        if any(k in blob for k in ("vl", "vision", "llava", "clip", "image", "vlm")):
            return "vlm"
        return "llm"

    @staticmethod
    def _detect_context(config: dict) -> Optional[int]:
        for key in (
            "max_position_embeddings",
            "max_sequence_length",
            "n_positions",
            "model_max_length",
        ):
            value = config.get(key)
            if isinstance(value, int) and value > 0:
                return value
        return None

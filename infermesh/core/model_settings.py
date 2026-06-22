# SPDX-License-Identifier: Apache-2.0
"""Per-model generation overrides, persisted to ``~/.infermesh/model_settings.json``.

A model's overrides take precedence over the global generation defaults but still
yield to a value the client sent explicitly (request > per-model > global >
adapter fallback). ``max_context_window`` lets a model reject over-long prompts.

This is a control-plane store -- plain JSON, no tokenizer or vendor SDK.
"""

from __future__ import annotations

import json
from pathlib import Path

from infermesh.core.settings import HOME_DIR

MODEL_SETTINGS_FILE = HOME_DIR / "model_settings.json"

#: Fields an override may carry. ``max_context_window`` is enforced separately
#: (it is not a sampling parameter); the rest fill omitted request fields.
FIELDS = ("temperature", "top_p", "top_k", "max_tokens", "max_context_window")
SAMPLING_FIELDS = ("temperature", "top_p", "top_k", "max_tokens")


class ModelSettingsStore:
    """A persisted ``{model_id: {field: value}}`` map of per-model overrides."""

    def __init__(self, path: Path = MODEL_SETTINGS_FILE):
        self._path = Path(path)
        self._data: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        try:
            if self._path.exists():
                d = json.loads(self._path.read_text())
                if isinstance(d, dict):
                    self._data = {k: dict(v) for k, v in d.items() if isinstance(v, dict)}
        except (json.JSONDecodeError, OSError):
            self._data = {}

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(self._data, indent=2, sort_keys=True))
        except OSError:
            pass

    def get(self, model_id: str) -> dict:
        return dict(self._data.get(model_id, {}))

    def all(self) -> dict:
        return {k: dict(v) for k, v in self._data.items()}

    def set(self, model_id: str, **fields) -> dict:
        """Apply ``fields`` to a model. A value of ``None`` clears that field; a
        model left with no fields is dropped entirely."""
        cur = self._data.setdefault(model_id, {})
        for key, value in fields.items():
            if key not in FIELDS:
                continue
            if value is None:
                cur.pop(key, None)
            else:
                cur[key] = value
        if not cur:
            self._data.pop(model_id, None)
        self._save()
        return self.get(model_id)

    def clear(self, model_id: str) -> None:
        if self._data.pop(model_id, None) is not None:
            self._save()

# SPDX-License-Identifier: Apache-2.0
"""Guard: embedding/encoder checkpoints are detected before any device op, so a
non-generative model can't reach the accelerator, fault its driver, and abort the
whole server (which is what crashed it when all-MiniLM-L6-v2 was benchmarked)."""

import json

from infermesh.backends.transformers.transformers_backend import TransformersBackend
from infermesh.core.backend import UnsupportedModelError


def _model(tmp_path, **cfg):
    (tmp_path / "config.json").write_text(json.dumps(cfg))
    return str(tmp_path)


def test_detects_bert_embedding(tmp_path):
    # all-MiniLM-L6-v2 ships config.json model_type "bert", architectures ["BertModel"]
    assert TransformersBackend._detect_embedding(
        _model(tmp_path, model_type="bert", architectures=["BertModel"]))


def test_detects_sentence_transformers_markers(tmp_path):
    (tmp_path / "modules.json").write_text("[]")
    (tmp_path / "config.json").write_text("{}")
    assert TransformersBackend._detect_embedding(str(tmp_path))


def test_allows_genuine_causal_lm(tmp_path):
    assert not TransformersBackend._detect_embedding(
        _model(tmp_path, model_type="qwen2", architectures=["Qwen2ForCausalLM"]))


def test_allows_bert_with_causal_head(tmp_path):
    # a genuinely generative BertLMHeadModel checkpoint (rare) is allowed through
    assert not TransformersBackend._detect_embedding(
        _model(tmp_path, model_type="bert", architectures=["BertLMHeadModel"]))


def test_missing_config_is_not_flagged(tmp_path):
    assert TransformersBackend._detect_embedding(str(tmp_path)) is False


def test_unsupported_error_is_runtimeerror():
    assert issubclass(UnsupportedModelError, RuntimeError)

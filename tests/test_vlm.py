# SPDX-License-Identifier: Apache-2.0
"""VLM (M15): multimodal image extraction through the adapters + the image loader.
No model/torch needed; the PIL-dependent test skips if Pillow is absent."""

import base64
import io

import pytest

from infermesh.api.adapters import AnthropicAdapter, OpenAIAdapter
from infermesh.api.anthropic_models import MessagesRequest
from infermesh.api.multimodal import extract_anthropic_images, extract_openai_images
from infermesh.api.openai_models import ChatCompletionRequest
from infermesh.backends.transformers.transformers_backend import TransformersBackend


def test_openai_adapter_extracts_image():
    req = ChatCompletionRequest(model="m", messages=[{"role": "user", "content": [
        {"type": "text", "text": "what is this?"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}}]}])
    ir = OpenAIAdapter().parse_request(req)
    assert ir.messages[-1].images == ["data:image/png;base64,AAA"]
    assert "what is this" in ir.messages[-1].content


def test_anthropic_adapter_extracts_image():
    req = MessagesRequest(model="m", max_tokens=16, messages=[{"role": "user", "content": [
        {"type": "text", "text": "hi"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "BBB"}}]}])
    ir = AnthropicAdapter().parse_request(req)
    assert ir.messages[-1].images == ["data:image/jpeg;base64,BBB"]


def test_extract_helpers_handle_dicts_and_none():
    assert extract_openai_images("plain text") is None
    assert extract_openai_images([{"type": "text", "text": "x"}]) is None
    assert extract_openai_images([{"type": "image_url", "image_url": {"url": "http://x/a.png"}}]) == ["http://x/a.png"]
    assert extract_anthropic_images([{"type": "image", "source": {"type": "url", "url": "http://x/b.png"}}]) == ["http://x/b.png"]


def test_vision_capability_default_off():
    assert TransformersBackend().capabilities().vision is False


def test_image_loader_base64():
    Image = pytest.importorskip("PIL.Image")
    buf = io.BytesIO()
    Image.new("RGB", (3, 3), (0, 128, 255)).save(buf, "PNG")
    url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    imgs = TransformersBackend._load_images([url])
    assert len(imgs) == 1 and imgs[0].size == (3, 3) and imgs[0].mode == "RGB"

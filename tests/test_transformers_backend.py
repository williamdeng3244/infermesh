# SPDX-License-Identifier: Apache-2.0
"""TransformersBackend: registration, caps, prompt building, tool wiring (no torch) (M10)."""

from infermesh.api.adapters.base import InternalMessage, InternalRequest
from infermesh.backends.transformers.transformers_backend import TransformersBackend
from infermesh.core.backend import ModelSpec
from infermesh.core.factory import BackendFactory


class _FakeTok:
    """Minimal tokenizer stand-in (no torch, no has_tool_calling)."""
    chat_template = "present"

    def apply_chat_template(self, messages, tools=None, add_generation_prompt=True, tokenize=False):
        head = f"[tools={len(tools)}]" if tools else ""
        return head + "".join(f"<{m['role']}>{m['content']}" for m in messages) + "<assistant>"


def test_factory_resolves_transformers():
    b = BackendFactory().create(ModelSpec(model_id="x", source="x", backend="transformers"))
    assert b.backend_name == "transformers"
    caps = b.capabilities()
    assert caps.streaming and caps.tool_calling and not caps.embeddings


def test_hardware_never_raises():
    # Works whether or not torch is installed; degrades to cpu when absent.
    assert TransformersBackend().hardware().vendor in ("nvidia", "amd", "apple", "cpu")


def test_build_prompt_uses_chat_template():
    b = TransformersBackend()
    b._tokenizer = _FakeTok()
    b._spec = ModelSpec(model_id="m", source="m", backend="transformers")
    p = b._build_prompt(InternalRequest(messages=[InternalMessage(role="user", content="hi")]))
    assert "<user>hi" in p and p.endswith("<assistant>")


def test_parse_tools_wires_family_parser():
    b = TransformersBackend()
    b._tokenizer = _FakeTok()
    req = InternalRequest(
        messages=[InternalMessage(role="user", content="weather?")],
        tools=[{"type": "function", "function": {"name": "get_weather", "parameters": {}}}],
    )
    text = '<tool_call>{"name": "get_weather", "arguments": {"city": "Paris"}}</tool_call>'
    cleaned, calls, finish = b._parse_tools(text, req)
    assert finish == "tool_calls"
    assert calls and calls[0]["function"]["name"] == "get_weather"   # dict via model_dump()
    assert "Paris" in calls[0]["function"]["arguments"]


def test_parse_tools_noop_without_tools():
    b = TransformersBackend()
    b._tokenizer = _FakeTok()
    req = InternalRequest(messages=[InternalMessage(role="user", content="hi")])
    text, calls, finish = b._parse_tools("hello", req)
    assert calls is None and finish == "stop" and text == "hello"

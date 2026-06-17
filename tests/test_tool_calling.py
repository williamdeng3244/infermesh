# SPDX-License-Identifier: Apache-2.0
"""Family tool-call parsers — activated by the in-process Transformers backend (M10).

These run with no tokenizer hooks (a plain object lacks ``has_tool_calling``), so
``parse_tool_calls`` takes the generic text-pattern path — exactly what a local
raw-text backend relies on.
"""

import json

from infermesh.api.tool_calling import parse_tool_calls

TOOLS = [{"type": "function", "function": {
    "name": "get_weather",
    "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
}}]


class _DummyTok:  # no has_tool_calling -> generic XML/Hermes/bracket fallback
    pass


def test_parse_qwen_xml_tool_call():
    text = ('Sure, let me check.\n'
            '<tool_call>\n{"name": "get_weather", "arguments": {"city": "Paris"}}\n</tool_call>')
    cleaned, calls = parse_tool_calls(text, _DummyTok(), TOOLS)
    assert calls and len(calls) == 1
    assert calls[0].function.name == "get_weather"
    assert json.loads(calls[0].function.arguments)["city"] == "Paris"
    assert "<tool_call>" not in cleaned


def test_no_tool_call_returns_none():
    cleaned, calls = parse_tool_calls("Just a plain answer, no tools.", _DummyTok(), TOOLS)
    assert calls is None
    assert "plain answer" in cleaned

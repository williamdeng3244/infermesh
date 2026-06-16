# SPDX-License-Identifier: Apache-2.0
"""
Thinking/reasoning content parser for separating <think>...</think> blocks.

Provides both streaming (ThinkingParser) and non-streaming (extract_thinking)
interfaces for separating reasoning content from regular response content.

Used by reasoning models like DeepSeek R1, Qwen3/3.5, MiniMax that wrap
their chain-of-thought reasoning in <think>...</think> tags.
"""

import re
from collections.abc import Callable, Sequence
from typing import List, Optional, Tuple

# Tags used for thinking blocks
_OPEN_TAG = "<think>"
_CLOSE_TAG = "</think>"
_OPEN_LEN = len(_OPEN_TAG)   # 7
_CLOSE_LEN = len(_CLOSE_TAG)  # 8
_MINIMAX_OPEN_TAG = "<mm:think>"
_MINIMAX_CLOSE_TAG = "</mm:think>"

# Regex for non-streaming extraction (complete text)
_THINKING_PATTERN = re.compile(r'<think>(.*?)</think>', re.DOTALL)
# Handle case where <think> is missing but </think> is present
# (scheduler prepends <think>\n but the tag may be split)
_THINKING_TAIL_PATTERN = re.compile(r'^(.*?)</think>', re.DOTALL)


def _safe_tokenizer_attr(tokenizer, attr: str, default=None):
    if tokenizer is None:
        return default
    try:
        return getattr(tokenizer, attr, default)
    except (AttributeError, TypeError, ValueError):
        return default


def _single_token_id(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _convert_token_to_id(tokenizer, token: str) -> int | None:
    convert = _safe_tokenizer_attr(tokenizer, "convert_tokens_to_ids")
    if not callable(convert):
        return None
    try:
        token_id = convert(token)
    except (AttributeError, KeyError, TypeError, ValueError):
        return None
    if token_id == _safe_tokenizer_attr(tokenizer, "unk_token_id"):
        return None
    return _single_token_id(token_id)


def _encode_prompt_ids(tokenizer, prompt: str) -> list[int] | None:
    encode = _safe_tokenizer_attr(tokenizer, "encode")
    if not callable(encode):
        return None
    try:
        return list(encode(prompt, add_special_tokens=False))
    except TypeError:
        try:
            return list(encode(prompt))
        except Exception:
            return None
    except Exception:
        return None


def _think_end_token_ids(tokenizer) -> list[int] | None:
    think_end_id = _single_token_id(_safe_tokenizer_attr(tokenizer, "think_end_id"))
    if think_end_id is not None:
        return [think_end_id]

    think_end_tag = _safe_tokenizer_attr(tokenizer, "think_end", _CLOSE_TAG)
    encoded = _encode_prompt_ids(tokenizer, think_end_tag or _CLOSE_TAG)
    if encoded:
        return encoded

    token_id = _convert_token_to_id(tokenizer, _CLOSE_TAG)
    if token_id is not None:
        return [token_id]
    return None


def prompt_opens_thinking(
    tokenizer,
    prompt: str,
    prompt_token_ids: Sequence[int] | None = None,
) -> tuple[bool, str]:
    """Return whether a raw prompt would make the engine prepend ``<think>``.

    Presentation-layer stripping must mirror the engine/scheduler decision, not
    just the raw text suffix. Some prompts can contain a literal ``<think>``
    without tokenizing to the model's think-start id, and templates can leave
    the think-start token in the final token tail without the raw string ending
    in the visible tag. When the caller already has prompt ids from the same
    tokenizer path as the scheduler, those ids are authoritative.
    """
    think_tag = (
        _safe_tokenizer_attr(tokenizer, "think_start", _OPEN_TAG) or _OPEN_TAG
    )
    if tokenizer is None:
        return prompt.rstrip().endswith(think_tag), think_tag

    think_start_id = _single_token_id(
        _safe_tokenizer_attr(tokenizer, "think_start_id")
    )
    if think_start_id is None:
        think_start_id = _convert_token_to_id(tokenizer, think_tag)
    if think_start_id is None:
        return False, think_tag

    if prompt_token_ids is None:
        prompt_ids = _encode_prompt_ids(tokenizer, prompt)
    else:
        prompt_ids = list(prompt_token_ids)
    if not prompt_ids or not think_start_id:
        return False, think_tag

    last_tokens = list(prompt_ids[-3:])
    if think_start_id not in last_tokens:
        return False, think_tag

    last_idx = len(last_tokens) - 1 - last_tokens[::-1].index(think_start_id)
    after_start = last_tokens[last_idx + 1 :]

    if after_start:
        think_end_ids = _think_end_token_ids(tokenizer)
        if think_end_ids and think_end_ids[0] in after_start:
            return False, think_tag

    return True, think_tag


def extract_thinking(text: str) -> Tuple[str, str]:
    """Extract thinking and content from complete text.

    Handles:
    - Normal: ``<think>reasoning</think>answer`` → ``("reasoning", "answer")``
    - No thinking: ``just answer`` → ``("", "just answer")``
    - Partial (no open tag): ``reasoning</think>answer`` → ``("reasoning", "answer")``
    - Empty think: ``<think></think>answer`` → ``("", "answer")``
    - Think only: ``<think>reasoning</think>`` → ``("reasoning", "")``
    - Malformed (open with no close): ``<think>everything…`` →
      ``("", "everything…")`` — recovery for V4-style models that
      occasionally skip the ``</think>`` boundary token. Without this
      fallback the entire body would be classified as thinking and the
      visible answer would be empty.

    Tag-free text is always classified as content. Mirrors
    ``ThinkingParser.finish()`` recovery semantics (`_content_emitted`
    fallback): when the model emits no thinking markers, surface the body
    as the answer so the response is never empty.

    Args:
        text: Complete model output text.

    Returns:
        Tuple of (thinking_content, regular_content).
    """
    if not text:
        return ("", "")

    text = text.replace(_MINIMAX_OPEN_TAG, _OPEN_TAG).replace(
        _MINIMAX_CLOSE_TAG, _CLOSE_TAG
    )

    thinking_parts = []
    remaining = text

    # Extract all <think>...</think> blocks
    while True:
        match = _THINKING_PATTERN.search(remaining)
        if not match:
            break
        thinking_parts.append(match.group(1))
        remaining = remaining[:match.start()] + remaining[match.end():]

    if thinking_parts:
        thinking = "\n".join(thinking_parts).strip()
        return (thinking, remaining.strip())

    # Handle partial: content before </think> without <think> tag
    if '</think>' in text and '<think>' not in text:
        match = _THINKING_TAIL_PATTERN.match(text)
        if match:
            thinking = match.group(1).strip()
            remaining = text[match.end():].strip()
            return (thinking, remaining)

    # Malformed: <think> opened but never closed. Drop the open tag and
    # treat the remainder as content so the answer body is not empty.
    if '<think>' in text and '</think>' not in text:
        idx = text.index('<think>')
        before = text[:idx]
        after = text[idx + _OPEN_LEN:]
        return ("", (before + after).strip())

    return ("", text)


class ThinkingParser:
    """Stateful streaming parser for separating <think>...</think> from content.

    Handles streaming chunks where tags may span multiple chunks.
    Returns (thinking_delta, content_delta) tuples for each feed() call.

    Example::

        parser = ThinkingParser()

        # Chunk 1: "<think>Let me"
        t, c = parser.feed("<think>Let me")
        # t = "Let me", c = ""

        # Chunk 2: " think</think>Answer"
        t, c = parser.feed(" think</think>Answer")
        # t = " think", c = "Answer"

        # Flush remaining
        t, c = parser.finish()
    """

    def __init__(self, start_in_thinking: bool = False):
        self._in_thinking: bool = start_in_thinking
        self._buffer: str = ""  # Buffer for potential partial tags
        # Recovery state for malformed thinking: when the prompt prepends
        # ``<think>`` and the model never emits ``</think>`` before EOS,
        # everything we streamed went out as thinking. The streamed events
        # cannot be retracted, so finish() emits the accumulated thinking
        # text once more as content — the client will show both panels but
        # the answer body is no longer empty.
        self._close_seen: bool = False
        self._thinking_accumulated: List[str] = []
        self._content_emitted: bool = False

    def feed(self, text: str) -> Tuple[str, str]:
        """Feed a text chunk, return (thinking_delta, content_delta).

        Args:
            text: New text chunk from model output.

        Returns:
            Tuple of (thinking_text, content_text) extracted from this chunk.
        """
        if not text:
            return ("", "")

        # Prepend any buffered partial tag content
        text = self._buffer + text
        self._buffer = ""

        thinking_out = []
        content_out = []

        i = 0
        while i < len(text):
            if text[i] == '<':
                # Check if this could be a tag start
                remaining = text[i:]

                # Try to match <think>
                if remaining.startswith(_OPEN_TAG):
                    self._in_thinking = True
                    i += _OPEN_LEN
                    continue

                # Try to match </think>
                if remaining.startswith(_CLOSE_TAG):
                    self._in_thinking = False
                    self._close_seen = True
                    i += _CLOSE_LEN
                    continue

                # Check if it could be a partial tag (not enough chars yet)
                if self._could_be_tag(remaining):
                    # Buffer the rest and wait for more data
                    self._buffer = remaining
                    break

                # Not a tag, emit the '<' as regular content
                if self._in_thinking:
                    thinking_out.append('<')
                else:
                    content_out.append('<')
                i += 1
            else:
                if self._in_thinking:
                    thinking_out.append(text[i])
                else:
                    content_out.append(text[i])
                i += 1

        thinking_delta = "".join(thinking_out)
        content_delta = "".join(content_out)
        if thinking_delta:
            self._thinking_accumulated.append(thinking_delta)
        if content_delta:
            self._content_emitted = True
        return (thinking_delta, content_delta)

    def finish(self) -> Tuple[str, str]:
        """Flush any remaining buffered content.

        Should be called when the stream is complete to emit any
        buffered characters that were waiting for potential tag completion.
        Also recovers from malformed thinking — when the model never
        emitted ``</think>`` and no content was ever produced, returns
        the accumulated thinking text as content so the client surfaces
        a non-empty answer body.

        Returns:
            Tuple of (thinking_text, content_text) from remaining buffer
            (plus recovered content if applicable).
        """
        partial = self._buffer
        self._buffer = ""

        # Recovery: prompt opened a thinking block (or model echoed
        # ``<think>`` itself), the close tag never arrived, and nothing
        # ever streamed as content. Re-emit the accumulated thinking text
        # as content so the answer body is not empty. The thinking events
        # already streamed live cannot be retracted, so the client sees
        # the same text twice — once in the thinking panel, once as the
        # answer. UX trade-off documented in the chat template plan.
        if (
            self._in_thinking
            and not self._close_seen
            and not self._content_emitted
            and self._thinking_accumulated
        ):
            recovered = "".join(self._thinking_accumulated) + partial
            self._content_emitted = True
            return ("", recovered)

        if not partial:
            return ("", "")

        # Partial tag never completed — emit it as-is in the current mode.
        if self._in_thinking:
            self._thinking_accumulated.append(partial)
            return (partial, "")
        else:
            self._content_emitted = True
            return ("", partial)

    @staticmethod
    def _could_be_tag(text: str) -> bool:
        """Check if text could be the start of a <think> or </think> tag.

        Returns True if text is a proper prefix of either tag but not
        yet a complete match.
        """
        length = len(text)
        if length >= _CLOSE_LEN:
            # Long enough to determine - not a partial tag
            return False

        # Check against both tags
        if _OPEN_TAG[:length] == text:
            return True
        if _CLOSE_TAG[:length] == text:
            return True

        return False

# ──────────────────────────────────────────────────────────────────────────────
# NOTE (infermesh): the oMLX original continued here with a class named
# ThinkingBudgetProcessor — a logits processor for Apple's MLX array framework
# that enforced a thinking-token budget during generation. That is compute-layer
# code (only ever constructed by an in-process MLX engine, which infermesh has
# none of in Milestone 1), so it was removed to keep all of infermesh/api/
# importable with no vendor SDK present, per the control-plane rule. If an MLX
# backend is added later, that class belongs under infermesh/backends/mlx/.
# ──────────────────────────────────────────────────────────────────────────────

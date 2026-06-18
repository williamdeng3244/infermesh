# SPDX-License-Identifier: Apache-2.0
"""Extract image references from OpenAI / Anthropic multimodal message content.

Text extraction stays in the existing adapters (``extract_text_content``); this
only pulls the images they currently drop, returning a flat list of refs (data
URLs, http(s) URLs, or file paths) for a VLM backend to load. Handles both
pydantic content models and plain dicts.
"""

from __future__ import annotations

from typing import Any, List, Optional


def _attr(obj: Any, key: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def extract_openai_images(content: Any) -> Optional[List[str]]:
    """OpenAI content array: parts of ``{type:'image_url', image_url:{url}}``."""
    if not isinstance(content, list):
        return None
    images: List[str] = []
    for part in content:
        if _attr(part, "type") != "image_url":
            continue
        image_url = _attr(part, "image_url")
        url = _attr(image_url, "url") if image_url is not None else None
        if isinstance(url, str) and url:
            images.append(url)
    return images or None


def extract_anthropic_images(content: Any) -> Optional[List[str]]:
    """Anthropic content blocks: ``{type:'image', source:{type:'base64'|'url', ...}}``."""
    if not isinstance(content, list):
        return None
    images: List[str] = []
    for block in content:
        if _attr(block, "type") != "image":
            continue
        source = _attr(block, "source")
        if source is None:
            continue
        stype = _attr(source, "type")
        if stype == "base64":
            media = _attr(source, "media_type") or "image/png"
            data = _attr(source, "data") or ""
            if data:
                images.append(f"data:{media};base64,{data}")
        elif stype == "url":
            url = _attr(source, "url")
            if url:
                images.append(url)
    return images or None

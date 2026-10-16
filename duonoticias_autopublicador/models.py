"""Deprecated: identity helpers now live in extractors.holasalta.keys."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from extractors.holasalta.keys import content_hash, news_key, normalize_url, trace_id, video_key

__all__ = ["DiscoveredItem", "Kind", "content_hash", "news_key", "normalize_url", "trace_id", "video_key"]

Kind = Literal["news", "video_link"]


@dataclass(frozen=True)
class DiscoveredItem:
    key: str
    kind: Kind
    raw: dict[str, Any]

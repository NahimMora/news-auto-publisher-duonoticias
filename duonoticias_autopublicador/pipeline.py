from __future__ import annotations

from typing import Any, Protocol, TypeAlias

ProcessedItem: TypeAlias = dict[str, Any]


class Processor(Protocol):
    def process(self, item: dict[str, Any]) -> ProcessedItem: ...


class PassthroughProcessor:
    """Extension point for future enrichment; intentionally preserves the input."""

    def process(self, item: dict[str, Any]) -> ProcessedItem:
        return dict(item)


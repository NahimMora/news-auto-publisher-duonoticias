from __future__ import annotations

import os
from typing import Any, Mapping

from storage.settings import PipelineSettings


DEFAULT_SALTA_SOURCES = frozenset(
    {
        "eltribuno",
        "ariesonline",
        "eloncesalta",
        "nuevodiariodesalta",
        "fiscalespenalesalta",
        "justiciasalta",
    }
)
SALTA_CATEGORIES = frozenset({"salta", "policial_salta"})


def is_salta_source(source: object, settings: PipelineSettings | None = None) -> bool:
    name = str(source or "").strip().lower()
    if not name:
        return False
    if name in DEFAULT_SALTA_SOURCES:
        return True
    if settings is None:
        return False
    sources = settings.sources_config.get("sources") if isinstance(settings.sources_config, dict) else None
    if not isinstance(sources, list):
        return False
    for item in sources:
        if not isinstance(item, dict):
            continue
        if str(item.get("name") or "").strip().lower() != name:
            continue
        category = str(item.get("category") or "").strip().lower()
        source_type = str(item.get("type") or "").strip().lower()
        return category in SALTA_CATEGORIES or source_type == "local_news"
    return False


def salta_priority_bonus(row: Mapping[str, Any], settings: PipelineSettings | None = None) -> float:
    if not is_salta_source(row.get("source"), settings):
        return 0.0
    raw = os.getenv("DUO_SALTA_PRIORITY_BONUS", "12").strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        return 12.0

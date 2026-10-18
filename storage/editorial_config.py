"""Lectura tipada de config/sources.yaml + config/editorial_scoring.yaml.

Un solo lugar responde a que cupo compite cada fuente, si exige video, que
politica de marcas de agua aplica y cuales son los umbrales, cupos y tiempos de
la cola. El resto del pipeline no lee los YAML directamente.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

from storage.settings import PipelineSettings

GROUPS = ("local", "national", "paparazzi", "x_feed")

_DEFAULT_QUOTAS = {"local": 6, "national": 2, "paparazzi": 2}
_DEFAULT_THRESHOLDS = {"local": 55.0, "local_official": 65.0, "national": 72.0, "paparazzi": 52.0, "x_feed": 55.0}
_DEFAULT_AGE = {"local": 18, "national": 12, "paparazzi": 24, "x_feed": 24}


@dataclass(frozen=True)
class SourceSpec:
    name: str
    display_name: str
    group: str
    category: str = ""
    base_url: str = ""
    parser: str = ""
    enabled: bool = True
    official: bool = False
    requires_video: bool = False
    watermark_policy: str = ""
    max_items_per_scan: int = 10
    feeds: Tuple[str, ...] = ()
    exclude_path_prefixes: Tuple[str, ...] = ()
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EditorialConfig:
    sources: Dict[str, SourceSpec]
    max_per_cycle: int
    group_quotas: Dict[str, int]
    free_slots: int
    free_eligible_groups: Tuple[str, ...]
    max_per_source_per_cycle: int
    max_pieces_per_day: int
    pending_ttl_hours: float
    max_retries: int
    max_content_age_hours: Dict[str, float]
    weights: Dict[str, Dict[str, float]]
    penalties: Dict[str, float]
    thresholds: Dict[str, float]
    batch_size: int
    max_chars_per_item: int
    clip_seconds: float
    max_clips: int
    min_clip_seconds: float
    min_video_seconds: float
    max_download_mb: float
    interval_minutes: float
    align_minute: int
    production_budget_minutes: float
    prompt_version: str
    rate_input_per_million: Optional[float]
    rate_output_per_million: Optional[float]
    model_rates: Dict[str, Tuple[float, float]] = field(default_factory=dict)

    # -- fuentes ------------------------------------------------------------

    def source(self, name: object) -> Optional[SourceSpec]:
        return self.sources.get(str(name or "").strip().lower())

    def group_of(self, source: object, source_type: object = "") -> str:
        spec = self.source(source)
        if spec is not None:
            return spec.group
        if str(source_type or "").lower() == "x_video" or str(source or "").lower().startswith("x"):
            return "x_feed"
        return ""

    def enabled_sources(self) -> List[SourceSpec]:
        return [spec for spec in self.sources.values() if spec.enabled]

    def is_enabled(self, source: object) -> bool:
        spec = self.source(source)
        return bool(spec and spec.enabled)

    def requires_video(self, source: object) -> bool:
        spec = self.source(source)
        return bool(spec and spec.requires_video)

    def is_official(self, source: object) -> bool:
        spec = self.source(source)
        return bool(spec and spec.official)

    def is_local(self, source: object) -> bool:
        return self.group_of(source) == "local"

    def display_name(self, source: object) -> str:
        spec = self.source(source)
        return spec.display_name if spec else str(source or "")

    def threshold_for(self, source: object, source_type: object = "") -> float:
        group = self.group_of(source, source_type)
        if group == "local" and self.is_official(source):
            return float(self.thresholds.get("local_official", self.thresholds.get("local", 55.0)))
        return float(self.thresholds.get(group, 60.0))

    def max_age_hours(self, source: object, source_type: object = "") -> float:
        return float(self.max_content_age_hours.get(self.group_of(source, source_type), 24.0))

    def estimated_cost_usd(self, input_tokens: int, output_tokens: int, model: str = "") -> Optional[float]:
        rates = self.model_rates.get(model)
        if rates is None:
            if self.rate_input_per_million is None or self.rate_output_per_million is None:
                return None
            rates = (self.rate_input_per_million, self.rate_output_per_million)
        return round(input_tokens / 1_000_000 * rates[0] + output_tokens / 1_000_000 * rates[1], 6)


def _section(payload: Mapping[str, Any], key: str) -> Dict[str, Any]:
    value = payload.get(key) if isinstance(payload, Mapping) else None
    return dict(value) if isinstance(value, Mapping) else {}


def _float_or_none(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _sources(settings: PipelineSettings) -> Dict[str, SourceSpec]:
    raw = settings.sources_config.get("sources") if isinstance(settings.sources_config, dict) else None
    specs: Dict[str, SourceSpec] = {}
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip().lower()
        if not name:
            continue
        group = str(item.get("group") or "").strip().lower()
        if group not in GROUPS:
            group = "x_feed" if name == "x" else "local"
        specs[name] = SourceSpec(
            name=name,
            display_name=str(item.get("display_name") or name),
            group=group,
            category=str(item.get("category") or ""),
            base_url=str(item.get("base_url") or "").rstrip("/"),
            parser=str(item.get("parser") or ""),
            enabled=item.get("enabled") is not False,
            official=bool(item.get("official")),
            requires_video=bool(item.get("requires_video")),
            watermark_policy=str(item.get("watermark_policy") or ""),
            max_items_per_scan=int(item.get("max_items_per_scan") or 10),
            feeds=tuple(str(feed) for feed in (item.get("feeds") or []) if feed),
            exclude_path_prefixes=tuple(str(p) for p in (item.get("exclude_path_prefixes") or []) if p),
            raw=dict(item),
        )
    return specs


def load_editorial_config(settings: PipelineSettings) -> EditorialConfig:
    payload = settings.editorial_scoring if isinstance(settings.editorial_scoring, dict) else {}
    cycle = _section(payload, "cycle")
    quotas = _section(payload, "quotas")
    queue = _section(payload, "queue")
    relevance = _section(payload, "relevance")
    media = _section(payload, "media")
    llm = _section(payload, "llm")
    rates = _section(llm, "rates_per_million")
    group_quotas = {**_DEFAULT_QUOTAS, **{k: int(v) for k, v in _section(quotas, "groups").items()}}
    thresholds = {**_DEFAULT_THRESHOLDS, **{k: float(v) for k, v in _section(relevance, "thresholds").items()}}
    ages = {**_DEFAULT_AGE, **{k: float(v) for k, v in _section(queue, "max_content_age_hours").items()}}
    weights = {
        group: {k: float(v) for k, v in dict(values).items()}
        for group, values in _section(relevance, "weights").items()
        if isinstance(values, Mapping)
    }
    return EditorialConfig(
        sources=_sources(settings),
        max_per_cycle=int(quotas.get("max_per_cycle") or 12),
        group_quotas=group_quotas,
        free_slots=int(quotas.get("free") if quotas.get("free") is not None else 2),
        free_eligible_groups=tuple(quotas.get("free_eligible_groups") or ("local", "paparazzi", "x_feed")),
        max_per_source_per_cycle=int(quotas.get("max_per_source_per_cycle") or 3),
        max_pieces_per_day=int(quotas.get("max_pieces_per_day") or 0),
        pending_ttl_hours=float(queue.get("pending_ttl_hours") or 12),
        max_retries=int(queue.get("max_retries") or 3),
        max_content_age_hours=ages,
        weights=weights,
        penalties={k: float(v) for k, v in _section(relevance, "penalties").items()},
        thresholds=thresholds,
        batch_size=max(1, int(relevance.get("batch_size") or 12)),
        max_chars_per_item=max(200, int(relevance.get("max_chars_per_item") or 700)),
        clip_seconds=float(media.get("clip_seconds") or 60),
        max_clips=max(1, int(media.get("max_clips") or 2)),
        min_clip_seconds=float(media.get("min_clip_seconds") or 5),
        min_video_seconds=float(media.get("min_video_seconds") or 5),
        max_download_mb=float(media.get("max_download_mb") or 400),
        interval_minutes=float(cycle.get("interval_minutes") or 60),
        align_minute=int(cycle.get("align_minute") or 0),
        production_budget_minutes=float(cycle.get("production_budget_minutes") or 45),
        prompt_version=str(llm.get("prompt_version") or "duo-v1"),
        rate_input_per_million=_float_or_none(rates.get("input")),
        rate_output_per_million=_float_or_none(rates.get("output")),
        model_rates={
            str(name): (float(value.get("input")), float(value.get("output")))
            for name, value in rates.items()
            if isinstance(value, Mapping) and value.get("input") is not None and value.get("output") is not None
        },
    )

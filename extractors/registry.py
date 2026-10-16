from __future__ import annotations

from typing import Dict, List

from extractors.holasalta.extractor import HolaSaltaExtractor
from extractors.news.ariesonline import AriesOnlineExtractor
from extractors.news.eloncesalta import ElonceSaltaExtractor
from extractors.news.eltribuno import ElTribunoExtractor
from extractors.news.fiscalespenalesalta import FiscalesPenalesSaltaExtractor
from extractors.news.justiciasalta import JusticiaSaltaExtractor
from extractors.news.nuevodiario import NuevoDiarioExtractor
from extractors.news.paparazzi import PaparazziExtractor
from extractors.news.rss_html import RssHtmlNewsExtractor
from storage.models import ExtractedContent
from storage.settings import PipelineSettings, get_settings

# Sources that require specialized HTML scrapers (not generic RSS/HTML)
_SPECIALIZED: Dict[str, type] = {
    "eltribuno": ElTribunoExtractor,
    "ariesonline": AriesOnlineExtractor,
    "eloncesalta": ElonceSaltaExtractor,
    "nuevodiariodesalta": NuevoDiarioExtractor,
    "fiscalespenalesalta": FiscalesPenalesSaltaExtractor,
    "justiciasalta": JusticiaSaltaExtractor,
}


class SourceRegistry:
    def __init__(self, settings: PipelineSettings | None = None) -> None:
        self.settings = settings or get_settings()

    def enabled_source_names(self) -> List[str]:
        sources = self.settings.sources_config.get("sources") if isinstance(self.settings.sources_config, dict) else None
        if not isinstance(sources, list):
            return ["paparazzi", "tn"]
        active = sorted(
            [s for s in sources if isinstance(s, dict) and s.get("enabled") is not False],
            key=lambda s: int(s.get("priority") or 0),
            reverse=True,
        )
        names = [
            str(s.get("name") or "").strip()
            for s in active
            if str(s.get("name") or "").strip() and str(s.get("name") or "").strip() != "x"
        ]
        return names or ["paparazzi", "tn"]

    def scan_source(self, source: str, max_items: int | None = None) -> List[ExtractedContent]:
        source = (source or "").strip().lower()
        config = self._source_config(source)
        if config and config.get("enabled") is False:
            return []
        resolved_max_items = self._resolve_max_items(config, max_items)
        if source == "x":
            return []
        if source == "paparazzi":
            return PaparazziExtractor(self.settings).scan(max_items=resolved_max_items)
        if source == "holasalta":
            category = str((config or {}).get("category") or "salta")
            return HolaSaltaExtractor(self.settings).scan(max_items=resolved_max_items, category=category)
        if source in _SPECIALIZED:
            return _SPECIALIZED[source](self.settings).scan(max_items=resolved_max_items)
        if config or source in {"tn", "infobae", "ambitofinanciero", "elonce", "minutouno", "noticiasargentinas"}:
            return RssHtmlNewsExtractor(source, self.settings).scan(max_items=resolved_max_items)
        return []

    def scan_enabled(self, max_items: int | None = None) -> Dict[str, List[ExtractedContent]]:
        return {source: self.scan_source(source, max_items=max_items) for source in self.enabled_source_names()}

    def holasalta_video_urls(self, max_items: int | None = None) -> List[str]:
        """X links queued in HolaSalta video jobs, if the source opts in."""
        config = self._source_config("holasalta")
        if not config or config.get("enabled") is False or not config.get("include_x_video_jobs"):
            return []
        limit = max_items if max_items is not None else int(config.get("max_x_video_jobs_per_scan") or 0) or None
        return HolaSaltaExtractor(self.settings).video_urls(max_items=limit)

    def _resolve_max_items(self, config: Dict, max_items: int | None) -> int:
        if max_items is not None:
            return max_items
        try:
            val = int((config or {}).get("max_items_per_scan") or 0)
            if val > 0:
                return val
        except Exception:
            pass
        return self.settings.scrape_default_max_items_per_source

    def _source_config(self, source: str) -> Dict[str, object]:
        sources = self.settings.sources_config.get("sources") if isinstance(self.settings.sources_config, dict) else None
        if not isinstance(sources, list):
            return {}
        for item in sources:
            if not isinstance(item, dict):
                continue
            if str(item.get("name") or "").strip().lower() == source:
                return dict(item)
        return {}

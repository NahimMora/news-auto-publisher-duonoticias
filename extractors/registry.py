from __future__ import annotations

import logging
from typing import Dict, List, Optional

from extractors.news.arc import ArcNewsExtractor
from extractors.news.eltribuno import ElTribunoExtractor
from extractors.news.html_scraper import KnownUrl
from extractors.news.informatesalta import InformateSaltaExtractor
from extractors.news.paparazzi import PaparazziExtractor
from extractors.news.quepasasalta import QuePasaSaltaExtractor
from extractors.news.saltagob import SaltaGobExtractor
from extractors.news.wordpress import WordPressNewsExtractor
from storage.editorial_config import EditorialConfig, SourceSpec, load_editorial_config
from storage.models import ExtractedContent
from storage.settings import PipelineSettings, get_settings

LOGGER = logging.getLogger("duo.extractors.registry")

# parser (config/sources.yaml) -> extractor. Las fuentes eliminadas no tienen parser.
_HTML_PARSERS = {
    "eltribuno": ElTribunoExtractor,
    "informatesalta": InformateSaltaExtractor,
    "quepasasalta": QuePasaSaltaExtractor,
    "saltagob": SaltaGobExtractor,
}


class SourceRegistry:
    """Fuentes de noticias activas. Los videos de X (HolaSalta) no pasan por aca."""

    def __init__(self, settings: PipelineSettings | None = None, config: EditorialConfig | None = None) -> None:
        self.settings = settings or get_settings()
        self.config = config or load_editorial_config(self.settings)

    def enabled_source_names(self) -> List[str]:
        return [spec.name for spec in self.config.enabled_sources() if spec.parser and spec.parser != "x_video_feed"]

    def scan_source(self, source: str, max_items: int | None = None, known: Optional[KnownUrl] = None) -> List[ExtractedContent]:
        spec = self.config.source(source)
        if spec is None or not spec.enabled or not spec.parser or spec.parser == "x_video_feed":
            return []
        limit = max_items if max_items is not None else spec.max_items_per_scan
        extractor = self._extractor(spec)
        if extractor is None:
            LOGGER.warning("Fuente %s sin extractor para parser=%s", spec.name, spec.parser)
            return []
        return extractor.scan(max_items=limit, known=known)

    def scan_enabled(self, max_items: int | None = None, known: Optional[KnownUrl] = None) -> Dict[str, List[ExtractedContent]]:
        return {source: self.scan_source(source, max_items=max_items, known=known) for source in self.enabled_source_names()}

    def _extractor(self, spec: SourceSpec):
        if spec.parser in _HTML_PARSERS:
            return _HTML_PARSERS[spec.parser](self.settings)
        if spec.parser == "paparazzi":
            return PaparazziExtractor(self.settings)
        if spec.parser == "wordpress":
            return WordPressNewsExtractor(spec.name, spec.base_url, category=spec.category or "salta", settings=self.settings)
        if spec.parser == "arc":
            return ArcNewsExtractor(
                spec.name,
                base_url=spec.base_url,
                feeds=list(spec.feeds),
                category=spec.category or "nacional",
                exclude_path_prefixes=list(spec.exclude_path_prefixes),
                settings=self.settings,
            )
        return None

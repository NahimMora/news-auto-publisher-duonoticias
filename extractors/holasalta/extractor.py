from __future__ import annotations

import logging
from typing import Any, Dict, List

from extractors.holasalta.client import HolaSaltaClient
from extractors.holasalta.keys import normalize_url
from extractors.news.common import content_from_raw
from storage.models import ExtractedContent
from storage.settings import PipelineSettings, get_settings


class HolaSaltaExtractor:
    """HolaSalta as one more pipeline source.

    News come from ``GET /api/news/`` and enter the pipeline like any other
    extractor. X video jobs (``GET /api/x-video/jobs``) are only returned as
    URLs: the pipeline imports them through the existing X flow so they get
    the same download, scoring and formatting as manual X imports.
    """

    name = "holasalta"
    source_type = "news"

    def __init__(self, settings: PipelineSettings | None = None, *, client: HolaSaltaClient | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = client
        self.logger = logging.getLogger("duo.extractors.holasalta")

    def scan(self, max_items: int | None = None, *, category: str = "salta") -> List[ExtractedContent]:
        limit = max_items if max_items is not None else self.settings.scrape_default_max_items_per_source
        if limit <= 0:
            return []
        news = self._with_client(lambda client: client.get_news())
        rows: List[ExtractedContent] = []
        for item in news[:limit]:
            rows.append(
                content_from_raw(source=self.name, source_type=self.source_type, raw=self._news_raw(item), category=category)
            )
        return rows

    def video_urls(self, max_items: int | None = None) -> List[str]:
        limit = max_items if max_items is not None else self.settings.x_default_items_per_handle
        if limit <= 0:
            return []
        jobs = self._with_client(lambda client: client.get_video_jobs())
        urls: List[str] = []
        for job in jobs:
            url = normalize_url(str(job.get("source_url") or ""))
            if url and url not in urls:
                urls.append(url)
            if len(urls) >= limit:
                break
        return urls

    @staticmethod
    def _news_raw(item: Dict[str, Any]) -> Dict[str, Any]:
        raw = dict(item)
        # The pipeline dedupes on canonical_url; prefer the original source so the
        # same article scraped directly (e.g. El Tribuno) collapses with this one.
        if not raw.get("url"):
            raw["url"] = raw.get("web_url") or raw.get("url_wordpress") or ""
        return raw

    def _with_client(self, call):
        if self._client is not None:
            return call(self._client)
        if not self.settings.hs_api_password:
            raise ValueError("HolaSalta: HS_API_PASSWORD no configurado")
        client = HolaSaltaClient(
            self.settings.hs_api_url,
            self.settings.hs_api_username,
            self.settings.hs_api_password,
        )
        try:
            return call(client)
        finally:
            client.close()

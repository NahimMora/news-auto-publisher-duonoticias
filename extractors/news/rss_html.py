from __future__ import annotations

import logging
import re
from typing import Dict, List

import feedparser
from bs4 import BeautifulSoup

from extractors.news.common import content_from_raw, extract_article_fields, normalize_url, strip_html
from storage.models import ExtractedContent
from storage.settings import PipelineSettings, get_settings
from utils.http_client import HttpClient


SOURCE_DEFAULTS: Dict[str, Dict[str, object]] = {
    "tn": {
        "base_url": "https://tn.com.ar",
        "feeds": ["https://tn.com.ar/rss.xml", "https://tn.com.ar/feed/"],
        "category": "nacional",
    },
    "infobae": {
        "base_url": "https://www.infobae.com",
        "feeds": ["https://www.infobae.com/feeds/rss/"],
        "category": "nacional",
        "article_patterns": [r"/20\d{2}/\d{2}/\d{2}/"],
        "homepage_selectors": ["article a[href]", "h2 a[href]", "h3 a[href]", "a[href]"],
    },
    "ambitofinanciero": {
        "base_url": "https://www.ambito.com",
        "feeds": ["https://www.ambito.com/rss.xml"],
        "category": "economia",
        "article_patterns": [r"-n\d{5,}/?$"],
        "homepage_selectors": [
            "article.news-article h1 a[href]",
            "article.news-article h2 a[href]",
            "article.news-article a[href]",
            "h1 a[href]",
            "h2 a[href]",
            "h3 a[href]",
            "a[href]",
        ],
    },
    "ariesonline": {
        "base_url": "https://ariesonline.com.ar",
        "feeds": ["https://ariesonline.com.ar/feed"],
        "category": "salta",
    },
    "elonce": {
        "base_url": "https://www.elonce.com",
        "feeds": ["https://www.elonce.com/rss.xml"],
        "category": "nacional",
        "article_patterns": [r"\.htm/?$"],
        "homepage_selectors": [
            "article .link-title[href]",
            "article .link-img[href]",
            "article a[href]",
            "h2 a[href]",
            "h3 a[href]",
            "a[href]",
        ],
    },
    "eloncesalta": {
        "base_url": "https://eloncesalta.com.ar",
        "feeds": ["https://eloncesalta.com.ar/feed"],
        "category": "salta",
    },
    "eltribuno": {
        "base_url": "https://www.eltribuno.com",
        "feeds": ["https://www.eltribuno.com/rss.xml"],
        "category": "salta",
    },
    "minutouno": {
        "base_url": "https://www.minutouno.com",
        "feeds": ["https://www.minutouno.com/rss.xml"],
        "category": "nacional",
        "article_patterns": [r"-n\d+"],
        "homepage_selectors": [
            "article a[href]",
            "div[class*=box] a[href]",
            "h1 a[href]",
            "h2 a[href]",
            "h3 a[href]",
            "a[href]",
        ],
    },
    "nuevodiariodesalta": {
        "base_url": "https://www.nuevodiariodesalta.com.ar",
        "feeds": ["https://www.nuevodiariodesalta.com.ar/feed"],
        "category": "salta",
    },
    "noticiasargentinas": {
        "base_url": "https://noticiasargentinas.com",
        "feeds": ["https://noticiasargentinas.com/rss.xml"],
        "category": "nacional",
    },
}


class RssHtmlNewsExtractor:
    source_type = "news"

    def __init__(self, source: str, settings: PipelineSettings | None = None) -> None:
        self.source = source
        self.settings = settings or get_settings()
        self.config = {**dict(SOURCE_DEFAULTS.get(source, {})), **self._source_config(source)}
        self.logger = logging.getLogger(f"duo.extractors.{source}")

    def scan(self, max_items: int | None = None) -> List[ExtractedContent]:
        limit = max_items if max_items is not None else 5
        if limit <= 0:
            return []
        candidates = self._feed_candidates(limit=limit)
        if not candidates:
            candidates = self._homepage_candidates(limit=limit)
        rows: List[ExtractedContent] = []
        for item in candidates[:limit]:
            raw = dict(item)
            url = str(raw.get("url") or "").strip()
            if url:
                try:
                    raw.update(self._article_detail(url, title_hint=str(raw.get("titulo") or "")))
                except Exception as exc:
                    self.logger.warning("%s detail failed: %s", self.source, exc)
            rows.append(
                content_from_raw(
                    source=self.source,
                    source_type=self.source_type,
                    raw=raw,
                    category=str(self.config.get("category") or "nacional"),
                )
            )
        return rows

    def _feed_candidates(self, *, limit: int) -> List[Dict[str, object]]:
        rows: List[Dict[str, object]] = []
        seen = set()
        for feed_url in self.config.get("feeds") or []:
            parsed = feedparser.parse(str(feed_url))
            for entry in parsed.entries or []:
                url = normalize_url(str(getattr(entry, "link", "") or ""))
                if not url or url in seen:
                    continue
                seen.add(url)
                rows.append(
                    {
                        "id": str(getattr(entry, "id", "") or url),
                        "url": url,
                        "titulo": strip_html(str(getattr(entry, "title", "") or "")),
                        "extracto": strip_html(str(getattr(entry, "summary", "") or "")),
                        "fecha_publicacion": str(getattr(entry, "published", "") or getattr(entry, "updated", "") or ""),
                    }
                )
                if len(rows) >= limit:
                    return rows
        return rows

    def _homepage_candidates(self, *, limit: int) -> List[Dict[str, object]]:
        base_url = str(self.config.get("base_url") or "")
        if not base_url:
            return []
        client = HttpClient(timeout=30, retries=2, backoff_base=1)
        try:
            response = client.get(base_url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
        finally:
            client.close()
        rows = []
        seen = set()
        selectors = self.config.get("homepage_selectors") or ["article a[href]", "h1 a[href]", "h2 a[href]", "h3 a[href]", "a[href]"]
        for link in soup.select(", ".join(str(selector) for selector in selectors)):
            url = normalize_url(str(link.get("href") or ""), base_url)
            if not self._looks_like_article(url) or url in seen:
                continue
            title = strip_html(link.get_text(" ", strip=True))
            if not title:
                parent = link.find_parent("article") or link.find_parent(["div", "section"])
                if parent:
                    heading = parent.find(["h1", "h2", "h3", "h4"])
                    title = strip_html(heading.get_text(" ", strip=True)) if heading else ""
            if len(title) < 10:
                continue
            seen.add(url)
            rows.append({"id": url, "url": url, "titulo": title})
            if len(rows) >= limit:
                break
        return rows

    def _article_detail(self, url: str, *, title_hint: str) -> Dict[str, object]:
        client = HttpClient(timeout=30, retries=2, backoff_base=1)
        try:
            response = client.get(url)
            response.raise_for_status()
            fields = extract_article_fields(response.text, url, title_hint=title_hint)
        finally:
            client.close()
        return {
            "title": fields.get("title") or title_hint,
            "summary": fields.get("summary") or "",
            "body_text": fields.get("body_text") or "",
            "image_urls": fields.get("image_urls") or [],
            "video_urls": fields.get("video_urls") or [],
            "published": fields.get("published") or "",
        }

    def _looks_like_article(self, url: str) -> bool:
        base_url = str(self.config.get("base_url") or "")
        if not url.startswith(base_url):
            return False
        lowered = url.lower()
        for token in self.config.get("exclude_patterns") or ("tag/", "/tags/", "/autor/", "/newsletter", "/videos/"):
            if str(token).lower() in lowered:
                return False
        patterns = self.config.get("article_patterns") or []
        for pattern in patterns:
            if re.search(str(pattern), url):
                return True
        return bool(re.search(r"/20\d{2}/\d{2}/\d{2}/", url) or len(url.rstrip("/").split("/")) >= 5)

    def _source_config(self, source: str) -> Dict[str, object]:
        sources = self.settings.sources_config.get("sources") if isinstance(self.settings.sources_config, dict) else []
        if not isinstance(sources, list):
            return {}
        for item in sources:
            if not isinstance(item, dict):
                continue
            if str(item.get("name") or "").strip().lower() == source:
                config = dict(item)
                if config.get("base_url") and not config.get("feeds"):
                    config["feeds"] = [f"{str(config['base_url']).rstrip('/')}/rss.xml", f"{str(config['base_url']).rstrip('/')}/feed"]
                return config
        return {}

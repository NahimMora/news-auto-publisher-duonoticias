"""Base class for HTML-based news extractors (ported from HolaSalta pattern)."""
from __future__ import annotations

import contextlib
import json
import random
import re
import time
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse, urlunparse

import feedparser
import requests
from bs4 import BeautifulSoup

from extractors.news.common import content_from_raw, normalize_url, strip_html
from storage.models import ExtractedContent
from storage.settings import PipelineSettings, get_settings


_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

_COMMON_TEXT_EXCLUDE = (
    "suscribite", "seguinos en", "compartir", "leer más", "ver más",
    "envianos tu noticia", "publicidad", "newsletter", "cookies",
    "términos y condiciones", "política de privacidad",
    "copyright", "todos los derechos", "instagram", "twitter",
    "facebook", "whatsapp", "tiktok", "youtube",
)

_IMAGE_EXCLUDE = (
    "logo", "banner", "publicidad", "ads", "pixel", "tracking",
    "icon", "favicon", "placeholder", "spinner", "loading",
    "gravatar", "avatar", "author",
)


def random_ua() -> str:
    return random.choice(_USER_AGENTS)


def default_headers(referer: str = "") -> Dict[str, str]:
    h = {
        "User-Agent": random_ua(),
        "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Cache-Control": "no-cache",
    }
    if referer:
        h["Referer"] = referer
    return h


def clean_text(text: Optional[str]) -> str:
    if not text:
        return ""
    value = re.sub(r"\s+", " ", str(text)).strip()
    with contextlib.suppress(Exception):
        if any(tok in value for tok in ("Ãƒ", "Ã‚", "Ã¢")):
            value = value.encode("latin1").decode("utf-8")
    return value.strip()


def is_valid_image_url(url: str) -> bool:
    low = url.lower()
    return not any(tok in low for tok in _IMAGE_EXCLUDE)


def extract_json_ld(soup: BeautifulSoup) -> Dict:
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text()
        if not raw:
            continue
        with contextlib.suppress(Exception):
            payload = json.loads(raw)
            items = payload if isinstance(payload, list) else [payload]
            for item in items:
                if isinstance(item, dict):
                    if item.get("@type") in ("NewsArticle", "Article", "WebPage"):
                        return item
                    graph = item.get("@graph")
                    if isinstance(graph, list):
                        for node in graph:
                            if isinstance(node, dict) and node.get("@type") in ("NewsArticle", "Article"):
                                return node
    return {}


def extract_og_image(soup: BeautifulSoup, base_url: str = "") -> str:
    for prop in ("og:image", "twitter:image"):
        tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
        if tag and tag.get("content"):
            src = str(tag["content"]).strip()
            if src and is_valid_image_url(src):
                return normalize_url(src, base_url)
    return ""


def extract_published_date(soup: BeautifulSoup, json_ld: Dict) -> str:
    for meta in (
        soup.find("meta", property="article:published_time"),
        soup.find("meta", itemprop="datePublished"),
        soup.find("meta", attrs={"name": "date"}),
    ):
        if meta and meta.get("content"):
            return str(meta["content"]).strip()
    if json_ld.get("datePublished"):
        return str(json_ld["datePublished"]).strip()
    time_tag = soup.select_one("time[datetime]")
    if time_tag and time_tag.get("datetime"):
        return str(time_tag["datetime"]).strip()
    return ""


def extract_paragraphs(
    soup: BeautifulSoup,
    container_selectors: List[str],
    exclude_tokens: tuple = (),
    min_length: int = 40,
    max_count: int = 8,
) -> List[str]:
    body = None
    for sel in container_selectors:
        body = soup.select_one(sel)
        if body:
            break

    if body is None:
        body = soup.select_one("article") or soup.select_one("main")

    if body is None:
        return []

    all_tokens = _COMMON_TEXT_EXCLUDE + tuple(str(t).lower() for t in exclude_tokens)
    paragraphs: List[str] = []
    seen: set = set()

    for block in body.find_all(["p", "h2", "h3", "li", "blockquote"]):
        text = clean_text(block.get_text(" ", strip=True))
        if not text or len(text) < min_length:
            continue
        low = text.lower()
        if any(tok in low for tok in all_tokens):
            continue
        if text in seen:
            continue
        seen.add(text)
        paragraphs.append(text)
        if len(paragraphs) >= max_count:
            break

    return paragraphs


def fetch_html(url: str, referer: str = "", timeout: int = 20, retries: int = 2) -> Optional[str]:
    headers = default_headers(referer)
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
            if r.ok and r.text:
                return r.text
        except requests.RequestException:
            pass
        if attempt < retries:
            time.sleep(1.5 * attempt + random.uniform(0, 0.5))
    return None


def normalize_article_url(url: str, base_url: str = "") -> str:
    raw = normalize_url(url, base_url)
    parts = urlparse(raw)
    path = parts.path.rstrip("/")
    if path.endswith("/amp"):
        path = path[:-4]
    return urlunparse((parts.scheme or "https", parts.netloc, path, "", "", ""))


class HtmlNewsExtractor:
    """Base class for site-specific HTML news extractors.

    Subclasses must set:
      - source: str
      - base_url: str
      - category: str
      - rss_feeds: List[str]
      - article_url_patterns: List[str] — regexes that match valid article paths
      - article_url_exclude: List[str] — tokens to skip in URLs
      - article_body_selectors: List[str] — CSS selectors for the article body
      - homepage_card_selectors: List[str] — CSS selectors to find article links on homepage
    """

    source: str = ""
    base_url: str = ""
    category: str = "nacional"
    rss_feeds: List[str] = []
    article_url_patterns: List[str] = []
    article_url_exclude: List[str] = [
        "tag/", "/tags/", "/autor/", "/newsletter", "/categoria/",
        "/seccion/", "/#", "/page/", "/video/", "?", "=",
    ]
    article_body_selectors: List[str] = [
        ".article-body", ".article__body", ".articulo__cuerpo",
        ".news-body", ".entry-content", "article .content",
        ".post-content", ".nota-cuerpo", "article",
    ]
    homepage_card_selectors: List[str] = [
        "article a[href]", "h1 a[href]", "h2 a[href]", "h3 a[href]",
    ]

    def __init__(self, settings: Optional[PipelineSettings] = None) -> None:
        self.settings = settings or get_settings()

    def scan(self, max_items: int = 10) -> List[ExtractedContent]:
        limit = max(1, max_items)
        candidates = self._rss_candidates(limit)
        if not candidates:
            candidates = self._homepage_candidates(limit)
        results: List[ExtractedContent] = []
        for item in candidates[:limit]:
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            with contextlib.suppress(Exception):
                detail = self._article_detail(url, title_hint=str(item.get("titulo") or ""))
                item.update(detail)
            results.append(
                content_from_raw(
                    source=self.source,
                    source_type="news",
                    raw=item,
                    category=self.category,
                )
            )
        return results

    def _rss_candidates(self, limit: int) -> List[Dict]:
        rows: List[Dict] = []
        seen: set = set()
        for feed_url in self.rss_feeds:
            try:
                parsed = feedparser.parse(str(feed_url))
                for entry in parsed.entries or []:
                    url = normalize_article_url(str(getattr(entry, "link", "") or ""), self.base_url)
                    if not url or url in seen or not self._is_article_url(url):
                        continue
                    seen.add(url)
                    rows.append({
                        "id": str(getattr(entry, "id", "") or url),
                        "url": url,
                        "titulo": strip_html(str(getattr(entry, "title", "") or "")),
                        "extracto": strip_html(str(getattr(entry, "summary", "") or "")),
                        "fecha_publicacion": str(getattr(entry, "published", "") or getattr(entry, "updated", "") or ""),
                    })
                    if len(rows) >= limit:
                        return rows
            except Exception:
                continue
        return rows

    def _homepage_candidates(self, limit: int) -> List[Dict]:
        html = fetch_html(self.base_url, referer=self.base_url)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        rows: List[Dict] = []
        seen: set = set()
        for selector in self.homepage_card_selectors:
            for link in soup.select(selector):
                href = link.get("href") or ""
                url = normalize_article_url(str(href), self.base_url)
                if not url or url in seen or not self._is_article_url(url):
                    continue
                title = clean_text(link.get_text(" ", strip=True))
                if len(title) < 8:
                    parent = link.find_parent(["article", "div", "li"])
                    if parent:
                        h = parent.find(["h1", "h2", "h3", "h4"])
                        if h:
                            title = clean_text(h.get_text(" ", strip=True))
                if len(title) < 10:
                    continue
                seen.add(url)
                rows.append({"id": url, "url": url, "titulo": title})
                if len(rows) >= limit:
                    return rows
        return rows

    def _article_detail(self, url: str, title_hint: str = "") -> Dict:
        html = fetch_html(url, referer=self.base_url)
        if not html:
            return {}
        soup = BeautifulSoup(html, "html.parser")
        json_ld = extract_json_ld(soup)

        title = (
            clean_text(soup.select_one("h1") and soup.select_one("h1").get_text(" ", strip=True))
            or clean_text(str(json_ld.get("headline") or ""))
            or title_hint
        )
        extracto = (
            clean_text(str(json_ld.get("description") or ""))
            or clean_text(str((soup.find("meta", property="og:description") or {}).get("content") or ""))
            or ""
        )
        parrafos = extract_paragraphs(soup, self.article_body_selectors)
        image_url = extract_og_image(soup, self.base_url)
        published = extract_published_date(soup, json_ld)

        return {
            "titulo": title or title_hint,
            "extracto": extracto,
            "parrafos": parrafos,
            "imagenes_url": [image_url] if image_url else [],
            "fecha_publicacion": published,
        }

    def _is_article_url(self, url: str) -> bool:
        if not url or not url.startswith(self.base_url):
            return False
        low = url.lower()
        for tok in self.article_url_exclude:
            if str(tok).lower() in low:
                return False
        if self.article_url_patterns:
            return any(re.search(p, url) for p in self.article_url_patterns)
        path = urlparse(url).path.rstrip("/")
        return len(path.split("/")) >= 3

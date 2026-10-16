"""Elonce Salta extractor — adapted from HolaSalta scraper pattern."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from extractors.news.html_scraper import (
    HtmlNewsExtractor,
    clean_text,
    extract_json_ld,
    extract_og_image,
    extract_published_date,
    fetch_html,
    normalize_article_url,
)
from extractors.news.common import normalize_url, strip_html
from storage.settings import PipelineSettings

# Valid article URLs: end with -20YYMMDD-HHMM.html
_ARTICLE_RE = re.compile(r"-20\d{6}-\d{4}\.html$")
_TEXT_EXCLUDE = (
    "suscribite", "seguinos", "compartir", "publicidad", "newsletter",
    "enviar comentario", "ver más", "cargar más", "últimas noticias",
)


class ElonceSaltaExtractor(HtmlNewsExtractor):
    source = "eloncesalta"
    base_url = "https://eloncesalta.com.ar"
    category = "salta"
    rss_feeds = [
        "https://eloncesalta.com.ar/feed",
        "https://eloncesalta.com.ar/feed/",
        "https://eloncesalta.com.ar/rss.xml",
    ]
    article_url_exclude = [
        "tag/", "/tags/", "/autor/", "/newsletter", "/#", "/page/",
        "/categoria/", "?", "/categoria/",
    ]
    article_body_selectors = [
        ".land-see-post-content",
        ".entry-content",
        ".post-content",
        ".article-content",
        "article .content",
        "article",
    ]
    homepage_card_selectors = [
        "h4.land-see-post-title a[href]",
        "article a[href]",
        "h2 a[href]",
        "h3 a[href]",
    ]

    def __init__(self, settings: Optional[PipelineSettings] = None) -> None:
        super().__init__(settings)

    def _is_article_url(self, url: str) -> bool:
        if not url or not url.startswith(self.base_url):
            return False
        low = url.lower()
        for tok in self.article_url_exclude:
            if tok in low:
                return False
        return bool(_ARTICLE_RE.search(urlparse(url).path))

    def _homepage_candidates(self, limit: int) -> List[Dict]:
        html = fetch_html(self.base_url, referer=self.base_url)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        rows: List[Dict] = []
        seen: set = set()

        for link in soup.select("h4.land-see-post-title a[href]"):
            url = normalize_article_url(str(link.get("href") or ""), self.base_url)
            if not url or url in seen or not self._is_article_url(url):
                continue
            title = clean_text(link.get("title") or link.get_text(" ", strip=True))
            if not title or len(title) < 10:
                continue
            fecha = self._date_from_url(url)
            seen.add(url)
            rows.append({"id": url, "url": url, "titulo": title, "fecha_publicacion": fecha})
            if len(rows) >= limit:
                break

        if not rows:
            for link in soup.select("article a[href], h3 a[href]"):
                url = normalize_article_url(str(link.get("href") or ""), self.base_url)
                if not url or url in seen or not self._is_article_url(url):
                    continue
                title = clean_text(link.get_text(" ", strip=True))
                if len(title) < 10:
                    continue
                seen.add(url)
                rows.append({"id": url, "url": url, "titulo": title})
                if len(rows) >= limit:
                    break
        return rows

    def _date_from_url(self, url: str) -> str:
        match = re.search(r"-(?P<y>20\d{2})(?P<m>\d{2})(?P<d>\d{2})-\d{4}\.html$", url)
        if match:
            return f"{match.group('y')}-{match.group('m')}-{match.group('d')}"
        return ""

    def _article_detail(self, url: str, title_hint: str = "") -> Dict:
        html = fetch_html(url, referer=self.base_url)
        if not html:
            return {}
        soup = BeautifulSoup(html, "html.parser")
        json_ld = extract_json_ld(soup)

        h1 = soup.select_one("h1.entry-title") or soup.select_one("h1")
        title = clean_text(h1.get_text(" ", strip=True) if h1 else "") or title_hint

        extracto = ""
        for sel in (".entry-subtitle", ".post-subtitle", ".article-subtitle"):
            tag = soup.select_one(sel)
            if tag:
                extracto = clean_text(tag.get_text(" ", strip=True))
                if extracto and extracto != title:
                    break
        if not extracto:
            extracto = clean_text(str(json_ld.get("description") or ""))
            if not extracto:
                meta = soup.find("meta", property="og:description")
                extracto = clean_text(str((meta or {}).get("content") or ""))

        parrafos = self._extract_body(soup, extracto, title)
        image_url = extract_og_image(soup, self.base_url)
        published = extract_published_date(soup, json_ld) or self._date_from_url(url)

        return {
            "titulo": title,
            "extracto": extracto,
            "parrafos": parrafos,
            "imagenes_url": [image_url] if image_url else [],
            "fecha_publicacion": published,
        }

    def _extract_body(self, soup: BeautifulSoup, extracto: str, titulo: str) -> List[str]:
        body = None
        for sel in self.article_body_selectors:
            body = soup.select_one(sel)
            if body:
                break
        if body is None:
            return [extracto] if extracto else []
        for junk in body.select("script, style, .tags, .compartir, .publicidad, .amp-wp-article-footer"):
            junk.decompose()
        paragraphs: List[str] = []
        seen: set = set()
        low_ex = extracto.lower()
        low_ti = titulo.lower()
        for block in body.find_all(["p", "h2", "h3", "li"]):
            text = clean_text(block.get_text(" ", strip=True))
            if not text or len(text) < 30:
                continue
            low = text.lower()
            if low in seen or low == low_ex or low == low_ti:
                continue
            if any(tok in low for tok in _TEXT_EXCLUDE):
                continue
            paragraphs.append(text)
            seen.add(low)
            if len(paragraphs) >= 8:
                break
        return paragraphs or ([extracto] if extracto else [])

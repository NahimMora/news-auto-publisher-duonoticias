"""El Tribuno de Salta extractor — adapted from HolaSalta scraper pattern."""
from __future__ import annotations

import contextlib
import re
from typing import Dict, List, Optional
from urllib.parse import urlparse, urlunparse

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

# URL pattern: /section/YYYY-M-D-H-M-S-slug
_ARTICLE_RE = re.compile(
    r"/[^/]+/\d{4}-\d{1,2}-\d{1,2}-\d{1,2}-\d{1,2}-\d{1,2}-[^/?#]+$"
)
_TEXT_EXCLUDE = (
    "suscribite", "seguinos", "publicidad", "compartir", "galería", "video:",
    "anticipo", "suscripción", "tags:", "etiquetas:", "última hora",
    "notas relacionadas", "más leídas", "últimas noticias",
)
_IMAGE_EXCLUDE = ("logo", "banner", "publicidad", "icon", "favicon", "tracking")


class ElTribunoExtractor(HtmlNewsExtractor):
    source = "eltribuno"
    base_url = "https://www.eltribuno.com"
    category = "salta"
    rss_feeds = [
        "https://www.eltribuno.com/salta/rss.xml",
        "https://www.eltribuno.com/rss.xml",
        "https://www.eltribuno.com/feed",
    ]
    article_url_patterns = [_ARTICLE_RE.pattern]
    article_url_exclude = [
        "tag/", "/tags/", "/autor/", "/newsletter", "/#",
        "/video/", "/fotos/", "/galeria/",
    ]
    article_body_selectors = [
        ".articulo__cuerpo",
        ".articulo__body",
        "article .content",
        ".nota-cuerpo",
        "article",
    ]
    homepage_card_selectors = [
        ".nota a[href]",
        "article a[href]",
        "h2 a[href]",
        "h3 a[href]",
    ]

    def __init__(self, settings: Optional[PipelineSettings] = None) -> None:
        super().__init__(settings)

    def _homepage_candidates(self, limit: int) -> List[Dict]:
        """Try /salta section first, then homepage."""
        for url in (f"{self.base_url}/salta", self.base_url):
            html = fetch_html(url, referer=self.base_url)
            if not html:
                continue
            results = self._parse_homepage_html(html, limit)
            if results:
                return results
        return []

    def _parse_homepage_html(self, html: str, limit: int) -> List[Dict]:
        soup = BeautifulSoup(html, "html.parser")
        rows: List[Dict] = []
        seen: set = set()
        for node in soup.select(".nota"):
            url = self._pick_url(node)
            if not url or url in seen or not self._is_article_url(url):
                continue
            title = self._pick_title(node)
            if not title:
                continue
            seen.add(url)
            rows.append({
                "id": url,
                "url": url,
                "titulo": title,
                "extracto": self._pick_extracto(node, title),
            })
            if len(rows) >= limit:
                break
        return rows

    def _pick_url(self, node) -> str:
        for link in node.select("a[href]"):
            url = normalize_article_url(str(link.get("href") or ""), self.base_url)
            if url and self._is_article_url(url):
                return url
        return ""

    def _pick_title(self, node) -> str:
        for sel in (".nota__titulo-item", ".nota__titulo h1", ".nota__titulo h2", "h1", "h2", "h3"):
            tag = node.select_one(sel)
            if tag:
                text = clean_text(tag.get_text(" ", strip=True))
                if len(text) >= 10:
                    return text
        return ""

    def _pick_extracto(self, node, titulo: str) -> str:
        for sel in (".nota__introduccion", ".nota__intro", ".articulo__intro"):
            tag = node.select_one(sel)
            if tag:
                text = clean_text(tag.get_text(" ", strip=True))
                if text and text != titulo:
                    return text
        return ""

    def _article_detail(self, url: str, title_hint: str = "") -> Dict:
        amp_url = f"{url.rstrip('/')}/amp"
        best: Optional[Dict] = None
        for candidate in (amp_url, url):
            html = fetch_html(candidate, referer=self.base_url)
            if not html:
                continue
            result = self._parse_article_html(html, url, title_hint)
            if best is None or len(result.get("parrafos") or []) > len(best.get("parrafos") or []):
                best = result
            if len(result.get("parrafos") or []) >= 3 and candidate.endswith("/amp"):
                break
        return best or {}

    def _parse_article_html(self, html: str, url: str, title_hint: str) -> Dict:
        soup = BeautifulSoup(html, "html.parser")
        json_ld = extract_json_ld(soup)

        h1 = soup.select_one("h1.articulo__titulo") or soup.select_one("h1")
        title = clean_text(h1.get_text(" ", strip=True) if h1 else "") or title_hint

        intro = soup.select_one(".articulo__intro")
        extracto = clean_text(intro.get_text(" ", strip=True) if intro else "")
        if not extracto:
            extracto = clean_text(str(json_ld.get("description") or ""))
            if not extracto:
                meta = soup.find("meta", property="og:description")
                extracto = clean_text(str((meta or {}).get("content") or ""))

        body = soup.select_one(".articulo__cuerpo") or soup.select_one(".articulo__body")
        parrafos = self._extract_body_paragraphs(body, extracto, title)

        image_url = extract_og_image(soup, self.base_url)
        if not image_url:
            img = soup.select_one(".articulo__media img[src], figure img[src]")
            if img:
                image_url = normalize_url(str(img.get("src") or ""), self.base_url)

        published = extract_published_date(soup, json_ld)
        if not published:
            match = re.search(r"/(\d{4})-(\d{1,2})-(\d{1,2})-", url)
            if match:
                published = f"{match.group(1)}-{match.group(2).zfill(2)}-{match.group(3).zfill(2)}"

        return {
            "titulo": title,
            "extracto": extracto,
            "parrafos": parrafos,
            "imagenes_url": [image_url] if image_url else [],
            "fecha_publicacion": published,
        }

    def _extract_body_paragraphs(self, body, extracto: str, titulo: str) -> List[str]:
        if body is None:
            return [extracto] if extracto else []
        for tag in body.select("script, style, .tags, .social-bar, .anticipo-cont, .suscripcion-page, .mas-leidas"):
            tag.decompose()
        paragraphs: List[str] = []
        seen: set = set()
        low_extracto = extracto.lower()
        low_titulo = titulo.lower()
        for block in body.find_all(["p", "h2", "h3", "li", "blockquote"]):
            text = clean_text(block.get_text(" ", strip=True))
            if not text or len(text) < 30:
                continue
            low = text.lower()
            if low in seen or low == low_extracto or low == low_titulo:
                continue
            if any(tok in low for tok in _TEXT_EXCLUDE):
                continue
            paragraphs.append(text)
            seen.add(low)
            if len(paragraphs) >= 8:
                break
        return paragraphs or ([extracto] if extracto else [])

    def _is_article_url(self, url: str) -> bool:
        if not url or not url.startswith(self.base_url):
            return False
        low = url.lower()
        for tok in self.article_url_exclude:
            if tok in low:
                return False
        return bool(_ARTICLE_RE.search(urlparse(url).path))

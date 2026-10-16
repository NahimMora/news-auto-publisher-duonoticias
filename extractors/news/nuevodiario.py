"""Nuevo Diario de Salta extractor — adapted from HolaSalta scraper pattern."""
from __future__ import annotations

import re
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


_TEXT_EXCLUDE = (
    "suscribite", "seguinos", "compartir", "publicidad", "newsletter",
    "notificaciones", "cargar más", "últimas noticias", "ver más noticias",
    "envianos tu", "términos y condiciones",
)


class NuevoDiarioExtractor(HtmlNewsExtractor):
    source = "nuevodiariodesalta"
    base_url = "https://nuevodiariodesalta.com.ar"
    category = "salta"
    rss_feeds = [
        "https://www.nuevodiariodesalta.com.ar/feed",
        "https://www.nuevodiariodesalta.com.ar/feed/",
        "https://www.nuevodiariodesalta.com.ar/rss.xml",
    ]
    # NuevoDiario uses flat slug URLs: /titulo-de-la-noticia/
    _SLUG_EXCLUDE = (
        "category", "tag", "author", "page", "legales", "licitaciones",
        "obituarios", "clasificados", "oferta-comercial", "wp-content",
        "wp-admin", "wp-login", "feed", "sitemap", "aviso", "politica",
        "terminos", "publicidad", "contacto", "quienes-somos", "tapas",
    )
    article_body_selectors = [
        ".entry-content",
        ".post-content",
        ".article-body",
        ".td-post-content",
        ".elementor-widget-theme-post-content",
        "article .content",
        "article",
    ]
    homepage_card_selectors = [
        "a[href]",
    ]

    def __init__(self, settings: Optional[PipelineSettings] = None) -> None:
        super().__init__(settings)

    def _is_article_url(self, url: str) -> bool:
        if not url:
            return False
        # Normalize: the site redirects www to apex
        norm_url = url.replace("https://www.", "https://").replace("http://www.", "http://")
        base_norm = self.base_url.replace("https://www.", "https://").replace("http://www.", "http://")
        if not norm_url.startswith(base_norm):
            return False
        path = urlparse(norm_url).path.strip("/")
        if not path:
            return False
        segs = path.split("/")
        first = segs[0].lower()
        if first in self._SLUG_EXCLUDE:
            return False
        if "?" in url or "#" in url:
            return False
        # Must look like a news slug (contains dashes, at least 15 chars)
        return "-" in first and len(first) >= 15

    def _homepage_candidates(self, limit: int) -> List[Dict]:
        # Site redirects www -> apex; use apex URL directly
        apex = "https://nuevodiariodesalta.com.ar"
        html = fetch_html(apex, referer=apex)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        rows: List[Dict] = []
        seen: set = set()
        for link in soup.select("a[href]"):
            href = str(link.get("href") or "").strip()
            if not href:
                continue
            url = normalize_article_url(href, apex)
            if not url or url in seen or not self._is_article_url(url):
                continue
            title = clean_text(link.get_text(" ", strip=True))
            if not title or len(title) < 15:
                parent = link.find_parent(["h1", "h2", "h3", "article"])
                if parent:
                    h = parent.find(["h1", "h2", "h3"])
                    if h:
                        title = clean_text(h.get_text(" ", strip=True))
            if not title or len(title) < 15:
                continue
            seen.add(url)
            rows.append({"id": url, "url": url, "titulo": title})
            if len(rows) >= limit:
                break
        return rows

    def _article_detail(self, url: str, title_hint: str = "") -> Dict:
        html = fetch_html(url, referer=self.base_url)
        if not html:
            return {}
        soup = BeautifulSoup(html, "html.parser")
        json_ld = extract_json_ld(soup)

        h1 = soup.select_one("h1.entry-title") or soup.select_one("h1.td-post-title") or soup.select_one("h1")
        title = clean_text(h1.get_text(" ", strip=True) if h1 else "") or title_hint

        extracto = ""
        for sel in (".entry-subtitle", ".td-post-sub-title", ".post-subtitle"):
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
        published = extract_published_date(soup, json_ld)

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
        for junk in body.select("script, style, .tags, .sharedaddy, .jp-relatedposts, .wpcnt"):
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

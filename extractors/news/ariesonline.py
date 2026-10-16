"""Aries Online (Salta) extractor — adapted from HolaSalta scraper pattern."""
from __future__ import annotations

import re
from typing import Dict, List, Optional

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
    "suscribite", "seguinos", "publicidad", "compartir", "newsletter",
    "envianos tu noticia", "quiero ser", "tu mensaje", "click aquí",
    "comentarios", "notificaciones", "cargar más",
)
_IMAGE_EXCLUDE = ("logo", "banner", "publici", "icon", "favicon")


class AriesOnlineExtractor(HtmlNewsExtractor):
    source = "ariesonline"
    base_url = "https://ariesonline.com.ar"
    category = "salta"
    rss_feeds = [
        "https://ariesonline.com.ar/feed",
        "https://ariesonline.com.ar/rss",
        "https://ariesonline.com.ar/rss.xml",
    ]
    article_url_exclude = [
        "tag/", "/tags/", "/autor/", "/#", "/newsletter",
        "/categoria/", "/page/", "/search/", "?s=",
    ]
    article_body_selectors = [
        ".fullpost__cuerpo",
        ".fullpost__contenido",
        ".post__cuerpo",
        ".post-content",
        ".entry-content",
        "article .content",
        "article",
    ]
    homepage_card_selectors = [
        "article.post.post__noticia a[href]",
        "h2.post__titulo a[href]",
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
        return "/contenido/" in low

    def _homepage_candidates(self, limit: int) -> List[Dict]:
        html = fetch_html(self.base_url, referer=self.base_url)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        rows: List[Dict] = []
        seen: set = set()

        for article in soup.select("article.post.post__noticia"):
            link = article.find("a", href=True)
            if not link:
                continue
            url = normalize_article_url(str(link.get("href") or ""), self.base_url)
            if not url or url in seen or not self._is_article_url(url):
                continue
            title_tag = article.select_one("h2.post__titulo a") or article.select_one("h2.post__titulo")
            title = clean_text(title_tag.get_text(" ", strip=True) if title_tag else link.get_text(" ", strip=True))
            if not title or len(title) < 10:
                continue
            seen.add(url)
            rows.append({"id": url, "url": url, "titulo": title})
            if len(rows) >= limit:
                break

        if not rows:
            for link in soup.select("h2.post__titulo a[href]"):
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

    def _article_detail(self, url: str, title_hint: str = "") -> Dict:
        html = fetch_html(url, referer=self.base_url)
        if not html:
            return {}
        soup = BeautifulSoup(html, "html.parser")
        json_ld = extract_json_ld(soup)

        h1 = soup.select_one("h1.fullpost__titulo") or soup.select_one("h1")
        title = clean_text(h1.get_text(" ", strip=True) if h1 else "") or title_hint

        extracto = ""
        for sel in ("p.fullpost__bajada", "p.fullpost__subtitulo", ".post__bajada"):
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
        if not published:
            date_tag = soup.select_one(".fullpost__fecha, .post__fecha, time")
            if date_tag:
                raw = clean_text(date_tag.get_text(" ", strip=True) or date_tag.get("datetime") or "")
                if raw:
                    published = raw

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

        for junk in body.select("script, style, .tags, .compartir, .publicidad, .relacionadas"):
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

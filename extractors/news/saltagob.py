"""Prensa del Gobierno de la Provincia de Salta (www.salta.gob.ar/prensa).

El sitio no publica RSS valido: los candidatos salen del listado
``/prensa/noticias`` (enlaces ``/prensa/noticias/<slug>-<id>``). Del detalle se
toma titulo, fecha (badge "16/10/2026 16:47", hora de Salta), bajada (``p.lead``),
imagen principal (fancybox) y cuerpo (``.contenido``). Es fuente oficial: solo
pasan los comunicados de alto interes ciudadano (umbral ``local_official``).
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from extractors.news.html_scraper import HtmlNewsExtractor, clean_text, fetch_html
from extractors.news.media import dedupe_candidates, videos_in_container
from storage.settings import PipelineSettings

# Las paginas de listado (seccion-, tema-, organismos/) comparten el formato slug-id.
_ARTICLE_RE = re.compile(r"^https://www\.salta\.gob\.ar/prensa/noticias/(?!seccion-|tema-|organismo)[a-z0-9-]+-\d+$")
_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2})")


def parse_local_date(text: str, zone: str = "America/Argentina/Salta") -> str:
    match = _DATE_RE.search(text or "")
    if not match:
        return ""
    day, month, year, hour, minute = (int(part) for part in match.groups())
    try:
        return datetime(year, month, day, hour, minute, tzinfo=ZoneInfo(zone)).isoformat()
    except ValueError:
        return ""


class SaltaGobExtractor(HtmlNewsExtractor):
    source = "gobiernosalta"
    base_url = "https://www.salta.gob.ar"
    category = "salta"
    rss_feeds: List[str] = []

    def __init__(self, settings: Optional[PipelineSettings] = None) -> None:
        super().__init__(settings)

    def _rss_candidates(self, limit: int) -> List[Dict]:
        return []

    def _homepage_candidates(self, limit: int) -> List[Dict]:
        html = fetch_html(f"{self.base_url}/prensa/noticias", referer=self.base_url)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        rows: List[Dict] = []
        seen: set = set()
        for link in soup.select("a[href]"):
            url = str(link.get("href") or "").split("#", 1)[0].rstrip("/")
            if url in seen or not _ARTICLE_RE.match(url):
                continue
            seen.add(url)
            rows.append({"id": url.rsplit("-", 1)[-1], "url": url, "titulo": clean_text(link.get("title") or link.get_text(" ", strip=True))})
            if len(rows) >= limit:
                break
        return rows

    def _article_detail(self, url: str, title_hint: str = "") -> Dict:
        html = fetch_html(url, referer=self.base_url)
        if not html:
            return {}
        return self.parse_article_html(html, url, title_hint)

    def parse_article_html(self, html: str, url: str, title_hint: str = "") -> Dict:
        soup = BeautifulSoup(html, "html.parser")
        article = soup.select_one("article") or soup
        h1 = article.select_one("h1")
        title = clean_text(h1.get_text(" ", strip=True) if h1 else "") or title_hint
        lead_tag = article.select_one("p.lead")
        lead = clean_text(lead_tag.get_text(" ", strip=True) if lead_tag else "")
        date_tag = article.select_one(".badge-secondary")
        published = parse_local_date(date_tag.get_text(" ", strip=True) if date_tag else "")
        body = article.select_one(".contenido")
        paragraphs: List[str] = []
        for block in (body.find_all(["p", "h2", "h3", "li"]) if body else []):
            text = clean_text(block.get_text(" ", strip=True))
            if len(text) >= 30 and text not in paragraphs and text != lead:
                paragraphs.append(text)
            if len(paragraphs) >= 14:
                break
        images: List[str] = []
        for anchor in article.select("a[data-fancybox][href]"):
            href = str(anchor.get("href") or "")
            if href.startswith("http") and href not in images:
                images.append(href)
        if not images:
            og = soup.find("meta", property="og:image")
            if og and og.get("content"):
                images.append(str(og["content"]))
        videos = dedupe_candidates(videos_in_container(body, self.base_url, location="body"))
        return {
            "id": url.rsplit("-", 1)[-1],
            "titulo": title,
            "extracto": lead,
            "parrafos": paragraphs,
            "imagenes_url": images[:6],
            "video_candidates": [candidate.as_dict() for candidate in videos],
            "fecha_publicacion": published,
        }

    def _is_article_url(self, url: str) -> bool:
        return bool(_ARTICLE_RE.match(url or ""))

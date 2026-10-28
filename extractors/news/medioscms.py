"""Sitios hechos con Medios CMS (medios.io): De Frente Salta (2026-10-22).

Sin RSS ni API: los candidatos salen del historial (``/historial``, las ultimas notas) y de
las secciones locales. Las notas son ``/contenido/<id>/<slug>``. El video propio del medio es
un ``<video src="/download/multimedia.video....mp4">`` dentro del articulo (MP4 directo); casi
todo su material lleva la marca "Defrentesalta" (politica ``discard`` en config/sources.yaml:
solo sale con relevancia muy alta, ver ``utils/watermark.py``).

El Cloudflare del sitio responde 403 a los headers completos de navegador de ``fetch_html``
(User-Agent de Chrome + Accept-Language, etc.) y 200 a un User-Agent simple: se usa ese.

2026-10-23: el sitio cambio de plantilla (``fullpost__*`` -> ``articulo-*``); desde entonces
todas las notas llegaban sin cuerpo (``texto_insuficiente``). Se leen las dos.
"""
from __future__ import annotations

import re
import time
from typing import Dict, List, Optional, Sequence

import requests
from bs4 import BeautifulSoup

from extractors.news.html_scraper import HtmlNewsExtractor, clean_text, normalize_article_url
from extractors.news.media import dedupe_candidates, json_ld_blocks, videos_in_container
from storage.settings import PipelineSettings

_TEXT_EXCLUDE = ("seguinos", "suscribite", "publicidad", "leé también", "lee también", "mirá también", "whatsapp de")


def fetch_html(url: str, referer: str = "", retries: int = 2) -> Optional[str]:
    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
            if response.ok and response.text:
                response.encoding = response.encoding if response.encoding and response.encoding.lower() != "iso-8859-1" else "utf-8"
                return response.text
        except requests.RequestException:
            pass
        if attempt < retries:
            time.sleep(1.5 * attempt)
    return None


class MediosCmsExtractor(HtmlNewsExtractor):
    category = "salta"
    rss_feeds: List[str] = []

    def __init__(self, source: str, base_url: str, *, listing_pages: Sequence[str], category: str = "salta",
                 settings: Optional[PipelineSettings] = None) -> None:
        super().__init__(settings)
        self.source = source
        self.base_url = base_url.rstrip("/")
        self.category = category
        self.listing_pages = tuple(listing_pages)
        self._article_re = re.compile(rf"^{re.escape(self.base_url)}/contenido/\d+/[a-z0-9-]+$")

    def _rss_candidates(self, limit: int) -> List[Dict]:
        return []

    def _homepage_candidates(self, limit: int) -> List[Dict]:
        rows: List[Dict] = []
        seen: set = set()
        for page in self.listing_pages:
            html = fetch_html(f"{self.base_url}{page}", referer=self.base_url)
            if not html:
                continue
            soup = BeautifulSoup(html, "html.parser")
            for link in soup.select('a[href*="/contenido/"]'):
                url = normalize_article_url(str(link.get("href") or ""), self.base_url)
                if url in seen or not self._article_re.match(url):
                    continue
                seen.add(url)
                rows.append({"id": url, "url": url, "titulo": clean_text(link.get("title") or link.get_text(" ", strip=True))})
        # Mas nuevas primero: el id de la nota es correlativo.
        rows.sort(key=lambda row: -int(re.search(r"/contenido/(\d+)/", row["url"]).group(1)))
        return rows[: max(limit, 1) * 2]

    def _article_detail(self, url: str, title_hint: str = "") -> Dict:
        html = fetch_html(url, referer=self.base_url)
        if not html:
            return {}
        return self.parse_article_html(html, url, title_hint)

    def parse_article_html(self, html: str, url: str, title_hint: str = "") -> Dict:
        soup = BeautifulSoup(html, "html.parser")
        article_ld: Dict = next((b for b in json_ld_blocks(soup) if str(b.get("@type") or "") == "NewsArticle"), {})
        h1 = soup.select_one("h1.fullpost__titulo") or soup.select_one("h1")
        title = clean_text(h1.get_text(" ", strip=True) if h1 else "") or clean_text(str(article_ld.get("headline") or "")) or title_hint
        paragraphs: List[str] = []
        body = soup.select_one(".articulo-cuerpo") or soup.select_one(".fullpost__cuerpo")
        # Los widgets "medios-widget" son tarjetas de otras notas metidas en el cuerpo.
        blocks = [p for p in body.select("p") if not p.find_parent(class_="medios-widget")] if body else []
        for block in blocks or ([body] if body else []):
            text = clean_text(block.get_text(" ", strip=True))
            if len(text) < 30 or text in paragraphs or any(token in text.lower() for token in _TEXT_EXCLUDE):
                continue
            paragraphs.append(text)
            if len(paragraphs) >= 14:
                break
        # El <video> propio va dentro del cuerpo; las tarjetas de otras notas quedan afuera de fullpost__main.
        container = (soup.select_one(".articulo-principal") or soup.select_one(".fullpost__main")
                     or soup.select_one(".fullpost__cuerpo"))
        videos = dedupe_candidates(videos_in_container(container, self.base_url, location="cover"))
        image = article_ld.get("image")
        if isinstance(image, dict):
            image = image.get("url")
        images = [str(image)] if image else []
        if not images:
            og = soup.find("meta", property="og:image")
            if og and og.get("content"):
                images.append(str(og["content"]))
        return {
            "titulo": title,
            "extracto": clean_text(str(article_ld.get("description") or "")),
            "parrafos": paragraphs,
            "imagenes_url": images,
            "video_candidates": [candidate.as_dict() for candidate in videos],
            "fecha_publicacion": str(article_ld.get("datePublished") or ""),
        }

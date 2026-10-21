"""Prensa oficial en WordPress (Policia de Salta, Municipalidad de Salta) via REST API.

La API trae titulo, bajada, cuerpo, fecha GMT e imagen destacada en una sola
respuesta, sin bajar cada pagina. Algunos sitios no exponen ``/wp-json/`` y si
``?rest_route=`` (Policia). Los videos incrustados en el cuerpo (iframes,
``video``) se detectan con ``extractors/news/media.py``; estas fuentes no exigen
video y pueden publicarse con imagen o carrusel.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from extractors.news.common import content_from_raw, normalize_url, strip_html
from extractors.news.html_scraper import KnownUrl, clean_text, fetch_json
from extractors.news.media import dedupe_candidates, videos_in_container
from storage.models import ExtractedContent
from storage.settings import PipelineSettings, get_settings

_SKIP_TEXT = ("compartir", "seguinos", "facebook", "instagram", "twitter")


class WordPressNewsExtractor:
    source_type = "news"

    def __init__(self, source: str, base_url: str, category: str = "salta", settings: Optional[PipelineSettings] = None) -> None:
        self.source = source
        self.base_url = base_url.rstrip("/")
        self.category = category
        self.settings = settings or get_settings()
        self.logger = logging.getLogger(f"duo.extractors.{source}")

    def _posts(self, limit: int) -> List[Dict[str, Any]]:
        per_page = max(1, min(int(limit), 30))
        for url in (
            f"{self.base_url}/wp-json/wp/v2/posts?per_page={per_page}&_embed=1",
            f"{self.base_url}/?rest_route=/wp/v2/posts&per_page={per_page}&_embed=1",
        ):
            payload = fetch_json(url, referer=self.base_url)
            if isinstance(payload, list):
                return [post for post in payload if isinstance(post, dict)]
        self.logger.warning("%s: la API de WordPress no respondio", self.source)
        return []

    def scan(self, max_items: int = 10, known: Optional[KnownUrl] = None) -> List[ExtractedContent]:
        rows: List[ExtractedContent] = []
        for post in self._posts(max_items):
            link = normalize_url(str(post.get("link") or ""))
            if not link or (known is not None and known(link)):
                continue
            rows.append(content_from_raw(source=self.source, source_type=self.source_type, raw=self.post_to_raw(post), category=self.category))
        return rows

    def post_to_raw(self, post: Dict[str, Any]) -> Dict[str, Any]:
        content_html = str((post.get("content") or {}).get("rendered") or "")
        soup = BeautifulSoup(content_html, "html.parser")
        paragraphs: List[str] = []
        for block in soup.find_all(["p", "h2", "h3", "li", "blockquote"]):
            text = clean_text(block.get_text(" ", strip=True))
            if len(text) < 30 or text in paragraphs or any(token in text.lower() for token in _SKIP_TEXT):
                continue
            paragraphs.append(text)
            if len(paragraphs) >= 14:
                break
        images: List[str] = []
        embedded = post.get("_embedded") or {}
        for media in embedded.get("wp:featuredmedia") or []:
            if isinstance(media, dict) and media.get("source_url"):
                images.append(str(media["source_url"]))
        for img in soup.select("img[src], img[data-src]"):
            src = str(img.get("data-src") or img.get("src") or "")
            if src.startswith("http") and src not in images:
                images.append(src)
        videos = dedupe_candidates(videos_in_container(soup, self.base_url, location="body"))
        published = str(post.get("date_gmt") or "")
        if published and not published.endswith(("Z", "+00:00")):
            published += "+00:00"
        return {
            "id": str(post.get("id") or ""),
            "url": str(post.get("link") or ""),
            "titulo": clean_text(strip_html(str((post.get("title") or {}).get("rendered") or ""))),
            "extracto": clean_text(strip_html(str((post.get("excerpt") or {}).get("rendered") or ""))),
            "parrafos": paragraphs,
            "imagenes_url": images[:6],
            "video_candidates": [candidate.as_dict() for candidate in videos],
            "fecha_publicacion": published or str(post.get("date") or ""),
        }

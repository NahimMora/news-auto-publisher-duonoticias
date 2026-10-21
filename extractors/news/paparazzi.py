"""Paparazzi (paparazzi.com.ar): notas de espectaculos que traen un video real.

El texto sale de la API de WordPress (titulo, bajada, cuerpo completo, fecha).
El video NO esta en ``content.rendered``: lo inserta la plantilla de la pagina
como JW Player (``<script src=".../players/{MEDIA_ID}-{SITE}.js">``). Por eso,
solo para las notas nuevas, se baja la pagina, se toma el media id y se consulta
la API publica de JW Player (``cdn.jwplayer.com/v2/media/{id}``, sin auth) para
obtener un MP4 directo y la duracion real. Mismo enfoque que La Voz Riojana.

Regla editorial: Paparazzi exige video (``requires_video``); sin video la nota se
descarta. Nunca se arma un reel con sus fotos.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from extractors.news.common import content_from_raw, normalize_url, strip_html
from extractors.news.html_scraper import KnownUrl, clean_text, fetch_html, fetch_json
from extractors.news.media import VideoCandidate, dedupe_candidates, videos_in_container
from storage.models import ExtractedContent
from storage.settings import PipelineSettings, get_settings

BASE_URL = "https://www.paparazzi.com.ar"
# Calidad suficiente para un reel 1080x1920 sin bajar el archivo mas pesado.
MP4_LABEL_PRIORITY = ("720p", "540p", "1080p", "480p", "406p", "360p")


def resolve_jwplayer(media_id: str) -> Optional[VideoCandidate]:
    """MP4 directo + duracion de un media id de JW Player. None si la API no responde."""
    payload = fetch_json(f"https://cdn.jwplayer.com/v2/media/{media_id}")
    playlist = (payload or {}).get("playlist") if isinstance(payload, dict) else None
    first = playlist[0] if isinstance(playlist, list) and playlist and isinstance(playlist[0], dict) else {}
    sources = [s for s in first.get("sources") or [] if isinstance(s, dict) and s.get("type") == "video/mp4" and str(s.get("file") or "").startswith("https://")]
    if not sources:
        return None
    by_label = {str(s.get("label") or ""): s for s in sources}
    pick = next((by_label[label] for label in MP4_LABEL_PRIORITY if label in by_label), sources[0])
    duration = first.get("duration")
    return VideoCandidate(
        url=str(pick["file"]),
        kind="mp4",
        location="cover",
        duration_seconds=float(duration) if isinstance(duration, (int, float)) and duration > 0 else None,
        poster=str(first.get("image") or ""),
        provider="jwplayer",
        meta={"media_id": media_id, "title": str(first.get("title") or "")},
    )


class PaparazziExtractor:
    name = "paparazzi"
    source_type = "news"

    def __init__(self, settings: PipelineSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self.logger = logging.getLogger("duo.extractors.paparazzi")

    def scan(self, max_items: int | None = None, known: Optional[KnownUrl] = None) -> List[ExtractedContent]:
        limit = max_items if max_items is not None else 10
        if limit <= 0:
            return []
        posts = fetch_json(f"{BASE_URL}/wp-json/wp/v2/posts?per_page={min(limit, 50)}&_embed=1", referer=BASE_URL)
        rows: List[ExtractedContent] = []
        for post in posts if isinstance(posts, list) else []:
            if not isinstance(post, dict):
                continue
            link = normalize_url(str(post.get("link") or ""))
            if not link or (known is not None and known(link)):
                continue
            raw = self.post_to_raw(post)
            html = fetch_html(link, referer=BASE_URL)
            raw["video_candidates"] = [candidate.as_dict() for candidate in self.page_videos(html or "")]
            rows.append(content_from_raw(source=self.name, source_type=self.source_type, raw=raw, category="espectaculos"))
        return rows

    def page_videos(self, html: str) -> List[VideoCandidate]:
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        scope = soup.select_one("article") or soup.select_one("main") or soup
        found: List[VideoCandidate] = []
        for candidate in dedupe_candidates(videos_in_container(scope, BASE_URL, location="cover")):
            if candidate.kind == "jwplayer":
                resolved = resolve_jwplayer(str(candidate.meta.get("media_id") or ""))
                if resolved is not None:
                    found.append(resolved)
                else:
                    self.logger.info("paparazzi: JW Player %s sin MP4 disponible", candidate.meta.get("media_id"))
            else:
                found.append(candidate)
        return found

    def post_to_raw(self, post: Dict[str, Any]) -> Dict[str, Any]:
        content_html = str((post.get("content") or {}).get("rendered") or "")
        soup = BeautifulSoup(content_html, "html.parser")
        images: List[str] = []
        for media in (post.get("_embedded") or {}).get("wp:featuredmedia") or []:
            if isinstance(media, dict) and media.get("source_url"):
                images.append(str(media["source_url"]))
        for image in soup.select("img[src], img[data-src], img[data-lazy-src]"):
            src = image.get("data-src") or image.get("data-lazy-src") or image.get("src") or ""
            if src and src not in images:
                images.append(str(src))
        paragraphs: List[str] = []
        for paragraph in soup.select("p, h2, h3"):
            text = clean_text(paragraph.get_text(" ", strip=True))
            if len(text) >= 35 and text not in paragraphs:
                paragraphs.append(text)
            if len(paragraphs) >= 14:
                break
        published = str(post.get("date_gmt") or "")
        if published and not published.endswith(("Z", "+00:00")):
            published += "+00:00"
        categories = [
            str(term.get("name") or "")
            for group in (post.get("_embedded") or {}).get("wp:term") or []
            for term in (group if isinstance(group, list) else [])
            if isinstance(term, dict) and term.get("taxonomy") == "category"
        ]
        return {
            "id": post.get("id"),
            "slug": post.get("slug") or "",
            "url": post.get("link") or "",
            "titulo": clean_text(strip_html(str((post.get("title") or {}).get("rendered", "")))),
            "extracto": clean_text(strip_html(str((post.get("excerpt") or {}).get("rendered", "")))),
            "parrafos": paragraphs,
            "imagenes_url": images[:6],
            "fecha_publicacion": published or str(post.get("date") or ""),
            "categoria": ", ".join(name for name in categories if name),
        }

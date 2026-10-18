"""TN e Infobae (Arc XP / Fusion): texto y videos reales de la nota.

Ambos sitios embeben el contenido completo en ``Fusion.globalContent``. El video
de la nota esta en ``promo_items.basic`` (portada) o en ``content_elements``
(cuerpo):
- TN: ``custom_embed`` subtipo ``genoa`` (vodgc) con ``highQuality`` mp4 y duracion.
- Infobae: ``custom_embed`` subtipo ``video`` (JW Player) con ``contentUrl`` mp4.
Asi el video queda atado a la nota: los widgets de "videos recomendados" de la
pagina no cuentan (traen el mismo video en notas distintas).

Ambas fuentes exigen video (``requires_video``); la politica descarta las que no
lo tengan antes de gastar evaluacion. Los vivos (live blogging) se marcan para
descartarlos: no son un hecho unico publicable.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import feedparser
import requests
from bs4 import BeautifulSoup

from extractors.news.common import content_from_raw, normalize_url, strip_html
from extractors.news.html_scraper import KnownUrl, default_headers, fetch_html
from extractors.news.media import arc_text, arc_videos, dedupe_candidates, fusion_global_content, videos_from_json_ld
from storage.models import ExtractedContent
from storage.settings import PipelineSettings, get_settings
from utils.tls import ca_bundle_for


class ArcNewsExtractor:
    source_type = "news"

    def __init__(
        self,
        source: str,
        *,
        base_url: str,
        feeds: List[str],
        category: str = "nacional",
        exclude_path_prefixes: List[str] | None = None,
        settings: Optional[PipelineSettings] = None,
    ) -> None:
        self.source = source
        self.base_url = base_url.rstrip("/")
        self.feeds = list(feeds)
        self.category = category
        self.exclude_path_prefixes = tuple(exclude_path_prefixes or ())
        self.settings = settings or get_settings()
        self.logger = logging.getLogger(f"duo.extractors.{source}")

    def _feed_entries(self, limit: int) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        seen: set = set()
        for feed_url in self.feeds:
            try:
                response = requests.get(feed_url, headers=default_headers(self.base_url), timeout=25, verify=ca_bundle_for(feed_url))
                response.raise_for_status()
            except requests.RequestException as exc:
                self.logger.warning("%s feed %s: %s", self.source, feed_url, exc)
                continue
            for entry in feedparser.parse(response.content).entries or []:
                url = normalize_url(str(getattr(entry, "link", "") or ""))
                if not url or url in seen or not self.is_article_url(url):
                    continue
                seen.add(url)
                rows.append(
                    {
                        "id": str(getattr(entry, "id", "") or url),
                        "url": url,
                        "titulo": strip_html(str(getattr(entry, "title", "") or "")),
                        "extracto": strip_html(str(getattr(entry, "summary", "") or ""))[:600],
                        "fecha_publicacion": str(getattr(entry, "published", "") or getattr(entry, "updated", "") or ""),
                    }
                )
                if len(rows) >= limit:
                    return rows
        return rows

    def is_article_url(self, url: str) -> bool:
        if not url.startswith(self.base_url):
            return False
        path = urlparse(url).path
        if any(path.startswith(prefix) for prefix in self.exclude_path_prefixes):
            return False
        return path.count("/") >= 3

    def scan(self, max_items: int = 10, known: Optional[KnownUrl] = None) -> List[ExtractedContent]:
        rows: List[ExtractedContent] = []
        for item in self._feed_entries(max_items):
            if known is not None and known(item["url"]):
                continue
            html = fetch_html(item["url"], referer=self.base_url)
            if not html:
                continue
            item.update(self.parse_article_html(html))
            rows.append(content_from_raw(source=self.source, source_type=self.source_type, raw=item, category=self.category))
        return rows

    def parse_article_html(self, html: str) -> Dict[str, Any]:
        content = fusion_global_content(html)
        detail: Dict[str, Any] = {}
        videos = []
        live = False
        if content:
            text = arc_text(content)
            videos = arc_videos(content)
            live = any(
                isinstance(el, dict) and el.get("subtype") == "live-blogging"
                for el in content.get("content_elements") or []
            ) or text["title"].lower().startswith(("en vivo", "minuto a minuto"))
            detail = {
                "titulo": text["title"],
                "extracto": text["summary"],
                "parrafos": text["paragraphs"][:16],
                "imagenes_url": [text["image"]] if text["image"] else [],
                "categoria": text["section"],
            }
            if text["published"]:
                detail["fecha_publicacion"] = text["published"]
        soup = BeautifulSoup(html, "html.parser")
        videos = dedupe_candidates(videos + videos_from_json_ld(soup))
        if not detail.get("imagenes_url"):
            og = soup.find("meta", property="og:image")
            if og and og.get("content"):
                detail["imagenes_url"] = [str(og["content"])]
        detail["video_candidates"] = [candidate.as_dict() for candidate in videos]
        detail["live_blog"] = live
        return {key: value for key, value in detail.items() if value not in (None, "")}

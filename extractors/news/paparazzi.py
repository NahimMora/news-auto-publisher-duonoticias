from __future__ import annotations

import logging
import re
from typing import List

from bs4 import BeautifulSoup

from extractors.news.common import content_from_raw
from storage.models import ExtractedContent
from storage.settings import PipelineSettings, get_settings


class PaparazziExtractor:
    name = "paparazzi"
    source_type = "news"

    def __init__(self, settings: PipelineSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self.logger = logging.getLogger("duo.extractors.paparazzi")

    def scan(self, max_items: int | None = None) -> List[ExtractedContent]:
        from scrapping.paparazzi.config import PER_PAGE
        from scrapping.paparazzi.scrap_links_paparazzi import _fetch_posts, _strip_html

        limit = max_items if max_items is not None else 5
        if limit <= 0:
            return []
        rows: List[ExtractedContent] = []
        page = 1
        while len(rows) < limit:
            posts = _fetch_posts(page, min(PER_PAGE, max(limit, 1)))
            if not posts:
                break
            for post in posts:
                raw = self._post_to_raw(post, strip_html_func=_strip_html)
                rows.append(content_from_raw(source=self.name, source_type=self.source_type, raw=raw, category="paparazzi"))
                if len(rows) >= limit:
                    break
            page += 1
            if page > 3:
                break
        return rows

    def _post_to_raw(self, post: dict, *, strip_html_func) -> dict:
        content_html = str((post.get("content") or {}).get("rendered") or "")
        embedded = post.get("_embedded") or {}
        images = []
        if embedded.get("wp:featuredmedia"):
            featured = embedded["wp:featuredmedia"][0]
            if featured.get("source_url"):
                images.append(str(featured.get("source_url")))
        soup = BeautifulSoup(content_html, "html.parser")
        for image in soup.select("img[src], img[data-src], img[data-lazy-src]"):
            src = image.get("data-src") or image.get("data-lazy-src") or image.get("src") or ""
            if src and src not in images:
                images.append(src)
        videos = []
        for match in re.findall(r"https?://[^\s\"']+", content_html):
            if ".mp4" in match or "youtube.com" in match or "youtu.be" in match:
                videos.append(match)
        paragraphs = []
        for paragraph in soup.select("p"):
            text = strip_html_func(paragraph.get_text(" ", strip=True))
            if len(text) >= 35 and text not in paragraphs:
                paragraphs.append(text)
            if len(paragraphs) >= 5:
                break
        return {
            "id": post.get("id"),
            "slug": post.get("slug") or "",
            "url": post.get("link") or "",
            "titulo": strip_html_func((post.get("title") or {}).get("rendered", "")),
            "extracto": strip_html_func((post.get("excerpt") or {}).get("rendered", "")),
            "parrafos": paragraphs,
            "imagenes_url": images,
            "videos_url": videos,
            "fecha_publicacion": post.get("date") or "",
            "fecha_scraping": "",
        }

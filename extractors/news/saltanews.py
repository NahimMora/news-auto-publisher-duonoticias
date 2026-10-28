"""SaltaNews (Next.js, 2026-10-22): RSS para los candidatos, la pagina de la nota para el detalle.

El video de la nota no esta en el HTML como iframe: lo arma el componente ``VideoDeYouTube`` con
el id de YouTube en el payload de React Server Components (``self.__next_f.push``), por ejemplo
``66:I[...,"VideoDeYouTube"]`` y despues ``["$","$L66",null,{"id":"ckPQbycBqHY",...}]``. Se toma
ese id y se resuelve como cualquier YouTube (``utils/media_resolver.py``: mas de 6 min no se usa).
El feed mezcla nacionales; las que no tienen relacion con Salta las penaliza la relevancia.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from extractors.news.html_scraper import HtmlNewsExtractor, clean_text, fetch_html
from extractors.news.media import VideoCandidate, dedupe_candidates, json_ld_blocks, videos_in_container
from storage.settings import PipelineSettings

_COMPONENT_RE = re.compile(r'(\w+):I\[\d+,\[[^\]]*\],"VideoDeYouTube"\]')
_TEXT_EXCLUDE = ("leé también", "lee también", "mirá también", "seguinos", "suscribite")


def youtube_ids(html: str) -> List[str]:
    """Ids de YouTube que el componente VideoDeYouTube recibe en el payload RSC de la nota."""
    payload = html.replace('\\"', '"')
    ids: List[str] = []
    for ref in set(_COMPONENT_RE.findall(payload)):
        for video_id in re.findall(rf'"\$L{re.escape(ref)}",null,\{{"id":"([\w-]{{11}})"', payload):
            if video_id not in ids:
                ids.append(video_id)
    return ids


class SaltaNewsExtractor(HtmlNewsExtractor):
    source = "saltanews"
    base_url = "https://www.saltanews.com.ar"
    category = "salta"
    rss_feeds = ["https://www.saltanews.com.ar/feed/"]
    article_url_exclude = ["/videos", "/horoscopo", "/obituarios", "?", "="]

    def __init__(self, settings: Optional[PipelineSettings] = None) -> None:
        super().__init__(settings)

    def _is_article_url(self, url: str) -> bool:
        if not url.startswith(self.base_url + "/") or any(token in url for token in self.article_url_exclude):
            return False
        return bool(re.match(r"^/[a-z0-9-]{12,}$", url[len(self.base_url):]))

    def _article_detail(self, url: str, title_hint: str = "") -> Dict:
        html = fetch_html(url, referer=self.base_url)
        if not html:
            return {}
        return self.parse_article_html(html, url, title_hint)

    def parse_article_html(self, html: str, url: str, title_hint: str = "") -> Dict:
        soup = BeautifulSoup(html, "html.parser")
        article_ld: Dict = next((b for b in json_ld_blocks(soup) if str(b.get("@type") or "") == "NewsArticle"), {})
        h1 = soup.select_one("article h1") or soup.select_one("h1")
        title = clean_text(h1.get_text(" ", strip=True) if h1 else "") or clean_text(str(article_ld.get("headline") or "")) or title_hint
        paragraphs: List[str] = []
        for block in soup.select(".cuerpo-nota p, p.cuerpo-nota"):
            text = clean_text(block.get_text(" ", strip=True))
            if len(text) < 30 or text in paragraphs or any(token in text.lower() for token in _TEXT_EXCLUDE):
                continue
            paragraphs.append(text)
            if len(paragraphs) >= 14:
                break
        videos = [VideoCandidate(url=f"https://www.youtube.com/watch?v={video_id}", kind="youtube", location="cover", provider="saltanews")
                  for video_id in youtube_ids(html)]
        videos += videos_in_container(soup.select_one("article"), self.base_url, location="body")
        image = article_ld.get("image")
        if isinstance(image, list):
            image = image[0] if image else ""
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
            "video_candidates": [candidate.as_dict() for candidate in dedupe_candidates(videos)],
            "fecha_publicacion": str(article_ld.get("datePublished") or ""),
        }

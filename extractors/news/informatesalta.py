"""Informate Salta (CMS Tadevel): articulo completo, galeria y video de portada.

En Informate el video suele ocupar el lugar de la foto de portada: es un
``<video autoplay data-tadevel-template="web/video">`` dentro de
``web/article-deco`` o ``web/multimedia``, con la URL en ``source[src]`` o en
``data-tadevel-lazy-attrs="src=..."`` (codificada). El ``poster`` es solo la
miniatura. Tambien se buscan videos dentro del cuerpo (``web/article-body``).
Los widgets de notas relacionadas no se miran (traen videos de otras notas).

Algunos videos llevan una franja azul inferior con el nombre del medio: la
recorta ``utils/watermark.py`` (politica ``informate_band``).
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from extractors.news.html_scraper import (
    HtmlNewsExtractor,
    clean_text,
    extract_published_date,
    fetch_html,
)
from extractors.news.media import dedupe_candidates, json_ld_blocks, videos_in_container
from storage.settings import PipelineSettings

_ARTICLE_RE = re.compile(r"^https://informatesalta\.com\.ar/[a-z0-9-]+/[^/?#]+_a[0-9a-f]{20,}$")
_TEXT_EXCLUDE = ("seguinos", "suscribite", "publicidad", "leé también", "lee también", "mirá también")


def _template(soup: BeautifulSoup, name: str):
    return soup.select_one(f'[data-tadevel-template="{name}"]')


class InformateSaltaExtractor(HtmlNewsExtractor):
    source = "informatesalta"
    base_url = "https://informatesalta.com.ar"
    category = "salta"
    rss_feeds = ["https://informatesalta.com.ar/rss.xml"]
    article_url_patterns = [_ARTICLE_RE.pattern]
    article_url_exclude = ["?output="]

    def __init__(self, settings: Optional[PipelineSettings] = None) -> None:
        super().__init__(settings)

    def _article_detail(self, url: str, title_hint: str = "") -> Dict:
        html = fetch_html(url, referer=self.base_url)
        if not html:
            return {}
        return self.parse_article_html(html, url, title_hint)

    def parse_article_html(self, html: str, url: str, title_hint: str = "") -> Dict:
        soup = BeautifulSoup(html, "html.parser")
        article = _template(soup, "web/article") or soup
        header = _template(article, "web/article-header") or article
        h1 = header.select_one("h1") or soup.select_one("h1")
        title = clean_text(h1.get_text(" ", strip=True) if h1 else "") or title_hint

        lead = ""
        for selector in ("h2", ".subtitle", ".article-subtitle", "p.lead"):
            tag = header.select_one(selector)
            if tag:
                lead = clean_text(tag.get_text(" ", strip=True))
                if lead and lead != title:
                    break
                lead = ""

        body = _template(article, "web/article-body")
        content = body.select_one(".article-body-content") if body else None
        paragraphs: List[str] = []
        seen: set = set()
        for block in (content or body or soup).find_all(["p", "h2", "h3", "li", "blockquote"], recursive=True):
            if block.find_parent(attrs={"data-tadevel-template": "web/article/article-body-related"}):
                continue
            if block.name == "p" and block.find("p"):
                # El HTML del CMS deja <p> sin cerrar y quedan anidados: solo el texto propio.
                own = [child for child in block.children if getattr(child, "name", None) != "p"]
                text = clean_text(" ".join(c.get_text(" ", strip=True) if hasattr(c, "get_text") else str(c) for c in own))
            else:
                text = clean_text(block.get_text(" ", strip=True))
            if len(text) < 30 or text.lower() in seen or text == title:
                continue
            if any(token in text.lower() for token in _TEXT_EXCLUDE):
                continue
            seen.add(text.lower())
            paragraphs.append(text)
            if len(paragraphs) >= 14:
                break

        deco = _template(article, "web/article-deco")
        multimedia = _template(article, "web/multimedia")
        cover_videos = videos_in_container(multimedia, self.base_url, location="cover")
        if deco is not None:
            # deco envuelve todo el articulo: solo cuenta su <video> directo (el fondo de portada).
            direct = "".join(str(video) for video in deco.find_all("video", recursive=False))
            cover_videos += videos_in_container(BeautifulSoup(direct, "html.parser"), self.base_url, location="cover")
        body_videos = videos_in_container(body, self.base_url, location="body")
        videos = dedupe_candidates(cover_videos + body_videos)

        images: List[str] = []
        for block in json_ld_blocks(soup):
            if str(block.get("@type") or "") != "NewsArticle":
                continue
            page = block.get("mainEntityOfPage") or {}
            primary = page.get("primaryImageOfPage") if isinstance(page, dict) else None
            for image in primary if isinstance(primary, list) else [primary]:
                if isinstance(image, dict) and image.get("url"):
                    images.append(str(image["url"]))
            extra = block.get("image")
            for image in extra if isinstance(extra, list) else ([extra] if extra else []):
                url = image.get("url") if isinstance(image, dict) else image
                if url and str(url) not in images:
                    images.append(str(url))
        if not images and multimedia is not None:
            for img in multimedia.select("img[src], source[srcset]"):
                src = str(img.get("src") or str(img.get("srcset") or "").split(" ")[0])
                if src.startswith("http") and src not in images:
                    images.append(src)

        published = extract_published_date(soup, {})
        return {
            "titulo": title,
            "extracto": lead,
            "parrafos": paragraphs,
            "imagenes_url": images[:6],
            "video_candidates": [candidate.as_dict() for candidate in videos],
            "fecha_publicacion": published,
        }

    def _is_article_url(self, url: str) -> bool:
        if not url or "?output=" in url:
            return False
        return bool(_ARTICLE_RE.match(url.split("#", 1)[0]))

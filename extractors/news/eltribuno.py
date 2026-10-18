"""El Tribuno de Salta: articulo, imagen principal y video (reproductor onvideo.news).

Candidatos desde el feed ``/feed`` (o la seccion /salta si falla). El detalle se
lee de la pagina canonica: el video aparece como iframe ``api.onvideo.news`` en
la portada (``.articulo__media``) o dentro del cuerpo (``.articulo__cuerpo``).
Las fotos propias suelen llevar la marca de agua "El Tribuno": la politica de
marcas de agua (``utils/watermark.py``) decide despues si la nota sigue.
"""
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
from extractors.news.media import dedupe_candidates, videos_in_container
from storage.settings import PipelineSettings

# URL pattern: /section/YYYY-M-D-H-M-S-slug
_ARTICLE_RE = re.compile(r"/[^/]+/\d{4}-\d{1,2}-\d{1,2}-\d{1,2}-\d{1,2}-\d{1,2}-[^/?#]+$")
_TEXT_EXCLUDE = (
    "suscribite", "seguinos", "publicidad", "compartir", "galería", "video:",
    "anticipo", "suscripción", "tags:", "etiquetas:", "última hora",
    "notas relacionadas", "más leídas", "últimas noticias",
)
_CDN_RE = re.compile(r"https://uscdn\.eltribuno\.com/\d+/\d+\.(?:webp|jpe?g|png)")


def jpeg_variant(url: str) -> str:
    """El CDN entrega JPEG con ``extw=jpg``; la URL pelada no siempre es descargable."""
    match = _CDN_RE.match(url or "")
    if not match:
        return url
    return f"{match.group(0)}?cw=1200&ch=675&extw=jpg"


class ElTribunoExtractor(HtmlNewsExtractor):
    source = "eltribuno"
    base_url = "https://www.eltribuno.com"
    category = "salta"
    rss_feeds = ["https://www.eltribuno.com/feed"]
    article_url_patterns = [_ARTICLE_RE.pattern]
    article_url_exclude = [
        "tag/", "/tags/", "/autor/", "/newsletter", "/#",
        "/fotos/", "/galeria/",
    ]

    def __init__(self, settings: Optional[PipelineSettings] = None) -> None:
        super().__init__(settings)

    def _homepage_candidates(self, limit: int) -> List[Dict]:
        for url in (f"{self.base_url}/salta", self.base_url):
            html = fetch_html(url, referer=self.base_url)
            if not html:
                continue
            results = self._parse_homepage_html(html, limit)
            if results:
                return results
        return []

    def _parse_homepage_html(self, html: str, limit: int) -> List[Dict]:
        soup = BeautifulSoup(html, "html.parser")
        rows: List[Dict] = []
        seen: set = set()
        for node in soup.select(".nota"):
            url = self._pick_url(node)
            if not url or url in seen or not self._is_article_url(url):
                continue
            title = self._pick_title(node)
            if not title:
                continue
            seen.add(url)
            rows.append({"id": url, "url": url, "titulo": title, "extracto": self._pick_extracto(node, title)})
            if len(rows) >= limit:
                break
        return rows

    def _pick_url(self, node) -> str:
        for link in node.select("a[href]"):
            url = normalize_article_url(str(link.get("href") or ""), self.base_url)
            if url and self._is_article_url(url):
                return url
        return ""

    def _pick_title(self, node) -> str:
        for sel in (".nota__titulo-item", ".nota__titulo h1", ".nota__titulo h2", "h1", "h2", "h3"):
            tag = node.select_one(sel)
            if tag:
                text = clean_text(tag.get_text(" ", strip=True))
                if len(text) >= 10:
                    return text
        return ""

    def _pick_extracto(self, node, titulo: str) -> str:
        for sel in (".nota__introduccion", ".nota__intro", ".articulo__intro"):
            tag = node.select_one(sel)
            if tag:
                text = clean_text(tag.get_text(" ", strip=True))
                if text and text != titulo:
                    return text
        return ""

    def _article_detail(self, url: str, title_hint: str = "") -> Dict:
        best: Optional[Dict] = None
        for candidate in (url, f"{url.rstrip('/')}/amp"):
            html = fetch_html(candidate, referer=self.base_url)
            if not html:
                continue
            result = self._parse_article_html(html, url, title_hint)
            if best is None or len(result.get("parrafos") or []) > len(best.get("parrafos") or []):
                if best and best.get("video_candidates") and not result.get("video_candidates"):
                    result["video_candidates"] = best["video_candidates"]
                best = result
            if len(result.get("parrafos") or []) >= 3:
                break
        return best or {}

    def _parse_article_html(self, html: str, url: str, title_hint: str) -> Dict:
        soup = BeautifulSoup(html, "html.parser")
        json_ld = extract_json_ld(soup)

        h1 = soup.select_one("h1.articulo__titulo") or soup.select_one("h1")
        title = clean_text(h1.get_text(" ", strip=True) if h1 else "") or title_hint

        intro = soup.select_one(".articulo__intro")
        extracto = clean_text(intro.get_text(" ", strip=True) if intro else "")
        if not extracto:
            extracto = clean_text(str(json_ld.get("description") or ""))
            if not extracto:
                meta = soup.find("meta", property="og:description")
                extracto = clean_text(str((meta or {}).get("content") or ""))

        media = soup.select_one(".articulo__media")
        body = soup.select_one(".articulo__cuerpo") or soup.select_one(".articulo__body")
        videos = dedupe_candidates(
            videos_in_container(media, self.base_url, location="cover")
            + videos_in_container(body, self.base_url, location="body")
        )
        parrafos = self._extract_body_paragraphs(body, extracto, title)

        images: List[str] = []
        for img in (media.select("amp-img[src], img[src]") if media else []):
            src = str(img.get("src") or "")
            if _CDN_RE.match(src) and jpeg_variant(src) not in images:
                images.append(jpeg_variant(src))
        if not images:
            og = extract_og_image(soup, self.base_url)
            if og:
                images.append(jpeg_variant(og))

        published = extract_published_date(soup, json_ld)
        if not published:
            match = re.search(r"/(\d{4})-(\d{1,2})-(\d{1,2})-(\d{1,2})-(\d{1,2})-", url)
            if match:
                y, mo, d, h, mi = match.groups()
                published = f"{y}-{mo.zfill(2)}-{d.zfill(2)}T{h.zfill(2)}:{mi.zfill(2)}:00-03:00"

        return {
            "titulo": title,
            "extracto": extracto,
            "parrafos": parrafos,
            "imagenes_url": images[:6],
            "video_candidates": [candidate.as_dict() for candidate in videos],
            "fecha_publicacion": published,
        }

    def _extract_body_paragraphs(self, body, extracto: str, titulo: str) -> List[str]:
        if body is None:
            return [extracto] if extracto else []
        for tag in body.select("script, style, .tags, .social-bar, .anticipo-cont, .suscripcion-page, .mas-leidas"):
            tag.decompose()
        paragraphs: List[str] = []
        seen: set = set()
        low_extracto = extracto.lower()
        low_titulo = titulo.lower()
        for block in body.find_all(["p", "h2", "h3", "li", "blockquote"]):
            text = clean_text(block.get_text(" ", strip=True))
            if not text or len(text) < 30:
                continue
            low = text.lower()
            if low in seen or low == low_extracto or low == low_titulo:
                continue
            if any(tok in low for tok in _TEXT_EXCLUDE):
                continue
            paragraphs.append(text)
            seen.add(low)
            if len(paragraphs) >= 12:
                break
        return paragraphs or ([extracto] if extracto else [])

    def _is_article_url(self, url: str) -> bool:
        if not url or not url.startswith(self.base_url):
            return False
        low = url.lower()
        for tok in self.article_url_exclude:
            if tok in low:
                return False
        return bool(_ARTICLE_RE.search(urlparse(url).path))

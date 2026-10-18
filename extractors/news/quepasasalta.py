"""Que Pasa Salta (Vincolo CMS): articulo, galeria y videos incrustados desde X.

El sitio no publica RSS: los candidatos salen de la portada y de las secciones
locales. Muchas notas incrustan el tuit del propio medio con el video del hecho
(``blockquote.twitter-tweet``): ese tuit se toma como video de la nota y se
resuelve con yt-dlp en ``utils/media_resolver.py``. Esto NO es scraping de
cuentas de X: solo se mira el tuit que ya esta dentro del articulo.

El JSON-LD a veces declara un ``.mp4`` como imagen: suele ser un preview animado
de ~2 s, que el resolvedor descarta por duracion minima.
Las tarjetas de notas relacionadas (``article.item``) no se miran.
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from extractors.news.html_scraper import HtmlNewsExtractor, clean_text, fetch_html, normalize_article_url
from extractors.news.media import VideoCandidate, classify_video_url, dedupe_candidates, json_ld_blocks, videos_in_container
from storage.settings import PipelineSettings

# Secciones que no publican hechos periodisticos.
_NON_NEWS_SECTIONS = {"horoscopo", "autor", "institucional", "tags", "tag", "buscar", "contacto"}
_ARTICLE_RE = re.compile(r"^https://www\.quepasasalta\.com\.ar/([a-z0-9-]+)/([a-z0-9-]{12,})/?$")
_LISTING_PAGES = ("/", "/salta/", "/policiales/", "/sociedad/", "/politica/", "/tiro-libre/", "/zapping/")
_TEXT_EXCLUDE = ("seguí leyendo", "segui leyendo", "suscribite", "mirá también", "lee también", "leé también")


class QuePasaSaltaExtractor(HtmlNewsExtractor):
    source = "quepasasalta"
    base_url = "https://www.quepasasalta.com.ar"
    category = "salta"
    rss_feeds: List[str] = []

    def __init__(self, settings: Optional[PipelineSettings] = None) -> None:
        super().__init__(settings)

    def _rss_candidates(self, limit: int) -> List[Dict]:
        return []

    def _homepage_candidates(self, limit: int) -> List[Dict]:
        rows: List[Dict] = []
        seen: set = set()
        for page in _LISTING_PAGES:
            html = fetch_html(f"{self.base_url}{page}", referer=self.base_url)
            if not html:
                continue
            soup = BeautifulSoup(html, "html.parser")
            for link in soup.select("a[href]"):
                url = normalize_article_url(str(link.get("href") or ""), self.base_url) + "/"
                if url in seen or not self._is_article_url(url):
                    continue
                title = clean_text(link.get("title") or link.get_text(" ", strip=True))
                seen.add(url)
                rows.append({"id": url, "url": url, "titulo": title})
            if len(rows) >= limit * 2:
                break
        return rows[: max(limit, 1) * 2]

    def _article_detail(self, url: str, title_hint: str = "") -> Dict:
        html = fetch_html(url, referer=self.base_url)
        if not html:
            return {}
        return self.parse_article_html(html, url, title_hint)

    def parse_article_html(self, html: str, url: str, title_hint: str = "") -> Dict:
        soup = BeautifulSoup(html, "html.parser")
        article_ld: Dict = {}
        for block in json_ld_blocks(soup):
            if str(block.get("@type") or "") == "NewsArticle":
                article_ld = block
                break
        h1 = soup.select_one("h1.content-title") or soup.select_one("h1")
        title = clean_text(h1.get_text(" ", strip=True) if h1 else "") or clean_text(str(article_ld.get("headline") or "")) or title_hint
        summary = clean_text(str(article_ld.get("description") or ""))

        body = soup.select_one(".vsmcontent") or soup.select_one(".content .body") or soup.select_one(".body")
        if body is not None:
            for related in body.select("article.item, .piece, .zone, .adbanner"):
                related.decompose()
        paragraphs: List[str] = []
        seen: set = set()
        for block in (body.find_all(["p", "h2", "h3", "li"]) if body else []):
            if block.find_parent("blockquote"):
                continue
            text = clean_text(block.get_text(" ", strip=True))
            if len(text) < 30 or text.lower() in seen or text == title:
                continue
            if any(token in text.lower() for token in _TEXT_EXCLUDE):
                continue
            seen.add(text.lower())
            paragraphs.append(text)
            if len(paragraphs) >= 14:
                break

        media = soup.select_one(".content-media")
        videos: List[VideoCandidate] = videos_in_container(media, self.base_url, location="cover")
        ld_image = str(article_ld.get("image") or "")
        if classify_video_url(ld_image) == "mp4":
            videos.append(VideoCandidate(url=ld_image, kind="mp4", location="cover", provider="quepasasalta"))
        videos += videos_in_container(body, self.base_url, location="body")
        videos = dedupe_candidates(videos)

        images: List[str] = []
        for img in (media.select("img[src]") if media else []):
            src = str(img.get("src") or "")
            if src.startswith("http") and src not in images:
                images.append(src)
        if ld_image and not classify_video_url(ld_image):
            images.append(ld_image)
        if not images:
            og = soup.find("meta", property="og:image")
            if og and og.get("content"):
                images.append(str(og["content"]))

        return {
            "titulo": title,
            "extracto": summary,
            "parrafos": paragraphs,
            "imagenes_url": images[:6],
            "video_candidates": [candidate.as_dict() for candidate in videos],
            "fecha_publicacion": str(article_ld.get("datePublished") or ""),
            "categoria": urlparse(url).path.strip("/").split("/", 1)[0],
        }

    def _is_article_url(self, url: str) -> bool:
        match = _ARTICLE_RE.match(url or "")
        return bool(match) and match.group(1) not in _NON_NEWS_SECTIONS

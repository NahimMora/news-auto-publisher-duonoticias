"""Gendarmeria Nacional (argentina.gob.ar, 2026-10-22): solo los procedimientos en Salta.

El listado (``/gendarmeria/noticias``, Drupal) trae las tarjetas de todo el pais; se baja el
detalle de cada una y se queda solo con lo que ocurrio en Salta: el titulo empieza con
"Salta" o el titulo/bajada/primer parrafo nombra una localidad saltena (Oran, Salvador Mazza,
Aguas Blancas, la ruta 50...). Una nota encabezada por otra provincia ("Chaco: ...") no entra
aunque mencione Salta de paso. Son operativos que los medios levantan tarde o no levantan.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Dict, List, Optional

from bs4 import BeautifulSoup

from extractors.news.html_scraper import HtmlNewsExtractor, clean_text, fetch_html, normalize_article_url
from storage.settings import PipelineSettings

_LISTING_PAGES = ("/gendarmeria/noticias", "/node/34987/noticias?page=1")
_SALTA_PLACES = (
    "salta", "oran", "salvador mazza", "aguas blancas", "tartagal", "pichanal", "embarcacion", "general mosconi",
    "aguaray", "colonia santa rosa", "hipolito yrigoyen", "joaquin v. gonzalez", "las lajitas", "apolinario saravia",
    "rosario de la frontera", "metan", "guemes", "cafayate", "cerrillos", "san antonio de los cobres", "tolar grande",
    "rio bermejo", "ruta nacional n°50", "ruta nacional 50", "ruta 50", "profesor salvador mazza", "santa victoria",
)
_OTHER_PROVINCES = (
    "jujuy", "tucuman", "chaco", "formosa", "misiones", "corrientes", "santiago del estero", "catamarca", "la rioja",
    "san juan", "mendoza", "san luis", "cordoba", "santa fe", "entre rios", "buenos aires", "la pampa", "neuquen",
    "rio negro", "chubut", "santa cruz", "tierra del fuego", "caba",
)


def _plain(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


def other_province(title: str) -> bool:
    """Titulo encabezado por otra provincia: "Chaco: ...", "En La Rioja incautaron...", "Santiago del Estero Detuvieron..."."""
    head = re.sub(r"^en\s+", "", _plain(title)[:40])
    return any(head.startswith(p) for p in _OTHER_PROVINCES)


def is_salta(title: str, text: str) -> bool:
    if other_province(title):
        return False
    haystack = _plain(f"{title} {text}")
    return any(re.search(rf"\b{re.escape(place)}\b", haystack) for place in _SALTA_PLACES)


class GendarmeriaExtractor(HtmlNewsExtractor):
    source = "gendarmeria"
    base_url = "https://www.argentina.gob.ar"
    category = "policiales"
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
            for link in soup.select('a[href^="/noticias/"]'):
                url = normalize_article_url(str(link.get("href") or ""), self.base_url)
                if url in seen:
                    continue
                seen.add(url)
                heading = link.select_one("h3") or link.select_one("h4")
                title = clean_text(heading.get_text(" ", strip=True) if heading else link.get_text(" ", strip=True))
                if other_province(re.sub(r"^\d{1,2} de \w+ de \d{4}\s*", "", title)):
                    continue  # sin bajar el detalle
                rows.append({"id": url, "url": url, "titulo": title})
        return rows[: max(limit, 1) * 2]

    def scan(self, max_items: int = 10, known=None):
        # El filtro de Salta necesita el detalle: se miran todas las tarjetas del listado.
        return super().scan(max_items=max(max_items, 30), known=known)

    def _article_detail(self, url: str, title_hint: str = "") -> Dict:
        html = fetch_html(url, referer=self.base_url)
        if not html:
            return {}
        return self.parse_article_html(html, url, title_hint)

    def parse_article_html(self, html: str, url: str, title_hint: str = "") -> Dict:
        soup = BeautifulSoup(html, "html.parser")

        def meta(prop: str) -> str:
            tag = soup.find("meta", property=prop)
            return str(tag.get("content") or "") if tag else ""

        title = clean_text(meta("og:title").split("|")[0]) or title_hint
        summary = clean_text(meta("og:description"))
        body = soup.select_one("article") or soup
        paragraphs: List[str] = []
        for block in body.find_all("p"):
            text = clean_text(block.get_text(" ", strip=True))
            if len(text) >= 30 and text not in paragraphs:
                paragraphs.append(text)
            if len(paragraphs) >= 14:
                break
        if not is_salta(title, " ".join([summary, *paragraphs[:2]])):
            return {}  # procedimiento de otra provincia
        image = meta("og:image")
        return {
            "titulo": title,
            "extracto": summary,
            "parrafos": paragraphs,
            "imagenes_url": [image] if image else [],
            "video_candidates": [],
            "fecha_publicacion": meta("article:published_time"),
        }

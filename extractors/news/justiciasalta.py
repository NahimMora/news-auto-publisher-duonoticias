"""Justicia Salta extractor — ported from HolaSalta scraper pattern."""
from __future__ import annotations

import re
from typing import List, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from extractors.news.html_scraper import (
    HtmlNewsExtractor,
    clean_text,
    extract_json_ld,
    extract_og_image,
    extract_published_date,
    extract_paragraphs,
    fetch_html,
)
from storage.settings import PipelineSettings


_URL_EXCLUDE = (
    "/contenidos/", "/css-", "/css-custom/", "/services/", "/static/",
    "/assets/", "/wp-content/", "/authors/", "/tags/", "/buscar", "/search",
    "#", "javascript:", ".jpg", ".png", ".gif", ".css", ".js", "/amp/",
)

_TEXT_EXCLUDE = (
    "suscribite a nuestro newsletter", "te puede interesar", "informate mas",
    "todos los detalles", "deja tu comentario", "por taboola", "leer mas",
    "contenido premium", "ver en x", "mirar en x",
)


class JusticiaSaltaExtractor(HtmlNewsExtractor):
    source_name = "justiciasalta"
    base_url = "https://www.justiciasalta.gov.ar"
    _HOMEPAGE_URL = "https://www.justiciasalta.gov.ar/es/prensa"

    def __init__(self, settings: Optional[PipelineSettings] = None) -> None:
        super().__init__(settings)

    def _is_article_url(self, url: str) -> bool:
        if not url or not url.startswith(self.base_url):
            return False
        parsed = urlparse(url)
        path = parsed.path.lower()
        for pat in _URL_EXCLUDE:
            if pat in url.lower():
                return False
        return "/es/prensa-detalle/" in path

    def _homepage_candidates(self, limit: int) -> List[dict]:
        html = fetch_html(self._HOMEPAGE_URL, referer=self.base_url)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        candidates = []
        seen: set = set()

        for article in soup.select("li.article-container article.i-collapsible-detail"):
            link = article.find("a", href=True)
            if not link:
                continue
            href = link.get("href", "")
            url = href if href.startswith("http") else urljoin(self.base_url, href)
            if url in seen or not self._is_article_url(url):
                continue
            seen.add(url)

            title_tag = article.find("h1", class_="title") or article.find("h2") or article.find("h3")
            title = clean_text(title_tag.get_text(" ", strip=True) if title_tag else link.get_text(" ", strip=True))
            if not title:
                continue

            time_tag = article.find("time", datetime=True)
            pub_date = time_tag.get("datetime") if time_tag else None

            candidates.append({
                "url": url,
                "title": title,
                "published_at": pub_date,
                "image_url": None,
            })
            if len(candidates) >= limit:
                break

        if not candidates:
            for a in soup.select("a[href*='/es/prensa-detalle/']"):
                href = a.get("href", "")
                url = href if href.startswith("http") else urljoin(self.base_url, href)
                if url in seen or not self._is_article_url(url):
                    continue
                seen.add(url)
                title = clean_text(a.get_text(" ", strip=True))
                if not title or len(title) < 5:
                    continue
                candidates.append({"url": url, "title": title, "published_at": None, "image_url": None})
                if len(candidates) >= limit:
                    break

        return candidates

    def _article_detail(self, url: str, candidate: dict) -> Optional[dict]:
        html = fetch_html(url, referer=self.base_url)
        if not html:
            return None
        soup = BeautifulSoup(html, "html.parser")

        jld = extract_json_ld(soup)
        title = (
            clean_text((soup.find("h1", class_="title") or soup.find("h1") or soup.new_tag("x")).get_text(" "))
            or jld.get("headline", "")
            or candidate.get("title", "")
        )
        if not title:
            return None

        summary = ""
        for meta in (
            soup.find("meta", property="og:description"),
            soup.find("meta", attrs={"name": "description"}),
        ):
            if meta and meta.get("content"):
                summary = clean_text(meta["content"])
                break

        paras = extract_paragraphs(
            soup,
            ["div.content-detail", "div.entry-content", "article", "main"],
            exclude_tokens=_TEXT_EXCLUDE,
        )
        body_text = "\n\n".join(paras)

        pub_date, _ = extract_published_date(soup)
        if not pub_date:
            time_tag = soup.find("time", datetime=True)
            pub_date = time_tag.get("datetime") if time_tag else candidate.get("published_at", "")

        image_url = extract_og_image(soup) or candidate.get("image_url", "")

        return {
            "title": title,
            "summary": summary,
            "body_text": body_text,
            "published_at": pub_date,
            "image_url": image_url,
            "canonical_url": url,
            "source": self.source_name,
        }

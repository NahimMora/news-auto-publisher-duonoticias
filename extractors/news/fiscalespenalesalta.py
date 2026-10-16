"""Fiscales Penales Salta extractor — ported from HolaSalta scraper pattern."""
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
    "/wp-content/", "/wp-json/", "/xmlrpc.php", "/comments/", "/feed/",
    "/category/", "/categoria/", "/tag/", "/author/", "/search", "?s=",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".css", ".js",
    "javascript:", "#", "/page/",
)

_TEXT_EXCLUDE = (
    "suscribite", "deja un comentario", "compartir", "relacionadas",
    "newsletter", "te puede interesar", "publicidad", "siguiente nota",
)


class FiscalesPenalesSaltaExtractor(HtmlNewsExtractor):
    source_name = "fiscalespenalesalta"
    base_url = "https://www.fiscalespenalesalta.gob.ar"

    _ARTICLE_RE = re.compile(
        r"^/[a-z0-9][a-z0-9\-]{10,}/?$", re.IGNORECASE
    )

    def __init__(self, settings: Optional[PipelineSettings] = None) -> None:
        super().__init__(settings)

    def _is_article_url(self, url: str) -> bool:
        if not url or not url.startswith(self.base_url):
            return False
        parsed = urlparse(url)
        path = parsed.path.rstrip("/")
        if not path or parsed.query or parsed.fragment:
            return False
        for pat in _URL_EXCLUDE:
            if pat in url.lower():
                return False
        if not self._ARTICLE_RE.match(path):
            return False
        slug = path.strip("/")
        return "-" in slug and len(slug) >= 15

    def _homepage_candidates(self, limit: int) -> List[dict]:
        html = fetch_html(self.base_url + "/", referer=self.base_url)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        candidates = []
        seen: set = set()

        grid = soup.select_one("div.mnky-posts-grid")
        items_src = grid.select('div.mpg-item[itemscope]') if grid else []
        if not items_src:
            items_src = soup.select("article")

        for card in items_src:
            link = (
                card.select_one("a.mpg-bg-url[href]")
                or card.select_one('a[itemprop="mainEntityOfPage"][href]')
                or card.find("a", href=True)
            )
            if not link:
                continue
            href = link.get("href", "")
            url = href if href.startswith("http") else urljoin(self.base_url, href)
            if url in seen or not self._is_article_url(url):
                continue
            seen.add(url)

            title_tag = card.select_one('[itemprop="headline"], h1, h2, h3, h4')
            title = clean_text(title_tag.get_text(" ", strip=True) if title_tag else link.get_text(" ", strip=True))
            if not title:
                continue

            time_tag = card.select_one('time[itemprop="datePublished"][datetime]')
            pub_date = time_tag.get("datetime") if time_tag else None

            img_tag = card.select_one("img[src]")
            image_url = img_tag.get("src") if img_tag else None

            candidates.append({
                "url": url,
                "title": title,
                "published_at": pub_date,
                "image_url": image_url,
            })
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
            clean_text((soup.select_one("h1.entry-title") or soup.find("h1") or soup.new_tag("x")).get_text(" "))
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
            ["article.single-layout div.entry-content", "div.entry-content", "article"],
            exclude_tokens=_TEXT_EXCLUDE,
        )
        body_text = "\n\n".join(paras)

        pub_date, _ = extract_published_date(soup)
        if not pub_date:
            pub_date = candidate.get("published_at", "")

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

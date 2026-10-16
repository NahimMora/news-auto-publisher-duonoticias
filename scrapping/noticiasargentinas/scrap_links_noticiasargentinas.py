"""Scraper de enlaces/titulos para Noticias Argentinas."""
import re
from urllib.parse import urljoin
from typing import List, Dict, Optional

from bs4 import BeautifulSoup

try:
    from utils.http_client import HttpClient
except ImportError:  # pragma: no cover
    import sys
    from pathlib import Path
    ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(ROOT))
    from utils.http_client import HttpClient

try:
    from scrapping.noticiasargentinas.config import (
        BASE_URL,
        HOMEPAGE_URL,
        URL_EXCLUDE_PATTERNS,
        REQUEST_TIMEOUT,
        HTTP_RETRIES,
        HTTP_BACKOFF_BASE,
        get_random_user_agent,
    )
    from scrapping.noticiasargentinas.logger import ScraperLogger
except ImportError:
    from .config import (
        BASE_URL,
        HOMEPAGE_URL,
        URL_EXCLUDE_PATTERNS,
        REQUEST_TIMEOUT,
        HTTP_RETRIES,
        HTTP_BACKOFF_BASE,
        get_random_user_agent,
    )
    from .logger import ScraperLogger


class LinkScraper:
    def __init__(self, logger=None):
        self.logger = logger or ScraperLogger("NoticiasArgentinasLinks")
        self.base_url = BASE_URL
        self.homepage_url = HOMEPAGE_URL

    def is_valid_news_url(self, url: str) -> bool:
        if not url:
            return False
        url_lower = url.lower()
        for pattern in URL_EXCLUDE_PATTERNS:
            if pattern in url_lower:
                return False
        if not url_lower.startswith(self.base_url.lower()):
            return False
        if not re.search(r"_a[0-9a-f]{6,}", url_lower):
            return False
        return True

    def _normalize_url(self, href: str) -> Optional[str]:
        if not href:
            return None
        href = href.strip()
        if href.startswith("//"):
            return "https:" + href
        if href.startswith("/"):
            return urljoin(self.base_url, href)
        if href.startswith("http"):
            return href
        return None

    def extract_titles_from_soup(self, soup: BeautifulSoup) -> List[Dict]:
        titles: Dict[str, Dict] = {}

        def add_candidate(url: Optional[str], title: str) -> None:
            if not url or not self.is_valid_news_url(url):
                return
            clean_title = (title or "").strip()
            if not clean_title:
                return
            if url not in titles or len(clean_title) > len(titles[url].get("titulo", "")):
                titles[url] = {"url": url, "titulo": clean_title}

        for article in soup.find_all("article"):
            link = article.find("a", href=True)
            if not link:
                continue
            url = self._normalize_url(link.get("href"))
            title_tag = article.find(["h1", "h2", "h3", "h4"])
            title = title_tag.get_text(strip=True) if title_tag else link.get_text(strip=True)
            add_candidate(url, title)

        for tag in ["h1", "h2", "h3", "h4"]:
            for header in soup.find_all(tag):
                link = header.find("a", href=True)
                if not link:
                    continue
                url = self._normalize_url(link.get("href"))
                title = header.get_text(strip=True) or link.get_text(strip=True)
                add_candidate(url, title)

        for link in soup.find_all("a", href=True):
            url = self._normalize_url(link.get("href"))
            title = link.get_text(strip=True)
            if not title or len(title) < 5:
                continue
            add_candidate(url, title)

        return list(titles.values())

    def get_article_titles(self) -> List[Dict]:
        self.logger.info(f"Conectando a {self.homepage_url}")
        client = HttpClient(
            headers={"User-Agent": get_random_user_agent()},
            timeout=REQUEST_TIMEOUT,
            retries=HTTP_RETRIES,
            backoff_base=HTTP_BACKOFF_BASE,
            backoff_max=10,
        )
        try:
            resp = client.get(self.homepage_url)
            resp.raise_for_status()
            html = resp.text
        except Exception as exc:
            self.logger.error(f"Error al obtener titulos: {exc}")
            return []
        finally:
            client.close()

        soup = BeautifulSoup(html, "html.parser")
        titles = self.extract_titles_from_soup(soup)
        self.logger.success(f"Se encontraron {len(titles)} titulos")
        return titles


def get_article_titles(logger: Optional[ScraperLogger] = None, max_articles: Optional[int] = None) -> List[Dict]:
    scraper = LinkScraper(logger)
    titles = scraper.get_article_titles()
    if max_articles:
        return titles[:max_articles]
    return titles


if __name__ == "__main__":
    log = ScraperLogger("NoticiasArgentinasLinksTest")
    items = get_article_titles(logger=log, max_articles=10)
    log.info(f"Total: {len(items)}")
    for idx, item in enumerate(items, 1):
        print(f"{idx:02d}. {item.get('titulo')} -> {item.get('url')}")


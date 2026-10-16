"""Fetch article links and titles from Paparazzi using the WordPress API."""
import html
import re
import time
from typing import List, Dict, Optional

try:
    from utils.http_client import HttpClient
except ImportError:  # pragma: no cover
    import sys
    from pathlib import Path
    ROOT = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(ROOT))
    from utils.http_client import HttpClient

try:
    from scrapping.paparazzi.config import (
        POSTS_ENDPOINT,
        PER_PAGE,
        MAX_PAGES,
        REQUEST_TIMEOUT,
        get_random_user_agent,
    )
    from scrapping.paparazzi.logger import ScraperLogger
except ImportError:
    from .config import POSTS_ENDPOINT, PER_PAGE, MAX_PAGES, REQUEST_TIMEOUT, get_random_user_agent
    from .logger import ScraperLogger


def _strip_html(raw_html: str) -> str:
    if not raw_html:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw_html)
    text = re.sub(r"\s+", " ", text).strip()
    return html.unescape(text).strip()


def _fetch_posts(page: int, per_page: int, logger: Optional[ScraperLogger] = None) -> List[dict]:
    headers = {"User-Agent": get_random_user_agent()}
    params = {
        "per_page": per_page,
        "page": page,
        "_embed": "1",
    }
    client = HttpClient(headers=headers, timeout=REQUEST_TIMEOUT, retries=3, backoff_base=1, backoff_max=10)
    try:
        resp = client.get(POSTS_ENDPOINT, params=params)
        if resp.status_code == 400:
            return []
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        if logger:
            logger.warning(f"Error fetching page {page}: {exc}")
        return []
    finally:
        client.close()


def get_article_titles(max_articles: Optional[int] = None, logger: Optional[ScraperLogger] = None) -> List[Dict]:
    logger = logger or ScraperLogger("PaparazziLinks")
    results: List[Dict] = []

    page = 1
    while page <= MAX_PAGES:
        posts = _fetch_posts(page, PER_PAGE, logger)
        if not posts:
            break

        for post in posts:
            title = _strip_html(post.get("title", {}).get("rendered", ""))
            url = post.get("link")
            if not url:
                continue
            results.append({
                "id": post.get("id"),
                "url": url,
                "titulo": title,
                "fecha_publicacion": post.get("date"),
            })
            if max_articles and len(results) >= max_articles:
                return results

        page += 1
        time.sleep(0.3)

    return results


def get_article_links(max_articles: Optional[int] = None, logger: Optional[ScraperLogger] = None) -> List[str]:
    titles = get_article_titles(max_articles=max_articles, logger=logger)
    return [item["url"] for item in titles if item.get("url")]


if __name__ == "__main__":
    log = ScraperLogger("PaparazziLinksTest")
    log.header("TEST LINKS PAPARAZZI")
    items = get_article_titles(max_articles=10, logger=log)
    log.info(f"Total: {len(items)}")
    for idx, item in enumerate(items, 1):
        print(f"{idx:02d}. {item.get('titulo')} -> {item.get('url')}")

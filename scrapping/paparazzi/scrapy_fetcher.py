import logging
from typing import Dict, Iterable, Optional

import scrapy
from scrapy.crawler import CrawlerProcess
from scrapy import signals

from scrapping.paparazzi.config import REQUEST_TIMEOUT, get_random_user_agent


class PaparazziPageSpider(scrapy.Spider):
    name = "paparazzi_pages"

    custom_settings = {
        "LOG_ENABLED": False,
        "RETRY_ENABLED": True,
        "RETRY_TIMES": 3,
        "RETRY_HTTP_CODES": [429, 500, 502, 503, 504],
        "DOWNLOAD_TIMEOUT": REQUEST_TIMEOUT,
        "AUTOTHROTTLE_ENABLED": True,
        "AUTOTHROTTLE_START_DELAY": 0.5,
        "AUTOTHROTTLE_MAX_DELAY": 5.0,
        "CONCURRENT_REQUESTS": 4,
        "DOWNLOAD_DELAY": 0.2,
    }

    def __init__(self, urls: Optional[Iterable[str]] = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.start_urls = list(urls or [])
        self._ua = get_random_user_agent()

    def start_requests(self):
        headers = {
            "User-Agent": self._ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
        }
        for url in self.start_urls:
            yield scrapy.Request(url, headers=headers, dont_filter=True)

    def parse(self, response):
        blocked = response.status in (403, 429) or "captcha" in response.text.lower()
        yield {
            "url": response.url,
            "status": response.status,
            "blocked": blocked,
            "html": response.text,
        }


def fetch_html_map(urls: Iterable[str], logger: Optional[logging.Logger] = None) -> Dict[str, str]:
    url_list = [u for u in urls if u]
    if not url_list:
        return {}

    items = []
    crawler_process = CrawlerProcess()

    def _collect_item(item, response, spider):
        items.append(dict(item))

    crawler = crawler_process.create_crawler(PaparazziPageSpider)
    crawler.signals.connect(_collect_item, signal=signals.item_scraped)
    crawler_process.crawl(crawler, urls=url_list)
    crawler_process.start()

    html_map: Dict[str, str] = {}
    for item in items:
        url = item.get("url")
        html = item.get("html")
        if not url or not html:
            continue
        if item.get("blocked") and logger:
            logger.warning(f"Bloqueo detectado en {url}")
        html_map[url] = html
    return html_map

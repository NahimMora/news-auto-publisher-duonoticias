"""Main runner for Paparazzi scraper."""
import os
import sys
from datetime import datetime
from pathlib import Path

# Encoding for Windows console
if sys.platform == "win32":
    import codecs
    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, "strict")
    sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, "strict")
    os.system("chcp 65001 > nul 2>&1")

SCRIPT_PATH = Path(__file__).resolve()
PAPARAZZI_DIR = SCRIPT_PATH.parent
SCRAPPING_DIR = PAPARAZZI_DIR.parent
PROJECT_ROOT = SCRAPPING_DIR.parent

sys.path.insert(0, str(PROJECT_ROOT))

try:
    from scrapping.paparazzi.config import (
        DATA_PATH,
        FOTOS_PATH,
        VIDEOS_PATH,
        HISTORICO_PATH,
        MAX_CONSECUTIVE_ERRORS,
        CONTINUE_ON_ERROR,
        LOGS_PATH,
    )
    from scrapping.paparazzi.logger import ScraperLogger
    from scrapping.paparazzi.scrap_links_paparazzi import get_article_titles
    from scrapping.paparazzi.scrap_news_paparazzi import scrap_noticia_paparazzi
    from scrapping.paparazzi.scrapy_fetcher import fetch_html_map
    from utils.file_manager import load_json, save_json
except ImportError as exc:
    print(f"[ERROR] Import error: {exc}")
    sys.exit(1)

DATA_PATH.mkdir(parents=True, exist_ok=True)
FOTOS_PATH.mkdir(parents=True, exist_ok=True)
VIDEOS_PATH.mkdir(parents=True, exist_ok=True)
LOGS_PATH.mkdir(parents=True, exist_ok=True)


class PaparazziScraper:
    def __init__(self, only_today=True):
        log_file = LOGS_PATH / f"paparazzi_scraper_{datetime.now().strftime('%Y%m%d')}.log"
        self.logger = ScraperLogger("Paparazzi", log_file=log_file)
        self.only_today = only_today
        self.today = datetime.now().date()

    def load_history(self):
        self.logger.info("Loading history...")
        history = load_json(str(HISTORICO_PATH), default=[])
        self.logger.success(f"History loaded: {len(history)}")
        return history

    def save_history(self, history):
        save_json(str(HISTORICO_PATH), history)
        self.logger.success(f"History saved: {len(history)}")

    def save_new_articles(self, articles, suffix=""):
        if not articles:
            self.logger.info("No new articles to save")
            return None
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
        filename = f"nuevas_noticias_paparazzi{suffix}_{timestamp}.json"
        filepath = DATA_PATH / filename
        save_json(str(filepath), articles)
        self.logger.success(f"Saved: {filename}")
        return str(filepath)

    def is_today_article(self, article):
        fecha = article.get("fecha_publicacion")
        if not fecha:
            return False
        try:
            dt = datetime.fromisoformat(fecha)
            return dt.date() == self.today
        except Exception:
            return False

    def is_already_processed(self, post_id, url, history):
        for item in history:
            if post_id and item.get("id") == post_id:
                return True
            if url and item.get("url") == url:
                return True
        return False

    def run(self, max_articles=None):
        filter_msg = "SOLO HOY" if self.only_today else "TODAS"
        self.logger.header(f"SCRAPER PAPARAZZI - {filter_msg}")
        start = datetime.now()

        history = self.load_history()

        self.logger.separator()
        self.logger.info("Fetching article list...")
        items = get_article_titles(max_articles=max_articles, logger=self.logger)
        if not items:
            self.logger.error("No articles found.")
            return

        self.logger.separator()
        self.logger.info(f"Processing {len(items)} items...")

        new_articles = []
        errors = 0
        consecutive_errors = 0

        pending_items = [item for item in items if not self.is_already_processed(item.get("id"), item.get("url"), history)]
        if max_articles:
            pending_items = pending_items[: max_articles * 3]
        html_map = fetch_html_map([item.get("url") for item in pending_items if item.get("url")], logger=self.logger)

        for idx, item in enumerate(items, 1):
            url = item.get("url")
            post_id = item.get("id")

            if self.is_already_processed(post_id, url, history):
                self.logger.info(f"[{idx}/{len(items)}] Skipping (already processed)")
                continue

            self.logger.info(f"[{idx}/{len(items)}] Processing: {url}")
            page_html = html_map.get(url)
            article = scrap_noticia_paparazzi(url, str(FOTOS_PATH), self.logger, post_id=post_id, page_html=page_html)

            if not article.get("titulo"):
                errors += 1
                consecutive_errors += 1
                self.logger.warning("Missing title, skipping")
            else:
                if self.only_today and not self.is_today_article(article):
                    self.logger.info("Filtered by date")
                else:
                    article["id"] = post_id
                    new_articles.append(article)
                    history.append(article)
                    self.logger.success("OK")
                consecutive_errors = 0

            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                self.logger.error("Too many consecutive errors, stopping")
                break

            if max_articles and len(new_articles) >= max_articles:
                break

        self.logger.separator()
        self.save_history(history)
        suffix = "_hoy" if self.only_today else ""
        saved = self.save_new_articles(new_articles, suffix=suffix)

        end = datetime.now()
        duration = (end - start).total_seconds()
        self.logger.separator()
        self.logger.header("RESUMEN")
        print(f"Total procesados: {len(items)}")
        print(f"Nuevas noticias:  {len(new_articles)}")
        print(f"Errores:          {errors}")
        print(f"Historial total:  {len(history)}")
        print(f"Tiempo total:     {duration:.1f}s")
        if saved:
            print(f"Archivo guardado: {Path(saved).name}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Scraper de Paparazzi")
    parser.add_argument("--all", action="store_true", help="No filtrar por fecha")
    parser.add_argument("--max", type=int, default=None, help="Maximo de noticias")
    args = parser.parse_args()

    scraper = PaparazziScraper(only_today=not args.all)
    scraper.run(max_articles=args.max)


if __name__ == "__main__":
    main()

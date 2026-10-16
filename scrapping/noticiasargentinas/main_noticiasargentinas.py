"""Main runner for Noticias Argentinas scraper."""
import os
import sys
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    import codecs
    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, "strict")
    sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, "strict")
    os.system("chcp 65001 > nul 2>&1")

SCRIPT_PATH = Path(__file__).resolve()
NA_DIR = SCRIPT_PATH.parent
SCRAPPING_DIR = NA_DIR.parent
PROJECT_ROOT = SCRAPPING_DIR.parent

sys.path.insert(0, str(PROJECT_ROOT))

try:
    from scrapping.noticiasargentinas.config import (
        DATA_PATH,
        FOTOS_PATH,
        HISTORICO_PATH,
        MAX_CONSECUTIVE_ERRORS,
        CONTINUE_ON_ERROR,
        LOGS_PATH,
    )
    from scrapping.noticiasargentinas.logger import ScraperLogger
    from scrapping.noticiasargentinas.scrap_links_noticiasargentinas import get_article_titles
    from scrapping.noticiasargentinas.scrap_news_noticiasargentinas import scrap_noticia_noticiasargentinas
    from utils.file_manager import load_json, save_json
except ImportError as exc:
    print(f"[ERROR] Import error: {exc}")
    sys.exit(1)

DATA_PATH.mkdir(parents=True, exist_ok=True)
FOTOS_PATH.mkdir(parents=True, exist_ok=True)
LOGS_PATH.mkdir(parents=True, exist_ok=True)


class NoticiasArgentinasScraper:
    def __init__(self, only_today=True):
        log_file = LOGS_PATH / f"noticiasargentinas_scraper_{datetime.now().strftime('%Y%m%d')}.log"
        self.logger = ScraperLogger("NoticiasArgentinas", log_file=log_file)
        self.only_today = only_today
        self.today = datetime.now().date()

    def _parse_spanish_date(self, date_text: str):
        months = {
            "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
            "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
            "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
        }
        try:
            cleaned = date_text.lower().strip().replace(" de ", " ")
            parts = cleaned.split()
            if len(parts) >= 3:
                day = int(parts[0])
                month = months.get(parts[1])
                year = int(parts[2])
                if month:
                    return datetime(year, month, day).date()
        except Exception:
            return None
        return None

    def _parse_article_date(self, article: dict):
        date_iso = article.get("fecha_publicacion")
        if date_iso:
            try:
                return datetime.fromisoformat(date_iso.replace("Z", "+00:00")).date()
            except Exception:
                pass
        date_text = article.get("fecha_texto")
        if date_text:
            return self._parse_spanish_date(date_text)
        return None

    def is_today_article(self, article: dict) -> bool:
        article_date = self._parse_article_date(article)
        return article_date == self.today

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
        filename = f"nuevas_noticias_noticiasargentinas{suffix}_{timestamp}.json"
        filepath = DATA_PATH / filename
        save_json(str(filepath), articles)
        self.logger.success(f"Saved: {filename}")
        return str(filepath)

    def is_already_processed(self, url, history):
        return any(item.get("url") == url for item in history)

    def run(self, max_articles=None):
        filter_msg = "SOLO HOY" if self.only_today else "TODAS"
        self.logger.header(f"SCRAPER NOTICIAS ARGENTINAS - {filter_msg}")
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

        for idx, item in enumerate(items, 1):
            url = item.get("url")
            if not url:
                continue
            if self.is_already_processed(url, history):
                self.logger.info(f"[{idx}/{len(items)}] Skipping (already processed)")
                continue

            self.logger.info(f"[{idx}/{len(items)}] Processing: {url}")
            article = scrap_noticia_noticiasargentinas(url, str(FOTOS_PATH), self.logger)

            if not article.get("titulo"):
                errors += 1
                consecutive_errors += 1
                self.logger.warning("Missing title, skipping")
            else:
                if self.only_today and not self.is_today_article(article):
                    self.logger.info("Filtered by date")
                else:
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

    parser = argparse.ArgumentParser(description="Scraper de Noticias Argentinas")
    parser.add_argument("--all", action="store_true", help="No filtrar por fecha")
    parser.add_argument("--max", type=int, default=None, help="Maximo de noticias")
    args = parser.parse_args()

    scraper = NoticiasArgentinasScraper(only_today=not args.all)
    scraper.run(max_articles=args.max)


if __name__ == "__main__":
    main()


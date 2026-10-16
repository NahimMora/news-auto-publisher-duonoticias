"""
Pipeline runner principal para AutoPublicador Duo.

Flujo:
1. Scrapea todas las fuentes habilitadas
2. Idempotencia: descarta contenidos ya procesados (SQLite)
3. Deduplicacion entre fuentes: descarta repetidos
4. Ranking por viralidad: selecciona top 10 noticias
5. Edicion editorial: caption <2500 chars con titulo/subtitulos/contenido/emojis
6. Publica en Instagram y Facebook via Meta Graph API

Uso:
    python pipeline_runner.py               # dry-run (sin publicar)
    python pipeline_runner.py --live        # publica en Instagram/Facebook
    python pipeline_runner.py --live --top 5  # publica top 5
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime

from jobs.pipeline import DuoPipeline
from storage.settings import get_settings


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/pipeline_runner.log", encoding="utf-8"),
    ],
)
# Fix Windows console encoding for Unicode chars
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf_8"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
logger = logging.getLogger("duo.runner")


def run(live: bool = False, top: int = 10, safe: bool = False) -> None:
    settings = get_settings()
    pipeline = DuoPipeline(settings)

    logger.info("=" * 56)
    logger.info(f"AutoPublicador Duo — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"Modo: {'LIVE (publica)' if live else 'DRY-RUN (sin publicar)'}")
    logger.info(f"Top noticias por corrida: {top}")
    logger.info("=" * 56)

    result = pipeline.run_pipeline(
        max_news=None,
        dry_run=not live,
        max_posts=top,
        safe_mode=safe,
        fixed_slot_publish=False,
    )

    logger.info("-" * 60)
    logger.info(f"  Ingestados:       {result.get('ingested', 0)}")
    logger.info(f"  Puntuados:        {result.get('scored', 0)}")
    logger.info(f"  Editorizados:     {result.get('editorialized', 0)}")
    logger.info(f"  Formateados:      {result.get('formatted', 0)}")
    logger.info(f"  Programados:      {result.get('scheduled', 0)}")
    logger.info(f"  Publicados:       {result.get('published', 0)}")
    if result.get("publish_blocked_reason"):
        logger.info(f"  Bloqueado:        {result['publish_blocked_reason']}")
    if result.get("next_scheduled"):
        logger.info(f"  Proxima public.:  {result['next_scheduled']}")
    logger.info("-" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description="AutoPublicador Duo pipeline runner")
    parser.add_argument("--live", action="store_true", help="Publicar en Instagram/Facebook")
    parser.add_argument("--top", type=int, default=10, help="Top N noticias a publicar (default: 10)")
    parser.add_argument("--safe", action="store_true", help="Modo seguro: limita publicaciones a 3")
    args = parser.parse_args()
    run(live=args.live, top=args.top, safe=args.safe)


if __name__ == "__main__":
    main()

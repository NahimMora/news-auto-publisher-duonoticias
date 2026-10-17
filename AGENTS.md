# AGENTS.md - AutoPublicador Duo

## Commands
- **Doctor**: `python -m cli.main doctor`
- **Run one safe cycle**: `python -m cli.main run-once --safe-mode`
- **Dry run**: `python -m cli.main dry-run`
- **24/7 loop**: `python -m cli.main run-24-7`
- **Live gate**: `python -m cli.main preflight` (exit 1 if live publishing cannot work)
- **Production service (FERNANDO)**: task `DuoNoticias-24x7` via `scripts/register_scheduled_task.ps1` -> `scripts/start_24x7_production.ps1` (see docs/OPERATIONS.md)
- **Queue**: `python -m cli.main queue --format table`
- **Import X URL**: `python -m cli.main import-x-url --url "..."`
- **Launch UI**: `python duo_ui.py` (tkinter wrapper over the new CLI)
- **Install deps**: `pip install -r requirements.txt` and `cd motion; npm install` (visual engine)
- **Visual engine**: `cd motion; npm run studio | panel | render:demos | typecheck` (see motion/README.md)

## Architecture
- **cli/main.py**: Single runtime entrypoint for SQLite 24/7 pipeline
- **jobs/pipeline.py**: Scraper → Scoring → Editorial → Formatter → Scheduler → Publisher → Analytics → Growth
- **extractors/**: Source registry, Paparazzi/TN/X extraction
- **utils/**: Core modules (OpenAI captioner, image/video processing, Instagram Graph API publisher, FAISS dedup)
- **motion/**: Duo Motion visual engine (Remotion templates, hooks, animation library, Next.js editorial panel, render worker). `formatter/motion_engine.py` is the pipeline adapter; the legacy Pillow/ffmpeg formatter (`utils/image_processor.py`, `video_app/`) is the automatic fallback
- **video_app/**: Legacy video overlay/subtitle engines (fallback only)
- **data/**: JSON outputs, history, FAISS index, media files
- External API: DUO_API.md documents the Next.js CMS REST API (admin/public endpoints)
- Legacy scripts are deprecated wrappers/reference only; do not add new runtime work outside `cli/main.py`.

## Code Style
- Python 3.10+, type hints encouraged, snake_case for functions/variables
- Use `pathlib.Path` for file paths, `httpx` for HTTP, `python-dotenv` for env
- Async via Celery/Redis optional (DUO_USE_CELERY=1)
- Logging: custom ScraperLogger or print with timestamps
- Config via `.env` (see `.env.example`); never commit secrets

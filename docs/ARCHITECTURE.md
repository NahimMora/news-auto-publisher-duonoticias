# AutoPublicador Duo - Architecture

## Runtime Source Of Truth

The runtime source of truth is `python -m cli.main`.

Legacy entrypoints are deprecated:
- `duo_runner.py` now delegates to `python -m cli.main run-once --safe-mode`.
- `utils/political_agent.py` and `ideologia_politica.md` are legacy/reference only and are not used by the new pipeline.
- `D:\WebApp_HolaSalta` is optional read-only reference through `WEBAPP_HOLASALTA_PATH`; production does not depend on subprocess calls to that project.

HolaSalta → DuoNoticias:
- Source: `extractors/holasalta/` is the `holasalta` entry in `config/sources.yaml` (disabled by default). News from `GET /api/news/` go through the full pipeline like any extractor; with `include_x_video_jobs: true`, X links from `GET /api/x-video/jobs` are imported through the regular X manual import (skipping tweets already in `content_items`).
- Delivery: `publishers/duo_web.py` is the `duo_web` publish platform (`ENABLE_DUO_WEB=true`). `DUO_WEB_MODE=ingest` posts the v1 contract in `docs/INGEST_CONTRACT.md`; `DUO_WEB_MODE=admin` posts to the existing `POST /api/admin/articles` (`DUO_API.md`) with a deterministic slug so resends collide (409 = already delivered). v1 sends text only, no cover image upload.
- Production guard: `utils/machine_guard.py`. `live_publish_enabled` is true only with `DUO_LIVE_PUBLISH_ENABLED=true` on `COMPUTERNAME=FERNANDO`.
- Deprecated standalone bridge: `python -m duonoticias_autopublicador.main` still works with its own outbox (`state/state.db`) and reuses the moved client/transport. Do not run it together with `duo_web` in `ingest` mode against the same web: both use different idempotency keys for the same item.

## Flow

`cli.main` -> `jobs.pipeline.DuoPipeline`:

1. `run_scraper`: direct source registry scans enabled sources from `config/sources.yaml`.
2. `run_scoring`: unified 0-100 scoring plus source-specific `source_scores`.
3. `run_editorial`: centralized JSON prompts from `editorial/prompting.py` and `config/editorial_policy.yaml`.
4. `run_formatter`: image/carousel/reel package creation through the Duo Motion engine (`formatter/motion_engine.py` -> `motion/`), with automatic per-piece fallback to the legacy Pillow/ffmpeg formatter. Dry-run uses no heavy media processing.
5. `run_scheduler`: slot assignment with anti-repetition.
6. `run_publisher`: blocked unless `DUO_LIVE_PUBLISH_ENABLED=true` and CLI `--live`.
7. `run_analytics`: Meta metrics where permissions allow.
8. `run_comment_engagement`: disabled by default; requires explicit config and may require extra Meta permissions.

## Duo Motion (visual engine)

`motion/` is a Node project (Remotion + React + TypeScript, Next.js panel). See `motion/README.md`.

- **Contract:** a piece is `content` (what the news says) + `presentation` (visual decisions), validated by Zod in `motion/src/schema/piece.ts`. `tests/test_motion_engine.py` validates Python-built pieces against that schema through `render/validate.ts`.
- **Python side:** `formatter/motion_engine.py` builds the piece from the editorialized row:
  - Gemini's `visual` block (`editorial/prompting.py` `VISUAL_RULES`) supplies the AV headline, category, location, urgency, key points and figures.
  - Figures pass only if the number appears literally in the note; key points must share most of their words with it.
- **Rendering:** a persistent `node render/cli.ts --stdio` worker per formatter stage (warm bundle and browser, no ports). `AssetFormatter.close()` ends it.
- **Templates:** `breaking`, `editorial` and `data` (reels), and `static` (posts, carousels, stories). Hooks: typographic, photo, data, chosen automatically by content.
- **Pipeline output:**
  - videos -> reel (editorial; breaking if urgent);
  - photos -> JPEG post or carousel;
  - urgent or data-rich photo news -> animated reel (`DUO_MOTION_PHOTO_REELS`).

## Publishing reliability

- **Idempotency:** before each Meta call the platform row is `in_flight`. At the start of the next publish run, `_reconcile_in_flight` searches the account for the exact caption:
  - found -> `published` with its id, never duplicated;
  - verified absent -> back to the queue;
  - unverifiable -> `ambiguous`, which needs `cli retry` after a manual check.
- **Rate limits** (`publishers/rate_limits.py`): Meta limit errors set a shared `blocked_until` per platform in `data/runtime/meta_rate_limits.json`. The piece goes back to `scheduled` without consuming retries.
- **Local-first policy:** `jobs/content_policy.py` accepts Salta news (Salta source or a Salta place in the headline) besides the national topics.

## Current Vertical Slice

Implemented first:
- Paparazzi direct WordPress API extractor.
- TN RSS/HTML extractor.
- X manual URL import with `X_MODE=manual`.
- SQLite traceability aliases.
- Safe/dry CLI.
- Meta publisher preview/mock guard.

## SQLite

Main DB: `SQLITE_PATH` or `DUO_DB_PATH`, default `data/duo_pipeline.sqlite3`.

Migrations are non-destructive:
- Backups are created before first runtime traceability migration in `storage/backups/`.
- `schema_migrations` records applied migrations.
- Existing tables are not dropped.
- Columns are only added if missing.

Primary tables:
- `content_items`
- `publications`
- `analytics_snapshots`
- `comment_actions`
- `daily_reports`
- `score_validation_runs`
- `schema_migrations`

`content_items` stores full traceability fields including raw payloads, score/editorial/formatted/schedule JSON, publish IDs, errors, retry count and analytics aliases.


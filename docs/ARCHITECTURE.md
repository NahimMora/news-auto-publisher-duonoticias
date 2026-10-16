# AutoPublicador Duo - Architecture

## Runtime Source Of Truth

The runtime source of truth is `python -m cli.main`.

Legacy entrypoints are deprecated:
- `duo_runner.py` now delegates to `python -m cli.main run-once --safe-mode`.
- `utils/political_agent.py` and `ideologia_politica.md` are legacy/reference only and are not used by the new pipeline.
- `D:\WebApp_HolaSalta` is optional read-only reference through `WEBAPP_HOLASALTA_PATH`; production does not depend on subprocess calls to that project.

## Flow

`cli.main` -> `jobs.pipeline.DuoPipeline`:

1. `run_scraper`: direct source registry scans enabled sources from `config/sources.yaml`.
2. `run_scoring`: unified 0-100 scoring plus source-specific `source_scores`.
3. `run_editorial`: centralized JSON prompts from `editorial/prompting.py` and `config/editorial_policy.yaml`.
4. `run_formatter`: image/carousel/reel package creation. Dry-run uses no heavy media processing.
5. `run_scheduler`: slot assignment with anti-repetition.
6. `run_publisher`: blocked unless `DUO_LIVE_PUBLISH_ENABLED=true` and CLI `--live`.
7. `run_analytics`: Meta metrics where permissions allow.
8. `run_comment_engagement`: disabled by default; requires explicit config and may require extra Meta permissions.

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


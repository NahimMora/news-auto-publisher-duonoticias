from __future__ import annotations

import json
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

from storage.models import (
    DedupDecision,
    EditorialPackage,
    ExtractedContent,
    FormattedPackage,
    PublicationRecord,
    ScheduleDecision,
    ViralityScore,
    safe_json,
    utc_now_iso,
)
from storage.settings import PipelineSettings, get_settings


class PipelineStore:
    TRACEABILITY_MIGRATION = "2026_05_02_traceability_runtime"

    def __init__(self, settings: PipelineSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self.path = self.settings.sqlite_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._backup_existing_database()
        self._init_schema()

    @contextmanager
    def connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self.connection() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS content_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content_key TEXT NOT NULL UNIQUE,
                    source TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_item_id TEXT,
                    canonical_url TEXT,
                    author TEXT,
                    source_handle TEXT,
                    title TEXT,
                    summary TEXT,
                    body_text TEXT,
                    language TEXT,
                    media_type TEXT,
                    created_at TEXT,
                    extracted_at TEXT,
                    visible_metrics_json TEXT,
                    tags_json TEXT,
                    ranking_signals_json TEXT,
                    raw_payload_json TEXT,
                    assets_json TEXT,
                    dedupe_status TEXT,
                    dedupe_reason TEXT,
                    matched_content_key TEXT,
                    perceptual_hash TEXT,
                    score_json TEXT,
                    score_total REAL,
                    score_novelty REAL,
                    score_engagement REAL,
                    score_debate REAL,
                    score_repostability REAL,
                    score_theme TEXT,
                    score_reason TEXT,
                    score_version TEXT,
                    editorial_json TEXT,
                    editorial_prompt TEXT,
                    editorial_input_json TEXT,
                    editorial_feedback TEXT,
                    editorial_hook_type TEXT,
                    editorial_tone TEXT,
                    editorial_signature TEXT,
                    formatted_json TEXT,
                    final_caption TEXT,
                    final_overlay TEXT,
                    assigned_post_type TEXT,
                    schedule_json TEXT,
                    assigned_slot TEXT,
                    assigned_time TEXT,
                    performance_bucket TEXT,
                    latest_performance_score REAL,
                    latest_engagement_rate REAL,
                    recycle_reusable INTEGER NOT NULL DEFAULT 0,
                    recycle_republishable INTEGER NOT NULL DEFAULT 0,
                    recycle_story_adaptable INTEGER NOT NULL DEFAULT 0,
                    recycle_reason TEXT,
                    pipeline_status TEXT DEFAULT 'extracted',
                    published_platforms_json TEXT DEFAULT '[]',
                    last_publication_id INTEGER,
                    last_post_id TEXT,
                    last_error TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version TEXT PRIMARY KEY,
                    applied_at TEXT NOT NULL,
                    notes TEXT
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT,
                    job_type TEXT NOT NULL,
                    content_key TEXT,
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS publications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content_key TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    status TEXT NOT NULL,
                    platform_media_id TEXT,
                    platform_post_id TEXT,
                    container_id TEXT,
                    permalink TEXT,
                    caption TEXT,
                    post_type TEXT,
                    scheduled_for TEXT,
                    published_at TEXT,
                    error_message TEXT,
                    mode TEXT DEFAULT 'live',
                    dry_run INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(content_key, platform)
                );
                CREATE TABLE IF NOT EXISTS analytics_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    publication_id INTEGER NOT NULL,
                    checkpoint_label TEXT,
                    checkpoint_order INTEGER,
                    due_at TEXT,
                    collected_at TEXT NOT NULL,
                    publication_age_minutes INTEGER,
                    views INTEGER,
                    likes INTEGER,
                    comments INTEGER,
                    shares INTEGER,
                    engagement_rate REAL,
                    performance_score REAL,
                    performance_bucket TEXT,
                    metrics_json TEXT NOT NULL,
                    FOREIGN KEY(publication_id) REFERENCES publications(id)
                );
                CREATE TABLE IF NOT EXISTS comment_actions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    publication_id INTEGER NOT NULL,
                    platform TEXT NOT NULL,
                    comment_id TEXT NOT NULL,
                    author_username TEXT,
                    comment_text TEXT,
                    liked INTEGER NOT NULL DEFAULT 0,
                    replied INTEGER NOT NULL DEFAULT 0,
                    reply_id TEXT,
                    payload_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(platform, comment_id),
                    FOREIGN KEY(publication_id) REFERENCES publications(id)
                );
                CREATE TABLE IF NOT EXISTS daily_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    report_date TEXT NOT NULL UNIQUE,
                    report_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS score_validation_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    checkpoint_label TEXT NOT NULL,
                    lookback_days INTEGER NOT NULL,
                    correlation REAL,
                    accuracy_score REAL,
                    mean_absolute_deviation REAL,
                    mean_signed_deviation REAL,
                    overestimated_count INTEGER NOT NULL DEFAULT 0,
                    underestimated_count INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
        self._migrate_schema()
        self._backfill_materialized_fields()
        self._record_migration(self.TRACEABILITY_MIGRATION, "runtime traceability aliases and safe migrations")

    def _backup_existing_database(self) -> None:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return
        if self._has_migration(self.TRACEABILITY_MIGRATION):
            return
        backup_dir = self.settings.backup_dir
        try:
            if not self.path.resolve().is_relative_to(self.settings.base_dir.resolve()):
                backup_dir = self.path.parent / "backups"
        except Exception:
            backup_dir = self.path.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"{self.path.stem}_{stamp}{self.path.suffix or '.sqlite3'}"
        shutil.copy2(self.path, backup_path)

    def _has_migration(self, version: str) -> bool:
        if not self.path.exists():
            return False
        conn: sqlite3.Connection | None = None
        try:
            conn = sqlite3.connect(self.path)
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
            ).fetchone()
            if not row:
                return False
            applied = conn.execute(
                "SELECT 1 FROM schema_migrations WHERE version = ?",
                (version,),
            ).fetchone()
            return bool(applied)
        except sqlite3.Error:
            return False
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def _record_migration(self, version: str, notes: str = "") -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO schema_migrations (version, applied_at, notes)
                VALUES (?, ?, ?)
                ON CONFLICT(version) DO NOTHING
                """,
                (version, utc_now_iso(), notes),
            )

    def _migrate_schema(self) -> None:
        content_columns = {
            "score_total": "REAL",
            "score_novelty": "REAL",
            "score_engagement": "REAL",
            "score_debate": "REAL",
            "score_repostability": "REAL",
            "score_theme": "TEXT",
            "score_reason": "TEXT",
            "score_version": "TEXT",
            "editorial_prompt": "TEXT",
            "editorial_input_json": "TEXT",
            "editorial_feedback": "TEXT",
            "editorial_hook_type": "TEXT",
            "editorial_tone": "TEXT",
            "editorial_signature": "TEXT",
            "final_caption": "TEXT",
            "final_overlay": "TEXT",
            "assigned_post_type": "TEXT",
            "assigned_slot": "TEXT",
            "assigned_time": "TEXT",
            "performance_bucket": "TEXT",
            "latest_performance_score": "REAL",
            "latest_engagement_rate": "REAL",
            "recycle_reusable": "INTEGER NOT NULL DEFAULT 0",
            "recycle_republishable": "INTEGER NOT NULL DEFAULT 0",
            "recycle_story_adaptable": "INTEGER NOT NULL DEFAULT 0",
            "recycle_reason": "TEXT",
            "last_publication_id": "INTEGER",
            "last_post_id": "TEXT",
            "source_url": "TEXT",
            "detected_at": "TEXT",
            "scraped_at": "TEXT",
            "raw_title": "TEXT",
            "raw_excerpt": "TEXT",
            "raw_text": "TEXT",
            "raw_images": "TEXT",
            "raw_videos": "TEXT",
            "raw_metrics": "TEXT",
            "normalized_payload_json": "TEXT",
            "safety_json": "TEXT",
            "duplication_json": "TEXT",
            "editorial_output_json": "TEXT",
            "formatted_output_json": "TEXT",
            "media_output_paths": "TEXT",
            "scheduled_at": "TEXT",
            "publish_status": "TEXT",
            "instagram_publication_id": "TEXT",
            "facebook_publication_id": "TEXT",
            "errors": "TEXT",
            "retry_count": "INTEGER NOT NULL DEFAULT 0",
            "analytics_1h": "TEXT",
            "analytics_6h": "TEXT",
            "analytics_24h": "TEXT",
            "growth_feedback_json": "TEXT",
        }
        publication_columns = {
            "platform_post_id": "TEXT",
            "post_type": "TEXT",
            "mode": "TEXT DEFAULT 'live'",
            "dry_run": "INTEGER NOT NULL DEFAULT 0",
        }
        analytics_columns = {
            "checkpoint_label": "TEXT",
            "checkpoint_order": "INTEGER",
            "due_at": "TEXT",
            "publication_age_minutes": "INTEGER",
            "views": "INTEGER",
            "likes": "INTEGER",
            "comments": "INTEGER",
            "shares": "INTEGER",
            "engagement_rate": "REAL",
            "performance_score": "REAL",
            "performance_bucket": "TEXT",
        }
        for name, definition in content_columns.items():
            self._ensure_column("content_items", name, definition)
        for name, definition in publication_columns.items():
            self._ensure_column("publications", name, definition)
        for name, definition in analytics_columns.items():
            self._ensure_column("analytics_snapshots", name, definition)
        self._ensure_table(
            "daily_reports",
            """
            CREATE TABLE IF NOT EXISTS daily_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_date TEXT NOT NULL UNIQUE,
                report_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
        )
        self._ensure_table(
            "score_validation_runs",
            """
            CREATE TABLE IF NOT EXISTS score_validation_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                checkpoint_label TEXT NOT NULL,
                lookback_days INTEGER NOT NULL,
                correlation REAL,
                accuracy_score REAL,
                mean_absolute_deviation REAL,
                mean_signed_deviation REAL,
                overestimated_count INTEGER NOT NULL DEFAULT 0,
                underestimated_count INTEGER NOT NULL DEFAULT 0,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """,
        )
        self._ensure_index(
            """
            CREATE INDEX IF NOT EXISTS idx_content_pipeline_status
            ON content_items(pipeline_status, extracted_at DESC)
            """
        )
        self._ensure_index(
            """
            CREATE INDEX IF NOT EXISTS idx_content_source_handle
            ON content_items(source, source_handle, extracted_at DESC)
            """
        )
        self._ensure_index(
            """
            CREATE INDEX IF NOT EXISTS idx_publications_status
            ON publications(status, published_at DESC)
            """
        )
        self._ensure_index(
            """
            CREATE INDEX IF NOT EXISTS idx_analytics_publication
            ON analytics_snapshots(publication_id, collected_at DESC)
            """
        )
        self._ensure_index(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_analytics_publication_checkpoint
            ON analytics_snapshots(publication_id, checkpoint_label)
            """
        )

    def _backfill_materialized_fields(self) -> None:
        with self.connection() as conn:
            conn.executescript(
                """
                UPDATE content_items
                SET score_total = COALESCE(score_total, json_extract(score_json, '$.total')),
                    score_novelty = COALESCE(score_novelty, json_extract(score_json, '$.novelty')),
                    score_engagement = COALESCE(score_engagement, json_extract(score_json, '$.engagement_potential')),
                    score_debate = COALESCE(score_debate, json_extract(score_json, '$.debate_potential')),
                    score_repostability = COALESCE(score_repostability, json_extract(score_json, '$.repostability')),
                    score_theme = COALESCE(score_theme, json_extract(score_json, '$.theme')),
                    score_reason = COALESCE(score_reason, json_extract(score_json, '$.reason')),
                    score_version = COALESCE(score_version, json_extract(score_json, '$.score_version')),
                    final_caption = COALESCE(
                        final_caption,
                        json_extract(formatted_json, '$.caption'),
                        json_extract(editorial_json, '$.caption')
                    ),
                    final_overlay = COALESCE(final_overlay, json_extract(editorial_json, '$.overlay')),
                    assigned_post_type = COALESCE(
                        assigned_post_type,
                        json_extract(formatted_json, '$.post_type'),
                        media_type
                    ),
                    assigned_slot = COALESCE(assigned_slot, json_extract(schedule_json, '$.slot_label')),
                    assigned_time = COALESCE(assigned_time, json_extract(schedule_json, '$.scheduled_for')),
                    editorial_hook_type = COALESCE(editorial_hook_type, json_extract(editorial_json, '$.hook_type')),
                    editorial_tone = COALESCE(editorial_tone, json_extract(editorial_json, '$.tone')),
                    editorial_signature = COALESCE(editorial_signature, json_extract(editorial_json, '$.pattern_signature'));

                UPDATE publications
                SET platform_post_id = COALESCE(platform_post_id, platform_media_id),
                    post_type = COALESCE(post_type, (
                        SELECT assigned_post_type
                        FROM content_items
                        WHERE content_items.content_key = publications.content_key
                    ));
                """
            )

    def _ensure_table(self, table_name: str, ddl: str) -> None:
        if table_name in self._existing_tables():
            return
        with self.connection() as conn:
            conn.execute(ddl)

    def _ensure_column(self, table_name: str, column_name: str, definition: str) -> None:
        if column_name in self._existing_columns(table_name):
            return
        with self.connection() as conn:
            try:
                conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")
            except sqlite3.OperationalError as exc:
                if "duplicate column name" in str(exc).lower():
                    return
                raise

    def _ensure_index(self, ddl: str) -> None:
        with self.connection() as conn:
            conn.execute(ddl)

    def _existing_tables(self) -> set[str]:
        with self.connection() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        return {str(row[0]) for row in rows}

    def _existing_columns(self, table_name: str) -> set[str]:
        with self.connection() as conn:
            rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return {str(row["name"]) for row in rows}

    def upsert_content(self, content: ExtractedContent) -> str:
        now = utc_now_iso()
        content_key = content.ensure_content_key()
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO content_items (
                    content_key, source, source_type, source_item_id, canonical_url, author,
                    source_handle, title, summary, body_text, language, media_type, created_at,
                    extracted_at, visible_metrics_json, tags_json, ranking_signals_json,
                    raw_payload_json, assets_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(content_key) DO UPDATE SET
                    source=excluded.source,
                    source_type=excluded.source_type,
                    source_item_id=excluded.source_item_id,
                    canonical_url=excluded.canonical_url,
                    author=excluded.author,
                    source_handle=excluded.source_handle,
                    title=excluded.title,
                    summary=excluded.summary,
                    body_text=excluded.body_text,
                    language=excluded.language,
                    media_type=excluded.media_type,
                    created_at=excluded.created_at,
                    extracted_at=excluded.extracted_at,
                    visible_metrics_json=excluded.visible_metrics_json,
                    tags_json=excluded.tags_json,
                    ranking_signals_json=excluded.ranking_signals_json,
                    raw_payload_json=excluded.raw_payload_json,
                    assets_json=excluded.assets_json,
                    updated_at=excluded.updated_at
                """,
                (
                    content_key,
                    content.source,
                    content.source_type,
                    content.source_item_id,
                    content.canonical_url,
                    content.author,
                    content.source_handle,
                    content.title,
                    content.summary,
                    content.body_text,
                    content.language,
                    content.media_type,
                    content.created_at,
                    content.extracted_at,
                    safe_json(content.visible_metrics),
                    safe_json(content.tags),
                    safe_json(content.ranking_signals),
                    safe_json(content.raw_payload),
                    safe_json([asset.as_dict() for asset in content.assets]),
                    now,
                ),
            )
            raw_images = [asset.as_dict() for asset in content.assets if asset.kind == "image"]
            raw_videos = [asset.as_dict() for asset in content.assets if asset.kind == "video"]
            conn.execute(
                """
                UPDATE content_items
                SET source_url = ?,
                    detected_at = COALESCE(detected_at, ?),
                    scraped_at = ?,
                    raw_title = ?,
                    raw_excerpt = ?,
                    raw_text = ?,
                    raw_images = ?,
                    raw_videos = ?,
                    raw_metrics = ?,
                    normalized_payload_json = ?
                WHERE content_key = ?
                """,
                (
                    content.canonical_url,
                    content.extracted_at,
                    content.extracted_at,
                    content.title,
                    content.summary,
                    content.body_text,
                    safe_json(raw_images),
                    safe_json(raw_videos),
                    safe_json(content.visible_metrics),
                    safe_json(content.as_dict()),
                    content_key,
                ),
            )
        return content_key

    def find_content(self, content_key: str) -> Optional[Dict[str, Any]]:
        with self.connection() as conn:
            row = conn.execute(
                "SELECT * FROM content_items WHERE content_key = ?",
                (content_key,),
            ).fetchone()
        return dict(row) if row else None

    def has_source_item(self, source: str, source_item_id: str) -> bool:
        if not source_item_id:
            return False
        with self.connection() as conn:
            row = conn.execute(
                "SELECT 1 FROM content_items WHERE source = ? AND source_item_id = ? LIMIT 1",
                (source, source_item_id),
            ).fetchone()
        return row is not None

    def recent_hash_candidates(self, source_type: str, limit: int = 200) -> List[Dict[str, Any]]:
        return self._rows(
            """
            SELECT content_key, title, perceptual_hash, dedupe_status, created_at, extracted_at
            FROM content_items
            WHERE source_type = ? AND perceptual_hash IS NOT NULL AND perceptual_hash != ''
            ORDER BY extracted_at DESC
            LIMIT ?
            """,
            (source_type, limit),
        )

    def save_dedup(self, content_key: str, decision: DedupDecision) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE content_items
                SET dedupe_status = ?,
                    dedupe_reason = ?,
                    matched_content_key = ?,
                    perceptual_hash = COALESCE(?, perceptual_hash),
                    duplication_json = ?,
                    pipeline_status = CASE
                        WHEN ? = 'discarded' THEN 'discarded'
                        ELSE pipeline_status
                    END,
                    updated_at = ?
                WHERE content_key = ?
                """,
                (
                    decision.status,
                    decision.reason,
                    decision.matched_content_key,
                    decision.perceptual_hash,
                    safe_json(decision.__dict__),
                    decision.status,
                    utc_now_iso(),
                    content_key,
                ),
            )

    def list_pending_scoring(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self._rows(
            """
            SELECT * FROM content_items
            WHERE COALESCE(dedupe_status, 'accepted') != 'discarded'
              AND pipeline_status = 'extracted'
              AND score_json IS NULL
            ORDER BY extracted_at DESC
            LIMIT ?
            """,
            (limit,),
        )

    def save_score(self, content_key: str, score: ViralityScore) -> None:
        status = "scored" if score.publish else "filtered"
        payload = score.as_dict()
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE content_items
                SET score_json = ?,
                    score_total = ?,
                    score_novelty = ?,
                    score_engagement = ?,
                    score_debate = ?,
                    score_repostability = ?,
                    score_theme = ?,
                    score_reason = ?,
                    score_version = ?,
                    safety_json = ?,
                    publish_status = CASE WHEN ? = 'filtered' THEN 'filtered' ELSE publish_status END,
                    pipeline_status = ?,
                    updated_at = ?
                WHERE content_key = ?
                """,
                (
                    safe_json(payload),
                    score.total,
                    score.novelty,
                    score.engagement_potential,
                    score.debate_potential,
                    score.repostability,
                    score.theme,
                    score.reason,
                    score.score_version,
                    safe_json({
                        "publish": score.publish,
                        "risk_penalty": max(0.0, 100.0 - float(score.total)),
                        "reason": score.reason,
                    }),
                    status,
                    status,
                    utc_now_iso(),
                    content_key,
                ),
            )

    def list_pending_editorial(self, limit: int = 25) -> List[Dict[str, Any]]:
        return self._rows(
            """
            SELECT * FROM content_items
            WHERE editorial_json IS NULL
              AND score_json IS NOT NULL
              AND pipeline_status = 'scored'
            ORDER BY COALESCE(score_total, json_extract(score_json, '$.total')) DESC, extracted_at DESC
            LIMIT ?
            """,
            (limit,),
        )

    def save_editorial(self, content_key: str, editorial: EditorialPackage) -> None:
        status = "editorialized" if editorial.publish else "filtered"
        payload = editorial.as_dict()
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE content_items
                SET editorial_json = ?,
                    editorial_output_json = ?,
                    editorial_prompt = ?,
                    editorial_input_json = ?,
                    editorial_feedback = ?,
                    growth_feedback_json = ?,
                    editorial_hook_type = ?,
                    editorial_tone = ?,
                    editorial_signature = ?,
                    final_caption = ?,
                    final_overlay = ?,
                    pipeline_status = ?,
                    updated_at = ?
                WHERE content_key = ?
                """,
                (
                    safe_json(payload),
                    safe_json(payload),
                    editorial.prompt_used,
                    safe_json(editorial.input_payload),
                    editorial.feedback_summary,
                    safe_json({"summary": editorial.feedback_summary, "anti_fatigue_notes": editorial.anti_fatigue_notes}),
                    editorial.hook_type,
                    editorial.tone,
                    editorial.pattern_signature,
                    editorial.caption,
                    editorial.overlay,
                    status,
                    utc_now_iso(),
                    content_key,
                ),
            )

    def list_pending_formatter(self, limit: int = 20) -> List[Dict[str, Any]]:
        return self._rows(
            """
            SELECT * FROM content_items
            WHERE formatted_json IS NULL
              AND editorial_json IS NOT NULL
              AND pipeline_status = 'editorialized'
            ORDER BY COALESCE(score_total, json_extract(score_json, '$.total')) DESC, extracted_at DESC
            LIMIT ?
            """,
            (limit,),
        )

    def save_formatted(self, content_key: str, formatted: FormattedPackage) -> None:
        payload = formatted.as_dict()
        media_paths = [asset.path for asset in formatted.assets if asset.path]
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE content_items
                SET formatted_json = ?,
                    formatted_output_json = ?,
                    media_output_paths = ?,
                    final_caption = ?,
                    assigned_post_type = ?,
                    pipeline_status = 'formatted',
                    updated_at = ?
                WHERE content_key = ?
                """,
                (
                    safe_json(payload),
                    safe_json(payload),
                    safe_json(media_paths),
                    formatted.caption,
                    formatted.post_type,
                    utc_now_iso(),
                    content_key,
                ),
            )

    def list_pending_scheduling(self, limit: int = 20) -> List[Dict[str, Any]]:
        return self._rows(
            """
            SELECT * FROM content_items
            WHERE schedule_json IS NULL
              AND formatted_json IS NOT NULL
              AND pipeline_status = 'formatted'
            ORDER BY COALESCE(score_total, json_extract(score_json, '$.total')) DESC, extracted_at DESC
            LIMIT ?
            """,
            (limit,),
        )

    def recent_schedule_context(self, limit: int = 6) -> List[Dict[str, Any]]:
        return self._rows(
            """
            SELECT content_key, title, source, source_handle, media_type, assigned_post_type,
                   score_theme, editorial_signature, editorial_tone, final_overlay,
                   assigned_slot, assigned_time, pipeline_status, updated_at
            FROM content_items
            WHERE schedule_json IS NOT NULL OR pipeline_status = 'published'
            ORDER BY COALESCE(assigned_time, updated_at) DESC
            LIMIT ?
            """,
            (limit,),
        )

    def future_schedule_context(self, now_iso: str, limit: int = 500) -> List[Dict[str, Any]]:
        return self._rows(
            """
            SELECT content_key, title, source, source_handle, media_type, assigned_post_type,
                   score_theme, assigned_slot, assigned_time, schedule_json, pipeline_status
            FROM content_items
            WHERE schedule_json IS NOT NULL
              AND formatted_json IS NOT NULL
              AND pipeline_status IN ('scheduled', 'publish_failed')
              AND json_extract(schedule_json, '$.scheduled_for') >= ?
            ORDER BY json_extract(schedule_json, '$.scheduled_for') ASC
            LIMIT ?
            """,
            (now_iso, limit),
        )

    def save_schedule(self, content_key: str, schedule: ScheduleDecision) -> None:
        payload = schedule.as_dict()
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE content_items
                SET schedule_json = ?,
                    assigned_slot = ?,
                    assigned_time = ?,
                    scheduled_at = ?,
                    pipeline_status = 'scheduled',
                    updated_at = ?
                WHERE content_key = ?
                """,
                (
                    safe_json(payload),
                    schedule.slot_label,
                    schedule.scheduled_for,
                    schedule.scheduled_for,
                    utc_now_iso(),
                    content_key,
                ),
            )

    def list_due_for_publish(
        self,
        now_iso: str,
        limit: int = 10,
        slot_label: str | None = None,
        min_extracted_at: str | None = None,
        content_type: str | None = None,
        force_due: bool = False,
    ) -> List[Dict[str, Any]]:
        # content_type: "reels" → only reel, "news" → image/carousel, None → all
        if content_type == "reels":
            type_clause = "AND assigned_post_type = 'reel'"
        elif content_type == "news":
            type_clause = "AND COALESCE(assigned_post_type,'image') IN ('image','carousel')"
        else:
            type_clause = ""
        time_clause = "" if force_due else "AND json_extract(schedule_json, '$.scheduled_for') <= ?"
        params = () if force_due else (now_iso,)
        status_clause = "pipeline_status IN ('scheduled','publish_failed')" if force_due else "pipeline_status = 'scheduled'"
        return self._rows(
            f"""
            SELECT * FROM content_items
            WHERE schedule_json IS NOT NULL
              AND formatted_json IS NOT NULL
              AND {status_clause}
              {time_clause}
              AND (? IS NULL OR assigned_slot = ?)
              AND (? IS NULL OR COALESCE(extracted_at, '') >= ?)
              {type_clause}
            ORDER BY json_extract(schedule_json, '$.scheduled_for') ASC
            LIMIT ?
            """,
            (*params, slot_label, slot_label, min_extracted_at, min_extracted_at, limit),
        )

    def list_publish_queue_candidates(self, limit: int = 300) -> List[Dict[str, Any]]:
        return self._rows(
            """
            SELECT * FROM content_items
            WHERE formatted_json IS NOT NULL
              AND pipeline_status IN ('formatted', 'scheduled', 'publish_failed')
            ORDER BY COALESCE(assigned_time, updated_at) ASC
            LIMIT ?
            """,
            (limit,),
        )

    def skip_stale_publish_queue(self, min_extracted_at: str) -> int:
        with self.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE content_items
                SET pipeline_status = 'skipped',
                    publish_status = 'skipped',
                    last_error = ?,
                    errors = ?,
                    updated_at = ?
                WHERE pipeline_status IN ('formatted', 'scheduled', 'publish_failed')
                  AND COALESCE(extracted_at, '') < ?
                  AND content_key NOT IN (
                      SELECT content_key
                      FROM publications
                      WHERE status = 'published'
                  )
                """,
                (
                    "stale_content_not_published",
                    "stale_content_not_published",
                    utc_now_iso(),
                    min_extracted_at,
                ),
            )
            return int(cursor.rowcount or 0)

    def published_fingerprints(self, limit: int = 500) -> List[Dict[str, Any]]:
        return self._rows(
            """
            SELECT DISTINCT c.content_key, c.source, c.source_item_id, c.canonical_url, c.title,
                   c.created_at, c.extracted_at, p.published_at
            FROM content_items c
            JOIN publications p ON p.content_key = c.content_key
            WHERE p.status = 'published'
            ORDER BY p.published_at DESC
            LIMIT ?
            """,
            (limit,),
        )

    def list_upcoming_scheduled(self, limit: int = 10) -> List[Dict[str, Any]]:
        return self._rows(
            """
            SELECT content_key, title, source, source_handle, score_total,
                   assigned_slot, assigned_time, assigned_post_type
            FROM content_items
            WHERE schedule_json IS NOT NULL
              AND formatted_json IS NOT NULL
              AND pipeline_status = 'scheduled'
            ORDER BY json_extract(schedule_json, '$.scheduled_for') ASC
            LIMIT ?
            """,
            (limit,),
        )

    def save_publication(self, content_key: str, publication: PublicationRecord) -> int:
        now = utc_now_iso()
        post_id = publication.platform_post_id or publication.platform_media_id
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO publications (
                    content_key, platform, status, platform_media_id, platform_post_id, container_id,
                    permalink, caption, post_type, scheduled_for, published_at, error_message,
                    mode, dry_run, payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(content_key, platform) DO UPDATE SET
                    status=excluded.status,
                    platform_media_id=excluded.platform_media_id,
                    platform_post_id=excluded.platform_post_id,
                    container_id=excluded.container_id,
                    permalink=excluded.permalink,
                    caption=excluded.caption,
                    post_type=excluded.post_type,
                    scheduled_for=excluded.scheduled_for,
                    published_at=excluded.published_at,
                    error_message=excluded.error_message,
                    mode=excluded.mode,
                    dry_run=excluded.dry_run,
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
                """,
                (
                    content_key,
                    publication.platform,
                    publication.status,
                    publication.platform_media_id,
                    post_id,
                    publication.container_id,
                    publication.permalink,
                    publication.caption,
                    publication.post_type,
                    publication.scheduled_for,
                    publication.published_at,
                    publication.error_message,
                    publication.mode,
                    int(publication.dry_run),
                    safe_json(publication.payload),
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT id FROM publications WHERE content_key = ? AND platform = ?",
                (content_key, publication.platform),
            ).fetchone()
            platform_rows = conn.execute(
                "SELECT platform FROM publications WHERE content_key = ? AND status = 'published'",
                (content_key,),
            ).fetchall()
            platforms = [value["platform"] for value in platform_rows]
            # Interim state only — refresh_content_publish_state is sole authority for final "published".
            pipeline_status = "publishing"
            conn.execute(
                """
                UPDATE content_items
                SET pipeline_status = ?,
                    publish_status = ?,
                    published_platforms_json = ?,
                    last_publication_id = ?,
                    last_post_id = ?,
                    instagram_publication_id = CASE
                        WHEN ? IN ('instagram', 'instagram_story') THEN ?
                        ELSE instagram_publication_id
                    END,
                    facebook_publication_id = CASE
                        WHEN ? = 'facebook' THEN ?
                        ELSE facebook_publication_id
                    END,
                    last_error = ?,
                    errors = ?,
                    updated_at = ?
                WHERE content_key = ?
                """,
                (
                    pipeline_status,
                    publication.status,
                    safe_json(platforms),
                    int(row["id"]) if row else None,
                    post_id,
                    publication.platform,
                    post_id,
                    publication.platform,
                    post_id,
                    publication.error_message,
                    publication.error_message,
                    now,
                    content_key,
                ),
            )
            return int(row["id"]) if row else 0

    def publication_statuses(self, content_key: str) -> Dict[str, Dict[str, Any]]:
        rows = self._rows(
            """
            SELECT platform, status, platform_media_id, platform_post_id, permalink,
                   published_at, error_message
            FROM publications
            WHERE content_key = ?
            """,
            (content_key,),
        )
        return {str(row.get("platform") or ""): row for row in rows if row.get("platform")}

    def refresh_content_publish_state(self, content_key: str, required_platforms: Sequence[str]) -> None:
        required = [platform for platform in required_platforms if platform]
        statuses = self.publication_statuses(content_key)
        published_platforms = sorted(
            platform
            for platform, row in statuses.items()
            if str(row.get("status") or "") == "published"
        )
        missing_or_failed = [
            platform
            for platform in required
            if str(statuses.get(platform, {}).get("status") or "") != "published"
        ]
        pipeline_status = "published" if required and not missing_or_failed else "publish_failed"
        error_message = "" if pipeline_status == "published" else f"pending_or_failed_platforms={','.join(missing_or_failed or required)}"
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE content_items
                SET pipeline_status = ?,
                    publish_status = ?,
                    published_platforms_json = ?,
                    last_error = ?,
                    errors = ?,
                    updated_at = ?
                WHERE content_key = ?
                """,
                (
                    pipeline_status,
                    pipeline_status,
                    safe_json(published_platforms),
                    error_message,
                    error_message,
                    utc_now_iso(),
                    content_key,
                ),
            )

    def update_publication_media_id(self, publication_id: int, platform_media_id: str) -> None:
        if not publication_id or not platform_media_id:
            return
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE publications
                SET platform_media_id = ?,
                    platform_post_id = COALESCE(NULLIF(platform_post_id, ''), ?),
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    platform_media_id,
                    platform_media_id,
                    utc_now_iso(),
                    publication_id,
                ),
            )

    def recent_publications_without_snapshot(self, min_age_minutes: int, limit: int = 20) -> List[Dict[str, Any]]:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(minutes=min_age_minutes)
        ).replace(microsecond=0).isoformat()
        return self._rows(
            """
            SELECT p.*, c.title, c.score_json, c.editorial_json, c.schedule_json, c.source, c.media_type
            FROM publications p
            JOIN content_items c ON c.content_key = p.content_key
            LEFT JOIN analytics_snapshots a ON a.publication_id = p.id
            WHERE p.status = 'published'
              AND p.published_at IS NOT NULL
              AND p.published_at <= ?
              AND a.id IS NULL
            ORDER BY p.published_at DESC
            LIMIT ?
            """,
            (cutoff, limit),
        )

    def list_due_analytics_checkpoints(
        self,
        now_dt: datetime,
        checkpoint_hours: Sequence[int],
        lookback_hours: int,
    ) -> List[Dict[str, Any]]:
        cutoff = (
            now_dt - timedelta(hours=lookback_hours)
        ).replace(microsecond=0).isoformat()
        rows = self._rows(
            """
            SELECT p.id AS publication_id, p.content_key, p.platform, p.platform_media_id, p.platform_post_id,
                   p.permalink, p.published_at, p.post_type, c.id AS content_id, c.source, c.source_handle,
                   c.title, c.score_total, c.score_json, c.editorial_prompt, c.editorial_input_json,
                   c.editorial_json, c.final_caption, c.final_overlay, c.assigned_slot, c.assigned_time
            FROM publications p
            JOIN content_items c ON c.content_key = p.content_key
            WHERE p.status = 'published'
              AND p.published_at IS NOT NULL
              AND p.published_at >= ?
            ORDER BY p.published_at DESC
            """,
            (cutoff,),
        )
        if not rows:
            return []
        publication_ids = [int(row["publication_id"]) for row in rows]
        placeholders = ",".join("?" for _ in publication_ids)
        snapshot_rows = self._rows(
            f"""
            SELECT publication_id, checkpoint_label
            FROM analytics_snapshots
            WHERE publication_id IN ({placeholders})
            """,
            tuple(publication_ids),
        )
        existing: Dict[int, set[str]] = {}
        for item in snapshot_rows:
            publication_id = int(item["publication_id"])
            label = str(item.get("checkpoint_label") or "")
            if not label:
                continue
            existing.setdefault(publication_id, set()).add(label)
        checkpoint_defs = self.checkpoint_definitions(checkpoint_hours)
        due_rows: List[Dict[str, Any]] = []
        for row in rows:
            published_at = self._parse_dt(row.get("published_at"))
            if published_at is None:
                continue
            publication_id = int(row["publication_id"])
            labels = existing.get(publication_id, set())
            age_minutes = int((now_dt - published_at).total_seconds() // 60)
            for checkpoint in checkpoint_defs:
                if checkpoint["label"] in labels:
                    continue
                due_at = published_at + timedelta(hours=int(checkpoint["hours"]))
                if due_at > now_dt:
                    continue
                item = dict(row)
                item.update(
                    {
                        "checkpoint_label": checkpoint["label"],
                        "checkpoint_order": checkpoint["order"],
                        "checkpoint_hours": checkpoint["hours"],
                        "due_at": due_at.replace(microsecond=0).isoformat(),
                        "publication_age_minutes": age_minutes,
                    }
                )
                due_rows.append(item)
        due_rows.sort(
            key=lambda item: (
                str(item.get("due_at") or ""),
                int(item.get("checkpoint_order") or 0),
            )
        )
        return due_rows

    def save_analytics_snapshot(
        self,
        publication_id: int,
        metrics: Dict[str, Any],
        *,
        checkpoint_label: str = "",
        checkpoint_order: int = 0,
        due_at: str = "",
        publication_age_minutes: int = 0,
        views: int = 0,
        likes: int = 0,
        comments: int = 0,
        shares: int = 0,
        engagement_rate: float = 0.0,
        performance_score: float = 0.0,
        performance_bucket: str = "",
    ) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO analytics_snapshots (
                    publication_id, checkpoint_label, checkpoint_order, due_at, collected_at,
                    publication_age_minutes, views, likes, comments, shares, engagement_rate,
                    performance_score, performance_bucket, metrics_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(publication_id, checkpoint_label) DO UPDATE SET
                    checkpoint_order=excluded.checkpoint_order,
                    due_at=excluded.due_at,
                    collected_at=excluded.collected_at,
                    publication_age_minutes=excluded.publication_age_minutes,
                    views=excluded.views,
                    likes=excluded.likes,
                    comments=excluded.comments,
                    shares=excluded.shares,
                    engagement_rate=excluded.engagement_rate,
                    performance_score=excluded.performance_score,
                    performance_bucket=excluded.performance_bucket,
                    metrics_json=excluded.metrics_json
                """,
                (
                    publication_id,
                    checkpoint_label or None,
                    checkpoint_order,
                    due_at,
                    utc_now_iso(),
                    publication_age_minutes,
                    views,
                    likes,
                    comments,
                    shares,
                    engagement_rate,
                    performance_score,
                    performance_bucket,
                    safe_json(metrics),
                ),
            )
            alias_column = {1: "analytics_1h", 2: "analytics_6h", 3: "analytics_24h"}.get(int(checkpoint_order or 0))
            if alias_column:
                conn.execute(
                    f"""
                    UPDATE content_items
                    SET {alias_column} = ?,
                        updated_at = ?
                    WHERE content_key = (
                        SELECT content_key FROM publications WHERE id = ?
                    )
                    """,
                    (safe_json(metrics), utc_now_iso(), publication_id),
                )

    def analytics_scores(self, checkpoint_label: str, lookback_days: int = 90) -> List[Dict[str, Any]]:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=lookback_days)
        ).replace(microsecond=0).isoformat()
        return self._rows(
            """
            SELECT id, publication_id, performance_score
            FROM analytics_snapshots
            WHERE checkpoint_label = ?
              AND collected_at >= ?
              AND performance_score IS NOT NULL
              AND COALESCE(json_extract(metrics_json, '$.meta.analytics_status'), '') != 'unavailable'
            ORDER BY performance_score ASC, collected_at ASC
            """,
            (checkpoint_label, cutoff),
        )

    def update_analytics_bucket(self, snapshot_id: int, bucket: str) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE analytics_snapshots
                SET performance_bucket = ?
                WHERE id = ?
                """,
                (bucket, snapshot_id),
            )

    def refresh_content_performance(self, publication_id: int) -> None:
        row = self._rows(
            """
            SELECT p.id AS publication_id, p.content_key, a.performance_score, a.performance_bucket,
                   a.engagement_rate
            FROM publications p
            JOIN analytics_snapshots a ON a.publication_id = p.id
            WHERE p.id = ?
              AND COALESCE(json_extract(a.metrics_json, '$.meta.analytics_status'), '') != 'unavailable'
            ORDER BY COALESCE(a.checkpoint_order, 0) DESC, a.collected_at DESC
            LIMIT 1
            """,
            (publication_id,),
        )
        if not row:
            return
        item = row[0]
        bucket = str(item.get("performance_bucket") or "")
        performance_score = float(item.get("performance_score") or 0.0)
        engagement_rate = float(item.get("engagement_rate") or 0.0)
        recyclable = bucket in {"elite", "alto"}
        republishable = bucket == "elite"
        adaptable_story = bucket in {"elite", "alto"}
        reason = (
            f"bucket={bucket or 'sin_bucket'};"
            f" score={performance_score:.2f};"
            f" er={engagement_rate:.2f}"
        )
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE content_items
                SET performance_bucket = ?,
                    latest_performance_score = ?,
                    latest_engagement_rate = ?,
                    recycle_reusable = ?,
                    recycle_republishable = ?,
                    recycle_story_adaptable = ?,
                    recycle_reason = ?,
                    updated_at = ?
                WHERE content_key = ?
                """,
                (
                    bucket,
                    performance_score,
                    engagement_rate,
                    int(recyclable),
                    int(republishable),
                    int(adaptable_story),
                    reason,
                    utc_now_iso(),
                    str(item.get("content_key") or ""),
                ),
            )

    def save_comment_action(
        self,
        publication_id: int,
        *,
        platform: str,
        comment_id: str,
        author_username: str,
        comment_text: str,
        liked: bool,
        replied: bool,
        reply_id: str,
        payload: Dict[str, Any],
    ) -> None:
        now = utc_now_iso()
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO comment_actions (
                    publication_id, platform, comment_id, author_username, comment_text,
                    liked, replied, reply_id, payload_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform, comment_id) DO UPDATE SET
                    author_username=excluded.author_username,
                    comment_text=excluded.comment_text,
                    liked=excluded.liked,
                    replied=excluded.replied,
                    reply_id=excluded.reply_id,
                    payload_json=excluded.payload_json,
                    updated_at=excluded.updated_at
                """,
                (
                    publication_id,
                    platform,
                    comment_id,
                    author_username,
                    comment_text,
                    int(liked),
                    int(replied),
                    reply_id,
                    safe_json(payload),
                    now,
                    now,
                ),
            )

    def enqueue_job(
        self,
        *,
        run_id: str,
        job_type: str,
        stage: str,
        status: str,
        content_key: str = "",
        payload: Dict[str, Any] | None = None,
        error_message: str = "",
    ) -> int:
        now = utc_now_iso()
        with self.connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO jobs (
                    run_id, job_type, content_key, stage, status, attempts,
                    payload_json, error_message, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    job_type,
                    content_key,
                    stage,
                    status,
                    safe_json(payload or {}),
                    error_message,
                    now,
                    now,
                ),
            )
        return int(cur.lastrowid)

    def list_failed_jobs(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self._rows(
            """
            SELECT * FROM jobs
            WHERE status = 'failed'
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        )

    def queue_summary(self) -> List[Dict[str, Any]]:
        return self._rows(
            """
            SELECT pipeline_status, COUNT(*) AS total
            FROM content_items
            GROUP BY pipeline_status
            ORDER BY total DESC
            """
        )

    def autorun_health_counts(
        self,
        now_iso: str,
        *,
        min_extracted_at: str,
        retry_limit: int,
    ) -> Dict[str, Any]:
        with self.connection() as conn:
            status_rows = conn.execute(
                """
                SELECT pipeline_status, COUNT(*) AS total
                FROM content_items
                GROUP BY pipeline_status
                """
            ).fetchall()
            due_to_publish = conn.execute(
                """
                SELECT COUNT(*)
                FROM content_items
                WHERE pipeline_status = 'scheduled'
                  AND formatted_json IS NOT NULL
                  AND schedule_json IS NOT NULL
                  AND json_extract(schedule_json, '$.scheduled_for') <= ?
                  AND COALESCE(extracted_at, '') >= ?
                """,
                (now_iso, min_extracted_at),
            ).fetchone()[0]
            scheduled_future = conn.execute(
                """
                SELECT COUNT(*)
                FROM content_items
                WHERE pipeline_status = 'scheduled'
                  AND formatted_json IS NOT NULL
                  AND schedule_json IS NOT NULL
                  AND json_extract(schedule_json, '$.scheduled_for') > ?
                """,
                (now_iso,),
            ).fetchone()[0]
            stale_unpublished = conn.execute(
                """
                SELECT COUNT(*)
                FROM content_items
                WHERE pipeline_status IN ('formatted', 'scheduled', 'publish_failed')
                  AND COALESCE(extracted_at, '') < ?
                  AND content_key NOT IN (
                      SELECT content_key
                      FROM publications
                      WHERE status = 'published'
                  )
                """,
                (min_extracted_at,),
            ).fetchone()[0]
            retry_exhausted = conn.execute(
                """
                SELECT COUNT(*)
                FROM content_items
                WHERE pipeline_status IN ('score_failed', 'editorial_failed', 'format_failed', 'publish_failed')
                  AND retry_count >= ?
                """,
                (max(1, int(retry_limit)),),
            ).fetchone()[0]
        return {
            "status_counts": {str(row["pipeline_status"]): int(row["total"]) for row in status_rows},
            "due_to_publish": int(due_to_publish or 0),
            "scheduled_future": int(scheduled_future or 0),
            "stale_unpublished": int(stale_unpublished or 0),
            "retry_exhausted": int(retry_exhausted or 0),
        }

    def stats_summary(self) -> Dict[str, Any]:
        with self.connection() as conn:
            content_total = conn.execute("SELECT COUNT(*) FROM content_items").fetchone()[0]
            published_total = conn.execute(
                "SELECT COUNT(*) FROM publications WHERE status = 'published'"
            ).fetchone()[0]
            failed_total = conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE status = 'failed'"
            ).fetchone()[0]
            analytics_total = conn.execute(
                "SELECT COUNT(*) FROM analytics_snapshots"
            ).fetchone()[0]
            report_total = conn.execute("SELECT COUNT(*) FROM daily_reports").fetchone()[0]
            top_snapshots = conn.execute(
                """
                SELECT metrics_json
                FROM analytics_snapshots
                ORDER BY collected_at DESC
                LIMIT 20
                """
            ).fetchall()
        return {
            "content_total": content_total,
            "published_total": published_total,
            "failed_jobs": failed_total,
            "analytics_checkpoints": analytics_total,
            "daily_reports": report_total,
            "recent_snapshots": [json.loads(row[0]) for row in top_snapshots],
        }

    def performance_rows(
        self,
        lookback_days: int = 30,
        *,
        checkpoint_label: str | None = None,
        latest_only: bool = True,
    ) -> List[Dict[str, Any]]:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=lookback_days)
        ).replace(microsecond=0).isoformat()
        rows = self._rows(
            """
            SELECT c.id AS content_id, c.content_key, c.source, c.source_type, c.source_handle,
                   c.title, c.summary, c.media_type, c.score_json, c.score_total, c.score_novelty,
                   c.score_engagement, c.score_debate, c.score_repostability, c.score_theme,
                   c.editorial_json, c.editorial_prompt, c.editorial_input_json, c.editorial_feedback,
                   c.editorial_hook_type, c.editorial_tone, c.editorial_signature, c.final_caption,
                   c.final_overlay, c.assigned_post_type, c.schedule_json, c.assigned_slot,
                   c.assigned_time, c.performance_bucket AS content_bucket, c.recycle_reusable,
                   c.recycle_republishable, c.recycle_story_adaptable, p.id AS publication_id,
                   p.platform, p.platform_media_id, p.platform_post_id, p.permalink, p.post_type,
                   p.published_at, a.id AS snapshot_id, a.checkpoint_label, a.checkpoint_order,
                   a.collected_at, a.views, a.likes, a.comments, a.shares, a.engagement_rate,
                   a.performance_score, a.performance_bucket, a.metrics_json
            FROM content_items c
            JOIN publications p ON p.content_key = c.content_key
            JOIN analytics_snapshots a ON a.publication_id = p.id
            WHERE p.status = 'published'
              AND p.published_at >= ?
            ORDER BY p.published_at DESC, COALESCE(a.checkpoint_order, 0) DESC, a.collected_at DESC
            """,
            (cutoff,),
        )
        if not rows:
            return []
        if not latest_only and not checkpoint_label:
            return rows
        return self._prefer_snapshots(rows, checkpoint_label=checkpoint_label)

    def recent_editorial_context(self, limit: int = 15) -> List[Dict[str, Any]]:
        return self._rows(
            """
            SELECT content_key, source, source_handle, title, editorial_json, editorial_hook_type,
                   editorial_tone, editorial_signature, final_caption, final_overlay,
                   assigned_post_type, assigned_slot, assigned_time, pipeline_status, updated_at
            FROM content_items
            WHERE editorial_json IS NOT NULL
            ORDER BY COALESCE(assigned_time, updated_at) DESC
            LIMIT ?
            """,
            (limit,),
        )

    def source_activity_rows(self, source: str, lookback_days: int = 30) -> List[Dict[str, Any]]:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=lookback_days)
        ).replace(microsecond=0).isoformat()
        return self._rows(
            """
            SELECT content_key, source, source_handle, extracted_at, pipeline_status,
                   performance_bucket, latest_performance_score, latest_engagement_rate
            FROM content_items
            WHERE source = ?
              AND extracted_at >= ?
            ORDER BY extracted_at DESC
            """,
            (source, cutoff),
        )

    def save_daily_report(self, report_date: str, report: Dict[str, Any]) -> None:
        now = utc_now_iso()
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO daily_reports (report_date, report_json, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(report_date) DO UPDATE SET
                    report_json=excluded.report_json,
                    updated_at=excluded.updated_at
                """,
                (report_date, safe_json(report), now, now),
            )

    def get_daily_report(self, report_date: str) -> Optional[Dict[str, Any]]:
        rows = self._rows(
            """
            SELECT report_json
            FROM daily_reports
            WHERE report_date = ?
            LIMIT 1
            """,
            (report_date,),
        )
        if not rows:
            return None
        return self._load_json(rows[0].get("report_json"))

    def save_score_validation_run(self, payload: Dict[str, Any]) -> None:
        with self.connection() as conn:
            conn.execute(
                """
                INSERT INTO score_validation_runs (
                    checkpoint_label, lookback_days, correlation, accuracy_score,
                    mean_absolute_deviation, mean_signed_deviation, overestimated_count,
                    underestimated_count, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(payload.get("checkpoint_label") or "latest"),
                    int(payload.get("lookback_days") or 0),
                    float(payload.get("correlation") or 0.0),
                    float(payload.get("accuracy_score") or 0.0),
                    float(payload.get("mean_absolute_deviation") or 0.0),
                    float(payload.get("mean_signed_deviation") or 0.0),
                    int(payload.get("overestimated_count") or 0),
                    int(payload.get("underestimated_count") or 0),
                    safe_json(payload),
                    utc_now_iso(),
                ),
            )

    def mark_status(self, content_key: str, status: str, error_message: str = "") -> None:
        with self.connection() as conn:
            conn.execute(
                """
                UPDATE content_items
                SET pipeline_status = ?,
                    last_error = ?,
                    errors = ?,
                    retry_count = CASE
                        WHEN ? LIKE '%failed' THEN retry_count + 1
                        ELSE retry_count
                    END,
                    updated_at = ?
                WHERE content_key = ?
                """,
                (status, error_message, error_message, status, utc_now_iso(), content_key),
            )

    def requeue_unpublished_for_rebuild(self) -> int:
        with self.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE content_items
                SET editorial_json = NULL,
                    editorial_prompt = NULL,
                    editorial_input_json = NULL,
                    editorial_feedback = NULL,
                    editorial_hook_type = NULL,
                    editorial_tone = NULL,
                    editorial_signature = NULL,
                    formatted_json = NULL,
                    schedule_json = NULL,
                    final_caption = NULL,
                    final_overlay = NULL,
                    assigned_post_type = NULL,
                    assigned_slot = NULL,
                    assigned_time = NULL,
                    pipeline_status = 'scored',
                    last_error = '',
                    updated_at = ?
                WHERE pipeline_status IN ('editorialized', 'formatted', 'scheduled', 'publish_failed')
                  AND content_key NOT IN (
                      SELECT content_key
                      FROM publications
                      WHERE status = 'published'
                  )
                """,
                (utc_now_iso(),),
            )
            return int(cursor.rowcount or 0)

    def rows_by_status(self, status: str, limit: int = 50) -> List[Dict[str, Any]]:
        return self._rows(
            """
            SELECT * FROM content_items
            WHERE pipeline_status = ?
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (status, limit),
        )

    def reset_failed_for_retry(self, content_key: str, target_status: str) -> bool:
        clear_score = target_status == "extracted"
        clear_editorial = target_status in {"extracted", "scored"}
        clear_formatted = target_status in {"extracted", "scored", "editorialized"}
        clear_schedule = target_status in {"extracted", "scored", "editorialized", "formatted"}
        with self.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE content_items
                SET pipeline_status = ?,
                    score_json = CASE WHEN ? THEN NULL ELSE score_json END,
                    score_total = CASE WHEN ? THEN NULL ELSE score_total END,
                    score_novelty = CASE WHEN ? THEN NULL ELSE score_novelty END,
                    score_engagement = CASE WHEN ? THEN NULL ELSE score_engagement END,
                    score_debate = CASE WHEN ? THEN NULL ELSE score_debate END,
                    score_repostability = CASE WHEN ? THEN NULL ELSE score_repostability END,
                    score_theme = CASE WHEN ? THEN NULL ELSE score_theme END,
                    score_reason = CASE WHEN ? THEN NULL ELSE score_reason END,
                    score_version = CASE WHEN ? THEN NULL ELSE score_version END,
                    safety_json = CASE WHEN ? THEN NULL ELSE safety_json END,
                    editorial_json = CASE WHEN ? THEN NULL ELSE editorial_json END,
                    editorial_output_json = CASE WHEN ? THEN NULL ELSE editorial_output_json END,
                    editorial_prompt = CASE WHEN ? THEN NULL ELSE editorial_prompt END,
                    editorial_input_json = CASE WHEN ? THEN NULL ELSE editorial_input_json END,
                    editorial_feedback = CASE WHEN ? THEN NULL ELSE editorial_feedback END,
                    editorial_hook_type = CASE WHEN ? THEN NULL ELSE editorial_hook_type END,
                    editorial_tone = CASE WHEN ? THEN NULL ELSE editorial_tone END,
                    editorial_signature = CASE WHEN ? THEN NULL ELSE editorial_signature END,
                    formatted_json = CASE WHEN ? THEN NULL ELSE formatted_json END,
                    formatted_output_json = CASE WHEN ? THEN NULL ELSE formatted_output_json END,
                    media_output_paths = CASE WHEN ? THEN NULL ELSE media_output_paths END,
                    final_caption = CASE WHEN ? THEN NULL ELSE final_caption END,
                    final_overlay = CASE WHEN ? THEN NULL ELSE final_overlay END,
                    schedule_json = CASE WHEN ? THEN NULL ELSE schedule_json END,
                    assigned_slot = CASE WHEN ? THEN NULL ELSE assigned_slot END,
                    assigned_time = CASE WHEN ? THEN NULL ELSE assigned_time END,
                    scheduled_at = CASE WHEN ? THEN NULL ELSE scheduled_at END,
                    publish_status = NULL,
                    last_error = '',
                    errors = '',
                    updated_at = ?
                WHERE content_key = ?
                """,
                (
                    target_status,
                    int(clear_score),
                    int(clear_score),
                    int(clear_score),
                    int(clear_score),
                    int(clear_score),
                    int(clear_score),
                    int(clear_score),
                    int(clear_score),
                    int(clear_score),
                    int(clear_score),
                    int(clear_editorial),
                    int(clear_editorial),
                    int(clear_editorial),
                    int(clear_editorial),
                    int(clear_editorial),
                    int(clear_editorial),
                    int(clear_editorial),
                    int(clear_editorial),
                    int(clear_formatted),
                    int(clear_formatted),
                    int(clear_formatted),
                    int(clear_formatted),
                    int(clear_formatted),
                    int(clear_schedule),
                    int(clear_schedule),
                    int(clear_schedule),
                    int(clear_schedule),
                    utc_now_iso(),
                    content_key,
                ),
            )
            return bool(cursor.rowcount)

    def queue_rows(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self._rows(
            """
            SELECT content_key, source, source_type, source_handle, title, media_type,
                   score_total, score_theme, assigned_post_type, assigned_slot,
                   assigned_time, pipeline_status, publish_status, last_error, updated_at
            FROM content_items
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        )

    def inspect_content(self, content_key: str) -> Optional[Dict[str, Any]]:
        row = self.find_content(content_key)
        if not row:
            return None
        parsed = dict(row)
        for key in (
            "visible_metrics_json",
            "ranking_signals_json",
            "raw_payload_json",
            "assets_json",
            "score_json",
            "safety_json",
            "duplication_json",
            "editorial_json",
            "formatted_json",
            "schedule_json",
            "growth_feedback_json",
        ):
            parsed[f"{key}_parsed"] = self._load_json_any(row.get(key))
        return parsed

    def skip_content(self, content_key: str, reason: str) -> bool:
        with self.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE content_items
                SET pipeline_status = 'skipped',
                    publish_status = 'skipped',
                    last_error = ?,
                    errors = ?,
                    updated_at = ?
                WHERE content_key = ?
                """,
                (reason, reason, utc_now_iso(), content_key),
            )
            return bool(cursor.rowcount)

    def retry_content(self, content_key: str) -> bool:
        row = self.find_content(content_key)
        if not row:
            return False
        reset_score = str(row.get("pipeline_status") or "") in {"filtered", "score_failed"}
        if reset_score:
            target = "extracted"
        elif not row.get("score_json"):
            target = "extracted"
        elif not row.get("editorial_json"):
            target = "scored"
        elif not row.get("formatted_json"):
            target = "editorialized"
        elif not row.get("schedule_json"):
            target = "formatted"
        else:
            target = "scheduled"
        with self.connection() as conn:
            cursor = conn.execute(
                """
                UPDATE content_items
                SET pipeline_status = ?,
                    score_json = CASE WHEN ? THEN NULL ELSE score_json END,
                    score_total = CASE WHEN ? THEN NULL ELSE score_total END,
                    score_novelty = CASE WHEN ? THEN NULL ELSE score_novelty END,
                    score_engagement = CASE WHEN ? THEN NULL ELSE score_engagement END,
                    score_debate = CASE WHEN ? THEN NULL ELSE score_debate END,
                    score_repostability = CASE WHEN ? THEN NULL ELSE score_repostability END,
                    score_theme = CASE WHEN ? THEN NULL ELSE score_theme END,
                    score_reason = CASE WHEN ? THEN NULL ELSE score_reason END,
                    score_version = CASE WHEN ? THEN NULL ELSE score_version END,
                    safety_json = CASE WHEN ? THEN NULL ELSE safety_json END,
                    editorial_json = CASE WHEN ? THEN NULL ELSE editorial_json END,
                    editorial_output_json = CASE WHEN ? THEN NULL ELSE editorial_output_json END,
                    formatted_json = CASE WHEN ? THEN NULL ELSE formatted_json END,
                    formatted_output_json = CASE WHEN ? THEN NULL ELSE formatted_output_json END,
                    schedule_json = CASE WHEN ? THEN NULL ELSE schedule_json END,
                    publish_status = NULL,
                    last_error = '',
                    errors = '',
                    updated_at = ?
                WHERE content_key = ?
                """,
                (
                    target,
                    int(reset_score),
                    int(reset_score),
                    int(reset_score),
                    int(reset_score),
                    int(reset_score),
                    int(reset_score),
                    int(reset_score),
                    int(reset_score),
                    int(reset_score),
                    int(reset_score),
                    int(reset_score),
                    int(reset_score),
                    int(reset_score),
                    int(reset_score),
                    int(reset_score),
                    utc_now_iso(),
                    content_key,
                ),
            )
            return bool(cursor.rowcount)

    def checkpoint_definitions(self, checkpoint_hours: Sequence[int] | None = None) -> List[Dict[str, int | str]]:
        values = tuple(checkpoint_hours or self.settings.analytics_checkpoint_hours)
        checkpoints: List[Dict[str, int | str]] = []
        for index, hours in enumerate(values, start=1):
            checkpoints.append({"label": f"T{index}", "order": index, "hours": int(hours)})
        return checkpoints

    def report_publications_for_date(self, report_date: date) -> List[Dict[str, Any]]:
        day_start = datetime(
            year=report_date.year,
            month=report_date.month,
            day=report_date.day,
            tzinfo=timezone.utc,
        )
        next_day = day_start + timedelta(days=1)
        rows = self.performance_rows(lookback_days=7, latest_only=True)
        selected: List[Dict[str, Any]] = []
        for row in rows:
            published_at = self._parse_dt(row.get("published_at"))
            if published_at is None:
                continue
            if day_start <= published_at < next_day:
                selected.append(row)
        return selected

    def _prefer_snapshots(
        self,
        rows: Sequence[Dict[str, Any]],
        *,
        checkpoint_label: str | None = None,
    ) -> List[Dict[str, Any]]:
        grouped: Dict[int, List[Dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(int(row["publication_id"]), []).append(row)
        selected: List[Dict[str, Any]] = []
        for items in grouped.values():
            preferred: Optional[Dict[str, Any]] = None
            if checkpoint_label:
                for row in items:
                    if str(row.get("checkpoint_label") or "") == checkpoint_label:
                        preferred = row
                        break
            if preferred is None:
                preferred = sorted(
                    items,
                    key=lambda row: (
                        int(row.get("checkpoint_order") or 0),
                        str(row.get("collected_at") or ""),
                    ),
                    reverse=True,
                )[0]
            selected.append(preferred)
        selected.sort(key=lambda row: str(row.get("published_at") or ""), reverse=True)
        return selected

    @staticmethod
    def _parse_dt(value: object) -> Optional[datetime]:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    @staticmethod
    def _load_json(raw: object) -> Dict[str, Any]:
        try:
            payload = json.loads(str(raw or ""))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _load_json_any(raw: object) -> Any:
        try:
            return json.loads(str(raw or ""))
        except Exception:
            return {}

    def _rows(self, query: str, params: Iterable[Any] = ()) -> List[Dict[str, Any]]:
        with self.connection() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [dict(row) for row in rows]

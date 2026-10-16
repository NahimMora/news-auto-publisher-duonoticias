from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from storage.models import (
    EditorialPackage,
    ExtractedContent,
    FormattedPackage,
    PublicationRecord,
    ScheduleDecision,
    ViralityScore,
)
from storage.settings import get_settings
from storage.sqlite_store import PipelineStore


class SQLiteStoreTests(unittest.TestCase):
    def test_migrates_legacy_analytics_table_before_creating_checkpoint_index(self) -> None:
        with tempfile.TemporaryDirectory(prefix="duo_store_") as tmp_dir:
            db_path = Path(tmp_dir) / "legacy.sqlite3"
            conn = sqlite3.connect(db_path)
            try:
                conn.executescript(
                    """
                    CREATE TABLE content_items (
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
                        editorial_json TEXT,
                        formatted_json TEXT,
                        schedule_json TEXT,
                        pipeline_status TEXT DEFAULT 'extracted',
                        published_platforms_json TEXT DEFAULT '[]',
                        last_error TEXT,
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE publications (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        content_key TEXT NOT NULL,
                        platform TEXT NOT NULL,
                        status TEXT NOT NULL,
                        platform_media_id TEXT,
                        container_id TEXT,
                        permalink TEXT,
                        caption TEXT,
                        scheduled_for TEXT,
                        published_at TEXT,
                        error_message TEXT,
                        payload_json TEXT,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        UNIQUE(content_key, platform)
                    );
                    CREATE TABLE analytics_snapshots (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        publication_id INTEGER NOT NULL,
                        collected_at TEXT NOT NULL,
                        metrics_json TEXT NOT NULL
                    );
                    """
                )
                conn.commit()
            finally:
                conn.close()
            with patch.dict(os.environ, {"DUO_DB_PATH": str(db_path)}):
                get_settings.cache_clear()
                store = PipelineStore(get_settings())
                with store.connection() as migrated:
                    columns = {
                        row["name"]
                        for row in migrated.execute("PRAGMA table_info(analytics_snapshots)").fetchall()
                    }
                self.assertIn("checkpoint_label", columns)
                self.assertIn("performance_bucket", columns)

    def test_traceability_and_checkpoints_are_persisted(self) -> None:
        with tempfile.TemporaryDirectory(prefix="duo_store_") as tmp_dir:
            db_path = Path(tmp_dir) / "duo.sqlite3"
            with patch.dict(os.environ, {"DUO_DB_PATH": str(db_path)}):
                get_settings.cache_clear()
                store = PipelineStore(get_settings())
                content = ExtractedContent(
                    source="x",
                    source_type="x_video",
                    source_item_id="123",
                    canonical_url="https://x.com/i/status/123",
                    source_handle="cuenta_test",
                    title="Clip viral",
                    summary="Resumen",
                    body_text="Texto",
                    media_type="video",
                )
                key = store.upsert_content(content)

                score = ViralityScore(
                    total=88,
                    novelty=80,
                    engagement_potential=90,
                    debate_potential=85,
                    repostability=70,
                    emotional_impact=75,
                    clarity=90,
                    duration_fit=80,
                    topic_fit=70,
                    publish=True,
                    reason="test",
                    theme="tendencia",
                )
                store.save_score(key, score)
                editorial = EditorialPackage(
                    hook="Hook",
                    context="Contexto",
                    tension="Tension",
                    remate="Remate",
                    cta="CTA",
                    caption="Caption final",
                    overlay="Overlay final",
                    publish=True,
                    reason="editorial_ok",
                    angle="conflicto",
                    style="agresivo",
                    prompt_used="PROMPT TEST",
                    input_payload={"title": "Clip viral"},
                    feedback_summary="CONTENIDO QUE FUNCIONA:\n- preguntas",
                    hook_type="pregunta",
                    tone="debate",
                    pattern_signature="abc123",
                )
                store.save_editorial(key, editorial)
                formatted = FormattedPackage(content_key=key, post_type="reel", caption="Caption final")
                store.save_formatted(key, formatted)
                schedule = ScheduleDecision(
                    scheduled_for="2026-04-05T21:00:00+00:00",
                    slot_label="21:00",
                    priority_rank=1,
                    reason="score=88",
                    slot_bucket="alto",
                )
                store.save_schedule(key, schedule)
                publication_id = store.save_publication(
                    key,
                    PublicationRecord(
                        platform="instagram",
                        status="published",
                        platform_media_id="1789",
                        platform_post_id="1789",
                        post_type="reel",
                        caption="Caption final",
                        scheduled_for=schedule.scheduled_for,
                        published_at="2026-04-05T21:00:00+00:00",
                    ),
                )
                store.save_analytics_snapshot(
                    publication_id,
                    {"details": {}, "insights": {}},
                    checkpoint_label="T1",
                    checkpoint_order=1,
                    due_at="2026-04-05T22:00:00+00:00",
                    publication_age_minutes=60,
                    views=1000,
                    likes=120,
                    comments=30,
                    shares=12,
                    engagement_rate=16.2,
                    performance_score=1450.0,
                    performance_bucket="alto",
                )
                store.refresh_content_performance(publication_id)
                row = store.find_content(key)
                assert row is not None
                self.assertEqual(row["score_total"], 88)
                self.assertEqual(row["editorial_prompt"], "PROMPT TEST")
                self.assertEqual(row["final_caption"], "Caption final")
                self.assertEqual(row["final_overlay"], "Overlay final")
                self.assertEqual(row["assigned_post_type"], "reel")
                self.assertEqual(row["assigned_slot"], "21:00")
                self.assertEqual(row["last_post_id"], "1789")
                self.assertEqual(row["performance_bucket"], "alto")
                self.assertEqual(row["recycle_reusable"], 1)

    def test_requeue_unpublished_for_rebuild_clears_pending_outputs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="duo_store_") as tmp_dir:
            db_path = Path(tmp_dir) / "duo.sqlite3"
            with patch.dict(os.environ, {"DUO_DB_PATH": str(db_path)}):
                get_settings.cache_clear()
                store = PipelineStore(get_settings())
                content = ExtractedContent(
                    source="news",
                    source_type="article",
                    source_item_id="1",
                    canonical_url="https://example.com/1",
                    title="Titulo",
                    summary="Resumen",
                    body_text="Texto",
                    media_type="image",
                )
                key = store.upsert_content(content)
                with store.connection() as conn:
                    conn.execute(
                        """
                        UPDATE content_items
                        SET pipeline_status = 'scheduled',
                            editorial_json = '{"caption":"viejo"}',
                            editorial_prompt = 'PROMPT',
                            formatted_json = '{"post_type":"reel"}',
                            schedule_json = '{"slot_label":"21:00"}',
                            final_caption = 'Caption vieja',
                            assigned_post_type = 'reel',
                            assigned_slot = '21:00'
                        WHERE content_key = ?
                        """,
                        (key,),
                    )
                reset = store.requeue_unpublished_for_rebuild()
                row = store.find_content(key)
                assert row is not None
                self.assertEqual(reset, 1)
                self.assertEqual(row["pipeline_status"], "scored")
                self.assertEqual(row["editorial_json"], None)
                self.assertEqual(row["formatted_json"], None)
                self.assertEqual(row["schedule_json"], None)
                self.assertEqual(row["final_caption"], None)
                self.assertEqual(row["assigned_slot"], None)

    def test_reset_failed_for_retry_clears_downstream_outputs_only(self) -> None:
        with tempfile.TemporaryDirectory(prefix="duo_store_") as tmp_dir:
            db_path = Path(tmp_dir) / "duo.sqlite3"
            with patch.dict(os.environ, {"DUO_DB_PATH": str(db_path)}):
                get_settings.cache_clear()
                store = PipelineStore(get_settings())
                content = ExtractedContent(
                    source="news",
                    source_type="article",
                    source_item_id="retry-1",
                    canonical_url="https://example.com/retry-1",
                    title="El Gobierno anuncio una medida",
                    summary="La decision se debate en el Congreso.",
                    body_text="Texto suficiente para una noticia politica local.",
                    media_type="image",
                )
                key = store.upsert_content(content)
                with store.connection() as conn:
                    conn.execute(
                        """
                        UPDATE content_items
                        SET pipeline_status = 'format_failed',
                            score_json = '{"total":70}',
                            score_total = 70,
                            editorial_json = '{"caption":"ok"}',
                            formatted_json = '{"post_type":"image"}',
                            schedule_json = '{"slot_label":"21:00"}',
                            final_caption = 'Caption',
                            assigned_slot = '21:00',
                            assigned_time = '2026-04-05T21:00:00+00:00',
                            publish_status = 'publish_failed',
                            last_error = 'old error',
                            errors = 'old error'
                        WHERE content_key = ?
                        """,
                        (key,),
                    )

                self.assertTrue(store.reset_failed_for_retry(key, "editorialized"))
                row = store.find_content(key)
                assert row is not None
                self.assertEqual(row["pipeline_status"], "editorialized")
                self.assertEqual(row["score_total"], 70)
                self.assertIsNotNone(row["editorial_json"])
                self.assertIsNone(row["formatted_json"])
                self.assertIsNone(row["schedule_json"])
                self.assertIsNone(row["assigned_slot"])
                self.assertIsNone(row["publish_status"])
                self.assertEqual(row["last_error"], "")

    def test_list_upcoming_scheduled_returns_earliest_scheduled_rows(self) -> None:
        with tempfile.TemporaryDirectory(prefix="duo_store_") as tmp_dir:
            db_path = Path(tmp_dir) / "duo.sqlite3"
            with patch.dict(os.environ, {"DUO_DB_PATH": str(db_path)}):
                get_settings.cache_clear()
                store = PipelineStore(get_settings())
                first = ExtractedContent(
                    source="x",
                    source_type="x_video",
                    source_item_id="a",
                    canonical_url="https://x.com/i/status/a",
                    title="Primero",
                    media_type="video",
                )
                second = ExtractedContent(
                    source="news",
                    source_type="article",
                    source_item_id="b",
                    canonical_url="https://example.com/b",
                    title="Segundo",
                    media_type="image",
                )
                first_key = store.upsert_content(first)
                second_key = store.upsert_content(second)
                store.save_formatted(first_key, FormattedPackage(content_key=first_key, post_type="reel", caption="Uno"))
                store.save_formatted(second_key, FormattedPackage(content_key=second_key, post_type="carousel", caption="Dos"))
                store.save_schedule(
                    second_key,
                    ScheduleDecision(
                        scheduled_for="2026-04-07T15:00:00+00:00",
                        slot_label="12:00",
                        priority_rank=2,
                        reason="score=62",
                        slot_bucket="medio",
                    ),
                )
                store.save_schedule(
                    first_key,
                    ScheduleDecision(
                        scheduled_for="2026-04-07T12:00:00+00:00",
                        slot_label="09:00",
                        priority_rank=1,
                        reason="score=58",
                        slot_bucket="experimental",
                    ),
                )
                upcoming = store.list_upcoming_scheduled(limit=2)
                self.assertEqual(len(upcoming), 2)
                self.assertEqual(upcoming[0]["content_key"], first_key)
                self.assertEqual(upcoming[0]["assigned_time"], "2026-04-07T12:00:00+00:00")
                self.assertEqual(upcoming[1]["content_key"], second_key)


if __name__ == "__main__":
    unittest.main()

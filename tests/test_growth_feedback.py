from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from growth.feedback import GrowthFeedbackService
from growth.validation import ScoreValidationService
from storage.models import PublicationRecord
from storage.settings import get_settings
from storage.sqlite_store import PipelineStore


class GrowthFeedbackTests(unittest.TestCase):
    def test_feedback_summary_and_validation_use_real_rows(self) -> None:
        with tempfile.TemporaryDirectory(prefix="duo_growth_") as tmp_dir:
            db_path = Path(tmp_dir) / "duo.sqlite3"
            with patch.dict(os.environ, {"DUO_DB_PATH": str(db_path)}):
                get_settings.cache_clear()
                store = PipelineStore(get_settings())
                base_rows = [
                    {
                        "content_key": "elite",
                        "source": "x",
                        "source_type": "x_video",
                        "source_handle": "cuenta_ganadora",
                        "title": "Escandalo total",
                        "summary": "Resumen",
                        "body_text": "Texto",
                        "media_type": "video",
                        "updated_at": "2026-04-05T00:00:00+00:00",
                    },
                    {
                        "content_key": "fracaso",
                        "source": "x",
                        "source_type": "x_video",
                        "source_handle": "cuenta_floja",
                        "title": "Parte oficial",
                        "summary": "Resumen",
                        "body_text": "Texto",
                        "media_type": "image",
                        "updated_at": "2026-04-05T00:00:00+00:00",
                    },
                ]
                with store.connection() as conn:
                    for row in base_rows:
                        conn.execute(
                            """
                            INSERT INTO content_items (
                                content_key, source, source_type, source_handle, title, summary, body_text,
                                media_type, score_total, editorial_json, editorial_hook_type, editorial_tone,
                                final_caption, final_overlay, assigned_post_type, assigned_slot, updated_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                row["content_key"],
                                row["source"],
                                row["source_type"],
                                row["source_handle"],
                                row["title"],
                                row["summary"],
                                row["body_text"],
                                row["media_type"],
                                90 if row["content_key"] == "elite" else 35,
                                '{"hook":"%s","caption":"caption"}' % row["title"],
                                "conflicto" if row["content_key"] == "elite" else "directo",
                                "debate" if row["content_key"] == "elite" else "informativo",
                                "caption extensa" if row["content_key"] == "elite" else "caption corta",
                                row["title"],
                                "reel" if row["content_key"] == "elite" else "image",
                                "21:00" if row["content_key"] == "elite" else "09:00",
                                row["updated_at"],
                            ),
                        )
                        conn.execute(
                            """
                            INSERT INTO publications (
                                content_key, platform, status, platform_media_id, platform_post_id,
                                caption, post_type, published_at, created_at, updated_at
                            ) VALUES (?, 'instagram', 'published', ?, ?, 'caption', ?, '2026-04-05T00:00:00+00:00',
                                      '2026-04-05T00:00:00+00:00', '2026-04-05T00:00:00+00:00')
                            """,
                            (
                                row["content_key"],
                                row["content_key"],
                                row["content_key"],
                                "reel" if row["content_key"] == "elite" else "image",
                            ),
                        )
                    pub_rows = conn.execute("SELECT id, content_key FROM publications").fetchall()
                    for pub in pub_rows:
                        if pub["content_key"] == "elite":
                            perf = 3000.0
                            bucket = "elite"
                        else:
                            perf = 150.0
                            bucket = "fracaso"
                        conn.execute(
                            """
                            INSERT INTO analytics_snapshots (
                                publication_id, checkpoint_label, checkpoint_order, collected_at,
                                views, likes, comments, shares, engagement_rate, performance_score,
                                performance_bucket, metrics_json
                            ) VALUES (?, 'T3', 3, '2026-04-06T00:00:00+00:00', 0, 0, 0, 0, 0, ?, ?, '{}')
                            """,
                            (pub["id"], perf, bucket),
                        )
                feedback = GrowthFeedbackService(store).build_feedback_summary()
                self.assertIn("CONTENIDO QUE FUNCIONA:", feedback)
                self.assertIn("EVITAR:", feedback)
                validation = ScoreValidationService(store).validate(lookback_days=30, checkpoint_label="T3")
                self.assertEqual(validation["total_samples"], 2)
                self.assertIn("accuracy_score", validation)


if __name__ == "__main__":
    unittest.main()

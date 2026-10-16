from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jobs.pipeline import DuoPipeline
from storage.settings import get_settings


class VerticalSliceTests(unittest.TestCase):
    def test_manual_x_url_reaches_schedule_in_dry_run_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="duo_vertical_") as tmp_dir:
            db_path = Path(tmp_dir) / "duo.sqlite3"
            with patch.dict(
                os.environ,
                {
                    "DUO_DB_PATH": str(db_path),
                    "X_MODE": "manual",
                    "OPENAI_API_KEY": "",
                    "DUO_LIVE_PUBLISH_ENABLED": "0",
                    "DUO_SCORE_THRESHOLD": "0",
                    "DUO_SCORE_KEEP_FLOOR": "0",
                    "DUO_PUBLISH_REQUIRE_SAME_LOCAL_DAY": "0",
                },
            ):
                get_settings.cache_clear()
                pipeline = DuoPipeline(get_settings())
                key = pipeline.import_x_url("MOCK_URL", dry_run=True)
                self.assertTrue(key)

                self.assertEqual(pipeline.run_scoring(limit=1), 1)
                self.assertEqual(pipeline.run_editorial(limit=1, force_fallback=True), 1)
                self.assertEqual(pipeline.run_formatter(limit=1, dry_run=True), 1)
                self.assertEqual(pipeline.run_scheduler(limit=1), 1)

                row = pipeline.store.find_content(key)
                assert row is not None
                self.assertEqual(row["pipeline_status"], "scheduled")
                self.assertEqual(row["assigned_post_type"], "reel")
                self.assertIsNotNone(row["score_json"])
                self.assertIsNotNone(row["editorial_json"])
                self.assertIsNotNone(row["formatted_json"])
                self.assertIsNotNone(row["schedule_json"])


if __name__ == "__main__":
    unittest.main()

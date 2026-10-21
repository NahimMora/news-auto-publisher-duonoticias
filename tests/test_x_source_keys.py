from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from extractors.holasalta.keys import tweet_id_from_url
from storage.models import ExtractedContent
from storage.settings import get_settings
from storage.sqlite_store import PipelineStore


class TweetIdTests(unittest.TestCase):
    def test_tweet_id_from_url(self) -> None:
        self.assertEqual(tweet_id_from_url("https://x.com/a/status/123?s=20"), "123")
        self.assertEqual(tweet_id_from_url("https://x.com/a"), "")


class HasSourceItemTests(unittest.TestCase):
    def tearDown(self) -> None:
        get_settings.cache_clear()

    def test_has_source_item(self) -> None:
        with tempfile.TemporaryDirectory(prefix="duo_hs_store_") as tmp_dir:
            with patch.dict(os.environ, {"DUO_DB_PATH": str(Path(tmp_dir) / "duo.sqlite3"), "SQLITE_PATH": ""}, clear=False):
                get_settings.cache_clear()
                store = PipelineStore(get_settings())
                store.upsert_content(
                    ExtractedContent(source="x", source_type="x_video", source_item_id="123", canonical_url="https://x.com/a/status/123")
                )
                self.assertTrue(store.has_source_item("x", "123"))
                self.assertFalse(store.has_source_item("x", "999"))
                self.assertFalse(store.has_source_item("x", ""))


if __name__ == "__main__":
    unittest.main()

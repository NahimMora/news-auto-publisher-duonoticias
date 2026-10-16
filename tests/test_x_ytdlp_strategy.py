from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from extractor_x import extractor_x_videos as legacy_x
from extractors.x.yt_dlp_strategy import YtDlpXStrategy
from storage.settings import get_settings


class XYtDlpStrategyTests(unittest.TestCase):
    def tearDown(self) -> None:
        get_settings.cache_clear()

    def test_extract_skips_old_urls_before_probing_ytdlp(self) -> None:
        strategy = YtDlpXStrategy(get_settings())
        recent_id = str(((1715000000 * 1000 - 1288834974657) << 22))
        old_id = str(((1710000000 * 1000 - 1288834974657) << 22))
        with patch(
            "extractors.x.yt_dlp_strategy._fetch_recent_tweet_urls",
            return_value=[
                f"https://twitter.com/test/status/{old_id}",
                f"https://twitter.com/test/status/{recent_id}",
                f"https://twitter.com/test/status/{recent_id}",
            ],
        ), patch(
            "extractors.x.yt_dlp_strategy.time.time",
            return_value=1715003600,
        ), patch(
            "extractors.x.yt_dlp_strategy._extract_tweet_info",
            return_value={
                "id": recent_id,
                "webpage_url": f"https://twitter.com/test/status/{recent_id}",
                "description": "Video reciente",
                "timestamp": 1715000000,
                "duration": 12,
                "formats": [{"ext": "mp4", "url": "https://cdn.example/video.mp4", "height": 720, "tbr": 1000}],
            },
        ) as extract_mock:
            rows = strategy.extract("test", limit=5, max_age_hours=24)

        self.assertEqual(len(rows), 1)
        extract_mock.assert_called_once()


class XLegacyFeedCacheTests(unittest.TestCase):
    def test_fetch_recent_tweet_urls_filters_old_cache_entries(self) -> None:
        with tempfile.TemporaryDirectory(prefix="duo_x_cache_") as tmp_dir:
            base_dir = Path(tmp_dir)
            recent_id = str(((1715000000 * 1000 - 1288834974657) << 22))
            old_id = str(((1710000000 * 1000 - 1288834974657) << 22))
            cache_path = base_dir / "cache_testuser.json"
            cache_path.write_text(
                json.dumps(
                    [
                        f"https://twitter.com/testuser/status/{old_id}",
                        f"https://twitter.com/testuser/status/{recent_id}",
                    ]
                ),
                encoding="utf-8",
            )
            with patch.object(legacy_x, "BASE_DIR", base_dir), patch(
                "extractor_x.extractor_x_videos._graphql_search_timeline",
                return_value=[],
            ), patch(
                "extractor_x.extractor_x_videos.httpx.get",
                side_effect=RuntimeError("network down"),
            ), patch(
                "extractor_x.extractor_x_videos.time.time",
                return_value=1715003600,
            ):
                urls = legacy_x._fetch_recent_tweet_urls(
                    "testuser",
                    max_items=10,
                    cookies_path=None,
                    max_age_seconds=24 * 3600,
                )

        self.assertEqual(urls, [f"https://twitter.com/testuser/status/{recent_id}"])


if __name__ == "__main__":
    unittest.main()

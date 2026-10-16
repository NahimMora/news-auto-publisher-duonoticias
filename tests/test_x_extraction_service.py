from __future__ import annotations

import unittest
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock
from unittest.mock import patch

from extractors.x.service import XExtractionService
from storage.settings import get_settings


class XExtractionServiceTests(unittest.TestCase):
    def test_normalizes_full_urls_and_dedupes_handles(self) -> None:
        with patch.dict(os.environ, {"X_MODE": "browser"}):
            get_settings.cache_clear()
            service = XExtractionService(get_settings())
            service.playwright_strategy.extract = Mock(return_value=[])
            service.ytdlp_strategy.extract = Mock(return_value=[])

            service.extract(
                handles=[
                    "@UnPocoTende",
                    "https://x.com/UnPocoTende/media",
                    "https://twitter.com/Trumperizar",
                    "Trumperizar/media",
                ],
                limit_per_handle=2,
            )

            self.assertEqual(service.playwright_strategy.extract.call_count, 2)
            normalized = [call.args[0] for call in service.playwright_strategy.extract.call_args_list]
            self.assertEqual(normalized, ["UnPocoTende", "Trumperizar"])

    def test_manual_mode_does_not_scan_feeds(self) -> None:
        with patch.dict(os.environ, {"X_MODE": "manual"}):
            get_settings.cache_clear()
            service = XExtractionService(get_settings())
            service.playwright_strategy.extract = Mock(return_value=[])
            rows = service.extract(handles=["UnPocoTende"], limit_per_handle=2)
        self.assertEqual(rows, [])
        self.assertEqual(service.playwright_strategy.extract.call_count, 0)

    def test_feed_results_are_sorted_by_tweet_timestamp(self) -> None:
        with patch.dict(os.environ, {"X_MODE": "browser", "DUO_PUBLISH_REQUIRE_SAME_LOCAL_DAY": "0"}):
            get_settings.cache_clear()
            service = XExtractionService(get_settings())
            now_ts = int(datetime.now(timezone.utc).timestamp())
            service.playwright_strategy.extract = Mock(
                return_value=[
                    {
                        "tweet_id": "old",
                        "tweet_url": "https://x.com/test/status/old",
                        "handle": "test",
                        "original_text": "Video viejo",
                        "timestamp": now_ts - 3600,
                        "duration_seconds": 10,
                        "visible_metrics": {},
                        "media": [{"type": "video", "url": "", "thumbnail_url": ""}],
                    },
                    {
                        "tweet_id": "new",
                        "tweet_url": "https://x.com/test/status/new",
                        "handle": "test",
                        "original_text": "Video nuevo",
                        "timestamp": now_ts - 1800,
                        "duration_seconds": 10,
                        "visible_metrics": {},
                        "media": [{"type": "video", "url": "", "thumbnail_url": ""}],
                    },
                ]
            )
            service.ytdlp_strategy.extract = Mock(return_value=[])
            rows = service.extract(handles=["test"], limit_per_handle=2)

        self.assertEqual([row.source_item_id for row in rows], ["new", "old"])
        self.assertTrue(rows[0].created_at)
        self.assertEqual(rows[0].ranking_signals["x_scan_scope"], "configured_handles_media_feed")

    def test_feed_mode_prefers_playwright_before_ytdlp(self) -> None:
        with patch.dict(os.environ, {"X_MODE": "feed", "DUO_PUBLISH_REQUIRE_SAME_LOCAL_DAY": "0"}):
            get_settings.cache_clear()
            service = XExtractionService(get_settings())
            now_ts = int(datetime.now(timezone.utc).timestamp())
            service.playwright_strategy.extract = Mock(
                return_value=[
                    {
                        "tweet_id": "new",
                        "tweet_url": "https://x.com/test/status/new",
                        "handle": "test",
                        "original_text": "Video nuevo",
                        "timestamp": now_ts - 1800,
                        "duration_seconds": 10,
                        "visible_metrics": {},
                        "media": [{"type": "video", "url": "", "thumbnail_url": ""}],
                    }
                ]
            )
            service.ytdlp_strategy.extract = Mock(return_value=[])

            rows = service.extract(handles=["test"], limit_per_handle=2)

        self.assertEqual(len(rows), 1)
        self.assertEqual(service.playwright_strategy.extract.call_count, 1)
        self.assertEqual(service.ytdlp_strategy.extract.call_count, 0)

    def test_service_filters_stale_rows_returned_by_strategy(self) -> None:
        with patch.dict(os.environ, {"X_MODE": "feed", "DUO_PUBLISH_REQUIRE_SAME_LOCAL_DAY": "0"}):
            get_settings.cache_clear()
            service = XExtractionService(get_settings())
            old_ts = int((datetime.now(timezone.utc) - timedelta(days=200)).timestamp())
            recent_ts = int((datetime.now(timezone.utc) - timedelta(hours=2)).timestamp())
            service.playwright_strategy.extract = Mock(
                return_value=[
                    {
                        "tweet_id": "old",
                        "tweet_url": "https://x.com/test/status/old",
                        "handle": "test",
                        "original_text": "Video viejo",
                        "timestamp": old_ts,
                        "duration_seconds": 10,
                        "visible_metrics": {},
                        "media": [{"type": "video", "url": "", "thumbnail_url": ""}],
                    },
                    {
                        "tweet_id": "new",
                        "tweet_url": "https://x.com/test/status/new",
                        "handle": "test",
                        "original_text": "Video nuevo",
                        "timestamp": recent_ts,
                        "duration_seconds": 10,
                        "visible_metrics": {},
                        "media": [{"type": "video", "url": "", "thumbnail_url": ""}],
                    },
                ]
            )
            service.ytdlp_strategy.extract = Mock(return_value=[])

            rows = service.extract(handles=["test"], limit_per_handle=5, max_age_hours=24)

        self.assertEqual([row.source_item_id for row in rows], ["new"])

    def test_home_timeline_uses_actual_author_handle(self) -> None:
        with patch.dict(os.environ, {"X_MODE": "feed"}):
            get_settings.cache_clear()
            service = XExtractionService(get_settings())
            now_ts = int(datetime.now(timezone.utc).timestamp())
            service.playwright_strategy.extract = Mock(
                return_value=[
                    {
                        "tweet_id": "home-1",
                        "tweet_url": "https://x.com/ceciarmy/status/home-1",
                        "handle": "ceciarmy",
                        "original_text": "Video desde home",
                        "timestamp": now_ts - 900,
                        "duration_seconds": 16,
                        "visible_metrics": {},
                        "media": [{"type": "video", "url": "", "thumbnail_url": ""}],
                    }
                ]
            )
            service.ytdlp_strategy.extract = Mock(return_value=[])

            rows = service.extract(handles=["https://x.com/home?lang=es"], limit_per_handle=2)

        self.assertEqual(service.playwright_strategy.extract.call_args.args[0], "home")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].source_handle, "ceciarmy")
        self.assertEqual(rows[0].ranking_signals["x_scan_scope"], "home_timeline")
        self.assertEqual(rows[0].ranking_signals["requested_handle"], "home")


if __name__ == "__main__":
    unittest.main()

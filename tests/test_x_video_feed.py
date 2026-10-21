from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from extractors.x_video_feed import MAX_ATTEMPTS, XVideoFeed, is_valid_x_url, tweet_key

NOW = datetime(2026, 10, 17, 21, 0, tzinfo=timezone.utc)


def _entry(job_id: str, url: str, hours_ago: float) -> dict:
    return {"job_id": job_id, "url": url, "created_at": (NOW - timedelta(hours=hours_ago)).isoformat()}


class XVideoFeedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="duo_xfeed_")
        root = Path(self.tmp.name)
        self.feed_path = root / "x_video_sources.json"
        self.state_path = root / "runtime" / "x_video_feed_state.json"
        self.feed = XVideoFeed(self.feed_path, self.state_path, max_age_hours=24)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_feed(self, entries: list) -> None:
        self.feed_path.write_text(json.dumps(entries), encoding="utf-8")

    def test_missing_or_broken_feed_is_not_an_error(self) -> None:
        self.assertEqual(self.feed.pending_jobs(now=NOW), [])
        self.feed_path.write_text('[{"job_id": "a", "url": ', encoding="utf-8")  # a medio escribir
        self.assertEqual(self.feed.pending_jobs(now=NOW), [])

    def test_oldest_first_with_double_dedupe_and_age_cut(self) -> None:
        # El feed viene del mas nuevo al mas viejo.
        self._write_feed(
            [
                _entry("j4", "https://x.com/b/status/200", 1),
                _entry("j3", "https://twitter.com/a/status/100?s=20", 2),  # mismo tweet que j2
                _entry("j2", "https://x.com/a/status/100", 3),
                _entry("j1", "https://x.com/c/status/50", 30),  # viejo
                _entry("j0", "http://x.com/d/status/1", 1),  # no https
            ]
        )
        self.assertEqual(
            self.feed.pending_jobs(now=NOW),
            [("j2", "https://x.com/a/status/100"), ("j4", "https://x.com/b/status/200")],
        )
        jobs = json.loads(self.state_path.read_text(encoding="utf-8"))["jobs"]
        self.assertEqual(jobs["j3"]["status"], "skipped_duplicate")
        self.assertEqual(jobs["j1"]["status"], "skipped_old")
        self.assertNotIn("j0", jobs)

    def test_feed_file_is_never_written(self) -> None:
        self._write_feed([_entry("j1", "https://x.com/a/status/1", 1)])
        before = self.feed_path.read_bytes()
        self.feed.pending_jobs(now=NOW)
        self.feed.mark("j1", "imported", content_key="k1")
        self.assertEqual(self.feed_path.read_bytes(), before)

    def test_imported_job_is_not_returned_again(self) -> None:
        self._write_feed([_entry("j1", "https://x.com/a/status/1", 1)])
        self.assertEqual(len(self.feed.pending_jobs(now=NOW)), 1)
        self.feed.mark("j1", "imported", content_key="k1")
        self.assertEqual(self.feed.pending_jobs(now=NOW), [])

    def test_failed_job_retries_until_max_attempts(self) -> None:
        self._write_feed([_entry("j1", "https://x.com/a/status/1", 1)])
        for _ in range(MAX_ATTEMPTS - 1):
            self.assertEqual(len(self.feed.pending_jobs(now=NOW)), 1)
            self.feed.mark("j1", "failed", error="sin video")
        self.assertEqual(len(self.feed.pending_jobs(now=NOW)), 1)
        self.feed.mark("j1", "failed", error="sin video")
        self.assertEqual(self.feed.pending_jobs(now=NOW), [])

    def test_url_rules(self) -> None:
        self.assertTrue(is_valid_x_url("https://mobile.twitter.com/a/status/9"))
        self.assertFalse(is_valid_x_url("https://x.com/a"))
        self.assertFalse(is_valid_x_url("https://evil.com/x.com/status/9"))
        self.assertEqual(tweet_key("https://x.com/a/status/123?s=1"), "x:123")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from analytics.service import AnalyticsCollector
from storage.settings import get_settings


class _FakeStore:
    def __init__(self) -> None:
        self.updated_ids = []

    def list_due_analytics_checkpoints(self, now_dt, checkpoint_hours, lookback_hours):
        return [
            {
                "publication_id": 1,
                "platform": "instagram",
                "platform_media_id": "bad-id",
                "platform_post_id": "bad-id",
                "permalink": "https://www.instagram.com/reel/test/",
                "published_at": "2026-04-05T21:20:20+00:00",
                "checkpoint_label": "T1",
                "checkpoint_order": 1,
                "due_at": "2026-04-05T22:20:20+00:00",
                "publication_age_minutes": 60,
            }
        ]

    def save_analytics_snapshot(self, *args, **kwargs):
        raise AssertionError("should not save snapshot when metrics are unavailable")

    def update_publication_media_id(self, publication_id: int, media_id: str) -> None:
        self.updated_ids.append((publication_id, media_id))


class _FailingPublisher:
    def collect_instagram_metrics(self, media_id: str, *, permalink: str = "", published_at: str = ""):
        return {
            "details": {},
            "insights": {},
            "meta": {"requested_media_id": media_id, "resolved_media_id": media_id},
            "errors": {"details": "unsupported"},
        }


class _UnavailableMetricsStore:
    def __init__(self) -> None:
        self.saved_snapshots = []

    def list_due_analytics_checkpoints(self, now_dt, checkpoint_hours, lookback_hours):
        return [
            {
                "publication_id": 2,
                "platform": "instagram",
                "platform_media_id": "missing-id",
                "platform_post_id": "missing-id",
                "permalink": "https://www.instagram.com/p/test/",
                "published_at": "2026-04-05T21:20:20+00:00",
                "checkpoint_label": "T1",
                "checkpoint_order": 1,
                "due_at": "2026-04-05T22:20:20+00:00",
                "publication_age_minutes": 60,
            }
        ]

    def save_analytics_snapshot(self, publication_id, metrics, **kwargs):
        self.saved_snapshots.append((publication_id, metrics, kwargs))

    def analytics_scores(self, checkpoint_label):
        return []

    def update_publication_media_id(self, publication_id: int, media_id: str) -> None:
        return None


class _UnavailablePublisher:
    def collect_instagram_metrics(self, media_id: str, *, permalink: str = "", published_at: str = ""):
        return {
            "details": {},
            "insights": {},
            "meta": {"requested_media_id": media_id, "resolved_media_id": media_id},
            "errors": {
                "details": "{'error': {'message': \"Unsupported get request. Object with ID 'missing-id' does not exist\", 'error_subcode': 33}}"
            },
        }


class AnalyticsServiceTests(unittest.TestCase):
    def test_skips_unavailable_instagram_metrics_without_crashing(self) -> None:
        store = _FakeStore()
        collector = AnalyticsCollector(store, _FailingPublisher(), get_settings())
        snapshots = collector.collect_due_snapshots()
        self.assertEqual(snapshots, [])
        self.assertEqual(store.updated_ids, [])

    def test_marks_terminal_instagram_unavailable_checkpoint_once(self) -> None:
        store = _UnavailableMetricsStore()
        collector = AnalyticsCollector(store, _UnavailablePublisher(), get_settings())

        snapshots = collector.collect_due_snapshots()

        self.assertEqual(snapshots, [])
        self.assertEqual(len(store.saved_snapshots), 1)
        publication_id, metrics, kwargs = store.saved_snapshots[0]
        self.assertEqual(publication_id, 2)
        self.assertEqual((metrics.get("meta") or {}).get("analytics_status"), "unavailable")
        self.assertEqual(kwargs["checkpoint_label"], "T1")
        self.assertEqual(kwargs["performance_score"], 0.0)


if __name__ == "__main__":
    unittest.main()

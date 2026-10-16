from __future__ import annotations

import json
import os
import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from jobs.scheduler import PeakScheduler, SlotCandidate
from storage.settings import get_settings


class PeakSchedulerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {
                "DUO_SCHEDULE_SLOTS": "09:00,12:00,15:00,18:00,21:00",
                "DUO_SCHEDULE_VIDEOS_PER_SLOT": "3",
                "DUO_SCHEDULE_POSTS_PER_SLOT": "5",
                "DUO_PUBLISH_REQUIRE_SAME_LOCAL_DAY": "true",
            },
            clear=False,
        )
        self.env.start()
        get_settings.cache_clear()

    def tearDown(self) -> None:
        self.env.stop()
        get_settings.cache_clear()

    def test_assigns_high_score_to_peak_slot_bucket(self) -> None:
        scheduler = PeakScheduler(get_settings())
        scheduler.next_slots = lambda count: self._fixed_slots(scheduler)[:count]  # type: ignore[method-assign]
        rows = [
            {"content_key": "a", "title": "Tema A", "score_json": json.dumps({"total": 90, "theme": "politica"}), "source_handle": "uno", "formatted_json": json.dumps({"post_type": "reel"})},
            {"content_key": "b", "title": "Tema B", "score_json": json.dumps({"total": 66, "theme": "actualidad"}), "source_handle": "dos", "formatted_json": json.dumps({"post_type": "image"})},
            {"content_key": "c", "title": "Tema C", "score_json": json.dumps({"total": 40, "theme": "tendencia"}), "source_handle": "tres", "formatted_json": json.dumps({"post_type": "carousel"})},
        ]
        decisions = scheduler.assign(rows)
        self.assertEqual(decisions["a"].slot_bucket, "alto")
        self.assertIn(decisions["a"].slot_label, {"18:00", "21:00", "00:00"})
        self.assertEqual(decisions["b"].slot_bucket, "medio")
        self.assertIn(decisions["b"].slot_label, {"12:00", "15:00"})
        self.assertEqual(decisions["c"].slot_bucket, "experimental")
        self.assertEqual(decisions["c"].slot_label, "09:00")

    def test_avoids_repeating_source_when_possible(self) -> None:
        scheduler = PeakScheduler(get_settings())
        scheduler.next_slots = lambda count: self._fixed_slots(scheduler)[:count]  # type: ignore[method-assign]
        rows = [
            {"content_key": "a", "title": "Tema A", "score_json": json.dumps({"total": 90, "theme": "politica"}), "source_handle": "repetida", "formatted_json": json.dumps({"post_type": "reel"})},
            {"content_key": "b", "title": "Tema B", "score_json": json.dumps({"total": 88, "theme": "deportes"}), "source_handle": "nueva", "formatted_json": json.dumps({"post_type": "reel"})},
        ]
        history = [{"title": "Tema previo", "score_theme": "politica", "source_handle": "repetida", "assigned_post_type": "reel"}]
        decisions = scheduler.assign(rows, recent_context=history)
        first_choice = min(decisions.items(), key=lambda item: item[1].priority_rank)[0]
        self.assertEqual(first_choice, "b")

    def test_prioritizes_salta_source_over_similar_national_post(self) -> None:
        scheduler = PeakScheduler(get_settings())
        scheduler.next_slots = lambda count: self._fixed_slots(scheduler)[:count]  # type: ignore[method-assign]
        rows = [
            {
                "content_key": "nacional",
                "source": "tn",
                "title": "El Gobierno anuncio una medida nacional",
                "score_json": json.dumps({"total": 65, "theme": "politica"}),
                "formatted_json": json.dumps({"post_type": "image"}),
            },
            {
                "content_key": "salta",
                "source": "eltribuno",
                "title": "Salta anuncio una medida local",
                "score_json": json.dumps({"total": 58, "theme": "politica"}),
                "formatted_json": json.dumps({"post_type": "image"}),
            },
        ]

        decisions = scheduler.assign(rows)
        first_choice = min(decisions.items(), key=lambda item: item[1].priority_rank)[0]

        self.assertEqual(first_choice, "salta")
        self.assertIn("prioridad_salta", decisions["salta"].reason)

    def test_respects_video_and_post_capacity_per_slot(self) -> None:
        scheduler = PeakScheduler(get_settings())
        scheduler.next_slots = lambda count: self._fixed_slots(scheduler)[:count]  # type: ignore[method-assign]
        rows = [
            {
                "content_key": f"video-{index}",
                "title": f"Video {index}",
                "score_json": json.dumps({"total": 40, "theme": "tendencia"}),
                "source_handle": f"v{index}",
                "formatted_json": json.dumps({"post_type": "reel"}),
            }
            for index in range(4)
        ]
        rows.extend(
            {
                "content_key": f"post-{index}",
                "title": f"Post {index}",
                "score_json": json.dumps({"total": 40, "theme": "tendencia"}),
                "source_handle": f"p{index}",
                "formatted_json": json.dumps({"post_type": "image"}),
            }
            for index in range(6)
        )

        decisions = scheduler.assign(rows)
        by_slot: dict[str, list[str]] = {}
        for key, decision in decisions.items():
            by_slot.setdefault(decision.scheduled_for, []).append(key)

        first_slot = min(by_slot)
        first_keys = by_slot[first_slot]
        self.assertEqual(sum(1 for key in first_keys if key.startswith("video-")), 3)
        self.assertEqual(sum(1 for key in first_keys if key.startswith("post-")), 5)
        self.assertEqual(len(first_keys), 8)
        self.assertEqual(len(decisions), 10)

    def test_existing_future_schedule_reduces_available_capacity(self) -> None:
        scheduler = PeakScheduler(get_settings())
        fixed_slots = self._fixed_slots(scheduler)
        scheduler.next_slots = lambda count: fixed_slots[:count]  # type: ignore[method-assign]
        first_slot_key = fixed_slots[0].scheduled_for.astimezone(ZoneInfo("UTC")).replace(microsecond=0).isoformat()
        rows = [
            {
                "content_key": f"video-{index}",
                "title": f"Video {index}",
                "score_json": json.dumps({"total": 40, "theme": "tendencia"}),
                "source_handle": f"v{index}",
                "formatted_json": json.dumps({"post_type": "reel"}),
            }
            for index in range(2)
        ]
        existing = [
            {"content_key": "existing-a", "assigned_time": first_slot_key, "assigned_post_type": "reel"},
            {"content_key": "existing-b", "assigned_time": first_slot_key, "assigned_post_type": "reel"},
        ]

        decisions = scheduler.assign(rows, existing_context=existing)
        first_slot_videos = [
            key
            for key, decision in decisions.items()
            if decision.scheduled_for == first_slot_key and key.startswith("video-")
        ]
        self.assertEqual(len(first_slot_videos), 1)

    def test_same_day_policy_does_not_schedule_after_last_slot(self) -> None:
        scheduler = PeakScheduler(get_settings())

        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):  # type: ignore[override]
                return datetime(2026, 4, 7, 22, 0, tzinfo=tz)

        with patch("jobs.scheduler.datetime", FixedDateTime):
            self.assertEqual(scheduler.next_slots(3), [])

    def test_same_day_policy_keeps_current_slot_open_within_window(self) -> None:
        scheduler = PeakScheduler(get_settings())

        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):  # type: ignore[override]
                return datetime(2026, 4, 7, 21, 0, tzinfo=tz)

        with patch("jobs.scheduler.datetime", FixedDateTime):
            slots = scheduler.next_slots(3)

        self.assertTrue(slots)
        self.assertEqual(slots[0].slot_label, "21:00")

    @staticmethod
    def _fixed_slots(scheduler: PeakScheduler) -> list[SlotCandidate]:
        zone = ZoneInfo(scheduler.settings.timezone)
        labels = ("09:00", "12:00", "15:00", "18:00", "21:00")
        slots: list[SlotCandidate] = []
        for day in (7, 8):
            for label in labels:
                hour, minute = (int(part) for part in label.split(":", 1))
                slots.append(
                    SlotCandidate(
                        slot_label=label,
                        scheduled_for=datetime(2026, 4, day, hour, minute, tzinfo=zone),
                        slot_bucket=scheduler._slot_bucket(label),
                    )
                )
        return slots


if __name__ == "__main__":
    unittest.main()

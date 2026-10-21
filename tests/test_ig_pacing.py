"""Ritmo de noticias en Instagram: tope fijo por hora local (cupo de 24 h moviles)."""
from __future__ import annotations

import dataclasses
import logging
import unittest
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from jobs.pipeline import DuoPipeline
from storage.editorial_config import load_editorial_config
from storage.settings import get_settings

ZONE = ZoneInfo("America/Buenos_Aires")


# Ritmo parejo (1 de noche, 3 de dia); la configuracion viva puede estar en modo prueba.
PACED = {"ig_news_per_hour_night": 1, "ig_news_per_hour_day": 3, "ig_news_peak_hours": (), "ig_quota_probe": False, "ig_feed_per_day": 0}


def pipeline_with_remaining(remaining: int, **overrides) -> DuoPipeline:
    get_settings.cache_clear()
    settings = get_settings()
    pipeline = DuoPipeline.__new__(DuoPipeline)
    pipeline.config = dataclasses.replace(load_editorial_config(settings), **{**PACED, **overrides})
    pipeline.settings = SimpleNamespace(enable_instagram=True)
    pipeline.zone = ZONE
    pipeline.logger = logging.getLogger("test")
    pipeline.publisher = SimpleNamespace(get_ig_publish_limit=lambda: {"remaining": remaining})
    return pipeline


class IgPacingTests(unittest.TestCase):
    def test_hourly_profile(self) -> None:
        config = dataclasses.replace(load_editorial_config(get_settings()), **PACED)
        self.assertEqual(config.news_cap_for_hour(3), 1)
        self.assertEqual(config.news_cap_for_hour(14), 3)
        self.assertEqual(config.news_cap_for_hour(0), 3)
        daily = sum(config.news_cap_for_hour(h) for h in range(24))
        self.assertLessEqual(daily + config.ig_reserve_for_formats, 100)

    def test_full_quota_at_night_does_not_burn_the_window(self) -> None:
        pipeline = pipeline_with_remaining(100)
        self.assertEqual(pipeline._capacity_left(datetime(2026, 10, 20, 2, 0, tzinfo=ZONE), True), 1)
        self.assertEqual(pipeline._capacity_left(datetime(2026, 10, 20, 21, 0, tzinfo=ZONE), True), 3)

    def test_probe_mode_ignores_remaining_quota(self) -> None:
        # Prueba del limite (pedida por el propietario): 10 por ciclo aunque la API diga que no queda cupo.
        pipeline = pipeline_with_remaining(0, ig_quota_probe=True, ig_news_per_hour_night=10, ig_news_per_hour_day=10)
        self.assertEqual(pipeline._capacity_left(datetime(2026, 10, 20, 3, 0, tzinfo=ZONE), True), 10)
        self.assertEqual(pipeline._capacity_left(datetime(2026, 10, 20, 15, 0, tzinfo=ZONE), True), 10)

    def test_reserve_for_formats_still_applies(self) -> None:
        self.assertEqual(pipeline_with_remaining(17)._capacity_left(datetime(2026, 10, 20, 15, 0, tzinfo=ZONE), True), 2)
        self.assertEqual(pipeline_with_remaining(10)._capacity_left(datetime(2026, 10, 20, 15, 0, tzinfo=ZONE), True), 0)

    def test_peak_hours(self) -> None:
        config = dataclasses.replace(load_editorial_config(get_settings()), **{**PACED, "ig_news_peak_hours": (21,), "ig_news_per_hour_peak": 2, "ig_news_per_hour_night": 0})
        self.assertEqual(config.news_cap_for_hour(21), 2)
        self.assertEqual(config.news_cap_for_hour(15), 3)
        self.assertEqual(config.news_cap_for_hour(3), 0)

    def test_split_feed_does_not_cap_facebook(self) -> None:
        # Con feed de IG separado, el cupo de Instagram no limita cuantas notas salen (en Facebook).
        pipeline = pipeline_with_remaining(0, ig_feed_per_day=20)
        self.assertIsNone(pipeline._capacity_left(datetime(2026, 10, 20, 15, 0, tzinfo=ZONE), True))


if __name__ == "__main__":
    unittest.main()

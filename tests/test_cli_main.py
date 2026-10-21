from __future__ import annotations

import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from cli import main as cli_main

ZONE = ZoneInfo("America/Buenos_Aires")


class DummyPipeline:
    def __init__(self, align_minute: int = 0) -> None:
        self.settings = SimpleNamespace(timezone="America/Buenos_Aires")
        self.config = SimpleNamespace(align_minute=align_minute)


class FrozenDatetime(datetime):
    frozen = datetime(2026, 10, 17, 14, 20, 0, tzinfo=ZONE)

    @classmethod
    def now(cls, tz=None):
        return cls.frozen.astimezone(tz) if tz else cls.frozen


class CliLoopTimingTests(unittest.TestCase):
    def test_next_cycle_is_next_top_of_the_hour(self) -> None:
        with patch.object(cli_main, "datetime", FrozenDatetime):
            wait = cli_main._seconds_until_next_cycle(DummyPipeline())
        self.assertAlmostEqual(wait, 40 * 60 + 5, delta=1)

    def test_next_cycle_respects_configured_minute(self) -> None:
        with patch.object(cli_main, "datetime", FrozenDatetime):
            wait = cli_main._seconds_until_next_cycle(DummyPipeline(align_minute=30))
        self.assertAlmostEqual(wait, 10 * 60 + 5, delta=1)

    def test_cycle_id_is_hourly_and_local(self) -> None:
        from jobs.pipeline import cycle_id_for

        self.assertEqual(cycle_id_for(datetime(2026, 10, 17, 17, 59, tzinfo=ZoneInfo("UTC")), ZONE), "2026-10-17T14")
        self.assertEqual(cycle_id_for(datetime(2026, 10, 17, 18, 0, tzinfo=ZoneInfo("UTC")), ZONE), "2026-10-17T15")


if __name__ == "__main__":
    unittest.main()

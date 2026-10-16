from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from cli import main as cli_main


class DummyPipeline:
    def __init__(self, *, active_slot: str | None = None) -> None:
        self.settings = SimpleNamespace(
            schedule_slots=("09:00", "12:00", "15:00", "18:00", "21:00"),
            timezone="America/Buenos_Aires",
        )
        self._slot = active_slot

    def _active_schedule_slot(self) -> str | None:
        return self._slot


class CliLoopTimingTests(unittest.TestCase):
    def test_initial_cycle_waits_for_next_slot_in_live_mode(self) -> None:
        pipeline = DummyPipeline(active_slot=None)
        with patch("cli.main._seconds_until_next_slot", return_value=7200):
            self.assertEqual(
                cli_main._seconds_until_initial_cycle(
                    pipeline,
                    3600,
                    align_to_slots=True,
                ),
                7200,
            )

    def test_initial_cycle_starts_immediately_when_slot_is_active(self) -> None:
        pipeline = DummyPipeline(active_slot="09:00")
        with patch("cli.main._seconds_until_next_slot", return_value=7200):
            self.assertEqual(
                cli_main._seconds_until_initial_cycle(
                    pipeline,
                    3600,
                    align_to_slots=True,
                ),
                0.0,
            )

    def test_next_cycle_follows_slot_in_live_mode(self) -> None:
        pipeline = DummyPipeline(active_slot=None)
        with patch("cli.main._seconds_until_next_slot", return_value=7200):
            self.assertEqual(
                cli_main._seconds_until_next_cycle(
                    pipeline,
                    3600,
                    align_to_slots=True,
                ),
                7200,
            )

    def test_next_cycle_uses_interval_outside_live_mode(self) -> None:
        pipeline = DummyPipeline(active_slot=None)
        with patch("cli.main._seconds_until_next_slot", return_value=7200):
            self.assertEqual(
                cli_main._seconds_until_next_cycle(
                    pipeline,
                    3600,
                    align_to_slots=False,
                ),
                3600,
            )

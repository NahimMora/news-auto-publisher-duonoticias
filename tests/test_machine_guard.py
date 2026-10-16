from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from storage.settings import get_settings
from utils.machine_guard import assert_production_machine, is_production_machine


class MachineGuardTests(unittest.TestCase):
    def tearDown(self) -> None:
        get_settings.cache_clear()

    def test_only_fernando_is_production(self) -> None:
        with patch.dict(os.environ, {"COMPUTERNAME": "fernando"}, clear=False):
            self.assertTrue(is_production_machine())
        with patch.dict(os.environ, {"COMPUTERNAME": "OTRA-PC"}, clear=False):
            self.assertFalse(is_production_machine())
            with self.assertRaises(RuntimeError):
                assert_production_machine()

    def test_live_publish_flag_is_ignored_outside_production(self) -> None:
        with patch.dict(os.environ, {"COMPUTERNAME": "OTRA-PC", "DUO_LIVE_PUBLISH_ENABLED": "1"}, clear=False):
            get_settings.cache_clear()
            settings = get_settings()
        self.assertFalse(settings.live_publish_enabled)
        self.assertFalse(settings.production_machine)

    def test_live_publish_needs_flag_and_production(self) -> None:
        with patch.dict(os.environ, {"COMPUTERNAME": "FERNANDO", "DUO_LIVE_PUBLISH_ENABLED": "1"}, clear=False):
            get_settings.cache_clear()
            self.assertTrue(get_settings().live_publish_enabled)
        with patch.dict(os.environ, {"COMPUTERNAME": "FERNANDO", "DUO_LIVE_PUBLISH_ENABLED": "0"}, clear=False):
            get_settings.cache_clear()
            self.assertFalse(get_settings().live_publish_enabled)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli import main as cli_main
from jobs.pipeline import DuoPipeline
from storage.settings import get_settings

READY_ENV = {
    "COMPUTERNAME": "FERNANDO",
    "DUO_LIVE_PUBLISH_ENABLED": "true",
    "GEMINI_API_KEY": "gm-test",
    "LLM_PROVIDER": "gemini",
    "ENABLE_INSTAGRAM": "false",
    "ENABLE_FACEBOOK": "false",
    "ENABLE_DUO_WEB": "true",
    "DUO_WEB_MODE": "admin",
    "DUO_WEB_URL": "http://web.local",
    "DUO_WEB_TOKEN": "admin-key",
}


class PreflightTests(unittest.TestCase):
    def tearDown(self) -> None:
        get_settings.cache_clear()

    def _preflight(self, env: dict[str, str]) -> dict:
        with tempfile.TemporaryDirectory(prefix="duo_preflight_") as tmp_dir:
            env = {"DUO_DB_PATH": str(Path(tmp_dir) / "duo.sqlite3"), "SQLITE_PATH": "", **env}
            with patch.dict(os.environ, env, clear=False), patch.object(cli_main, "_internet_check", return_value="ok"):
                get_settings.cache_clear()
                return cli_main._preflight(DuoPipeline(get_settings()))

    def test_ready_profile_passes(self) -> None:
        result = self._preflight(READY_ENV)
        self.assertTrue(result["ok"], result["critical"])
        self.assertEqual(result["platforms"], {"duo_web": "ready"})

    def test_other_machine_is_blocked(self) -> None:
        result = self._preflight({**READY_ENV, "COMPUTERNAME": "OTRA-PC"})
        self.assertFalse(result["ok"])
        self.assertIn("not_production_machine", result["critical"])

    def test_missing_credentials_and_llm_key_are_critical(self) -> None:
        result = self._preflight(
            {**READY_ENV, "GEMINI_API_KEY": "", "ENABLE_FACEBOOK": "true", "META_ACCESS_TOKEN": "", "META_PAGE_ID": "", "FB_ACCESS_TOKEN": "", "FB_PAGE_ID": ""}
        )
        self.assertFalse(result["ok"])
        self.assertIn("GEMINI_API_KEY_missing", result["critical"])
        self.assertIn("facebook_missing_credentials", result["critical"])

    def test_no_platform_is_critical(self) -> None:
        result = self._preflight({**READY_ENV, "ENABLE_DUO_WEB": "false"})
        self.assertIn("no_enabled_publish_platforms", result["critical"])

    def test_output_has_no_secret_values(self) -> None:
        result = self._preflight(READY_ENV)
        self.assertNotIn("admin-key", repr(result))
        self.assertNotIn("gm-test", repr(result))


if __name__ == "__main__":
    unittest.main()

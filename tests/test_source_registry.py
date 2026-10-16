from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from extractors.registry import SourceRegistry
from storage.settings import get_settings


class SourceRegistryTests(unittest.TestCase):
    def tearDown(self) -> None:
        get_settings.cache_clear()

    def test_scan_source_uses_configured_max_items_when_not_provided(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DUO_SCRAPE_DEFAULT_MAX_ITEMS_PER_SOURCE": "10",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            registry = SourceRegistry(get_settings())
            with patch("extractors.registry.RssHtmlNewsExtractor.scan", return_value=[]) as mocked:
                registry.scan_source("tn")

        self.assertEqual(mocked.call_args.kwargs["max_items"], 10)

    def test_settings_load_x_handles_from_sources_yaml_when_env_is_missing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="duo_sources_") as tmp_dir:
            config_path = Path(tmp_dir) / "sources.yaml"
            config_path.write_text(
                "\n".join(
                    [
                        "sources:",
                        "  - name: x",
                        "    enabled: true",
                        "    handles:",
                        "      - https://x.com/TTendenciaX",
                        "      - https://x.com/home?lang=es",
                        "      - https://x.com/ceciarmy",
                    ]
                ),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {
                    "DUO_SOURCES_CONFIG": str(config_path),
                    "X_SOURCES": "",
                },
                clear=False,
            ):
                get_settings.cache_clear()
                settings = get_settings()

        self.assertEqual(settings.x_sources, ("TTendenciaX", "home", "ceciarmy"))


if __name__ == "__main__":
    unittest.main()

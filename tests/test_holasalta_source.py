from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from extractors.holasalta.extractor import HolaSaltaExtractor
from extractors.holasalta.keys import tweet_id_from_url
from extractors.registry import SourceRegistry
from storage.models import ExtractedContent
from storage.settings import get_settings
from storage.sqlite_store import PipelineStore


class FakeHolaSalta:
    def __init__(self, news=None, jobs=None) -> None:
        self.news = news or []
        self.jobs = jobs or []

    def get_news(self):
        return self.news

    def get_video_jobs(self):
        return self.jobs


NEWS = [
    {
        "id": 7,
        "titulo": "Corte de agua en Salta capital",
        "url": "https://www.eltribuno.com/salta/nota/corte-agua?utm=x",
        "web_url": "https://holasalta.com/corte-agua",
        "extracto": "Aguas del Norte anuncio cortes programados.",
        "parrafos": ["Aguas del Norte informo que el martes habra cortes programados en zona norte."],
        "imagen_optimizada": "https://holasalta.com/img/corte.webp",
    },
    {"id": 8, "titulo": "Sin url de origen", "url_wordpress": "https://holasalta.com/sin-origen"},
]


def _sources_yaml(tmp_dir: str, *, enabled: bool, include_jobs: bool) -> Path:
    path = Path(tmp_dir) / "sources.yaml"
    path.write_text(
        "\n".join(
            [
                "sources:",
                "  - name: holasalta",
                f"    enabled: {'true' if enabled else 'false'}",
                "    category: salta",
                "    max_items_per_scan: 5",
                f"    include_x_video_jobs: {'true' if include_jobs else 'false'}",
            ]
        ),
        encoding="utf-8",
    )
    return path


class HolaSaltaExtractorTests(unittest.TestCase):
    def tearDown(self) -> None:
        get_settings.cache_clear()

    def test_news_become_pipeline_content(self) -> None:
        rows = HolaSaltaExtractor(get_settings(), client=FakeHolaSalta(news=NEWS)).scan(max_items=5)

        self.assertEqual(len(rows), 2)
        first = rows[0]
        self.assertIsInstance(first, ExtractedContent)
        self.assertEqual((first.source, first.source_type, first.source_item_id), ("holasalta", "news", "7"))
        # Canonical URL is the original source, so direct scrapes of El Tribuno dedupe against it.
        self.assertEqual(first.canonical_url, "https://www.eltribuno.com/salta/nota/corte-agua")
        self.assertIn("salta", first.tags)
        self.assertEqual(first.assets[0].remote_url, "https://holasalta.com/img/corte.webp")
        self.assertEqual(rows[1].canonical_url, "https://holasalta.com/sin-origen")

    def test_scan_respects_max_items(self) -> None:
        rows = HolaSaltaExtractor(get_settings(), client=FakeHolaSalta(news=NEWS)).scan(max_items=1)
        self.assertEqual(len(rows), 1)

    def test_video_urls_are_normalized_deduped_and_limited(self) -> None:
        jobs = [
            {"source_url": "HTTPS://X.COM/a/status/1/?b=2&a=1"},
            {"source_url": "https://x.com/a/status/1?a=1&b=2"},
            {"source_url": "https://x.com/b/status/2"},
            {"source_url": "https://x.com/c/status/3"},
        ]
        urls = HolaSaltaExtractor(get_settings(), client=FakeHolaSalta(jobs=jobs)).video_urls(max_items=2)
        self.assertEqual(urls, ["https://x.com/a/status/1?a=1&b=2", "https://x.com/b/status/2"])

    def test_missing_password_fails_without_network(self) -> None:
        with patch.dict(os.environ, {"HS_API_PASSWORD": ""}, clear=False):
            get_settings.cache_clear()
            with self.assertRaises(ValueError):
                HolaSaltaExtractor(get_settings()).scan(max_items=1)

    def test_tweet_id_from_url(self) -> None:
        self.assertEqual(tweet_id_from_url("https://x.com/a/status/123?s=20"), "123")
        self.assertEqual(tweet_id_from_url("https://x.com/a"), "")


class HolaSaltaRegistryTests(unittest.TestCase):
    def tearDown(self) -> None:
        get_settings.cache_clear()

    def _registry(self, tmp_dir: str, *, enabled: bool, include_jobs: bool) -> SourceRegistry:
        path = _sources_yaml(tmp_dir, enabled=enabled, include_jobs=include_jobs)
        with patch.dict(os.environ, {"DUO_SOURCES_CONFIG": str(path)}, clear=False):
            get_settings.cache_clear()
            return SourceRegistry(get_settings())

    def test_disabled_source_is_not_scanned(self) -> None:
        with tempfile.TemporaryDirectory(prefix="duo_hs_") as tmp_dir:
            registry = self._registry(tmp_dir, enabled=False, include_jobs=True)
            with patch.object(HolaSaltaExtractor, "scan") as scan, patch.object(HolaSaltaExtractor, "video_urls") as videos:
                self.assertEqual(registry.scan_source("holasalta"), [])
                self.assertEqual(registry.holasalta_video_urls(), [])
            scan.assert_not_called()
            videos.assert_not_called()
            self.assertNotIn("holasalta", registry.enabled_source_names())

    def test_enabled_source_uses_config_limits(self) -> None:
        with tempfile.TemporaryDirectory(prefix="duo_hs_") as tmp_dir:
            registry = self._registry(tmp_dir, enabled=True, include_jobs=False)
            with patch.object(HolaSaltaExtractor, "scan", return_value=[]) as scan, patch.object(HolaSaltaExtractor, "video_urls") as videos:
                registry.scan_source("holasalta")
                self.assertEqual(registry.holasalta_video_urls(), [])
            self.assertEqual(scan.call_args.kwargs, {"max_items": 5, "category": "salta"})
            videos.assert_not_called()
            self.assertIn("holasalta", registry.enabled_source_names())

    def test_video_jobs_require_opt_in(self) -> None:
        with tempfile.TemporaryDirectory(prefix="duo_hs_") as tmp_dir:
            registry = self._registry(tmp_dir, enabled=True, include_jobs=True)
            with patch.object(HolaSaltaExtractor, "video_urls", return_value=["https://x.com/a/status/1"]):
                self.assertEqual(registry.holasalta_video_urls(), ["https://x.com/a/status/1"])


class HasSourceItemTests(unittest.TestCase):
    def tearDown(self) -> None:
        get_settings.cache_clear()

    def test_has_source_item(self) -> None:
        with tempfile.TemporaryDirectory(prefix="duo_hs_store_") as tmp_dir:
            with patch.dict(os.environ, {"DUO_DB_PATH": str(Path(tmp_dir) / "duo.sqlite3"), "SQLITE_PATH": ""}, clear=False):
                get_settings.cache_clear()
                store = PipelineStore(get_settings())
                store.upsert_content(
                    ExtractedContent(source="x", source_type="x_video", source_item_id="123", canonical_url="https://x.com/a/status/123")
                )
                self.assertTrue(store.has_source_item("x", "123"))
                self.assertFalse(store.has_source_item("x", "999"))
                self.assertFalse(store.has_source_item("x", ""))


if __name__ == "__main__":
    unittest.main()

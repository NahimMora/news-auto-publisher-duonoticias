from __future__ import annotations

import unittest
from unittest.mock import patch

from extractors.registry import SourceRegistry
from storage.settings import get_settings

ACTIVE = {"eltribuno", "informatesalta", "quepasasalta", "gobiernosalta", "policiasalta", "municipalidadsalta", "paparazzi", "tn", "infobae"}
REMOVED = {"nuevodiariodesalta", "fiscalespenalesalta", "justiciasalta", "noticiasargentinas", "minutouno", "elonce", "ambitofinanciero", "ariesonline", "eloncesalta"}


class SourceRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        get_settings.cache_clear()
        self.registry = SourceRegistry(get_settings())

    def test_only_active_sources_are_scanned(self) -> None:
        names = set(self.registry.enabled_source_names())
        self.assertEqual(names, ACTIVE)
        self.assertFalse(names & REMOVED)
        self.assertNotIn("x", names)  # los videos de X llegan solo por el intercambio de HolaSalta

    def test_removed_sources_return_nothing(self) -> None:
        for source in REMOVED | {"x"}:
            self.assertEqual(self.registry.scan_source(source), [], source)

    def test_groups_and_video_rules(self) -> None:
        config = self.registry.config
        self.assertEqual({s for s in ACTIVE if config.group_of(s) == "local"}, {"eltribuno", "informatesalta", "quepasasalta", "gobiernosalta", "policiasalta", "municipalidadsalta"})
        self.assertEqual(config.group_of("tn"), config.group_of("infobae"))
        self.assertEqual(config.group_of("tn"), "national")
        for source in ("tn", "infobae", "paparazzi"):
            self.assertTrue(config.requires_video(source), source)
        self.assertTrue(config.is_official("policiasalta"))
        self.assertGreater(config.threshold_for("gobiernosalta"), config.threshold_for("eltribuno"))

    def test_known_urls_are_passed_to_extractors(self) -> None:
        known = lambda url: True  # noqa: E731
        with patch("extractors.registry.ElTribunoExtractor.scan", return_value=[]) as scan:
            self.registry.scan_source("eltribuno", known=known)
        self.assertIs(scan.call_args.kwargs["known"], known)
        self.assertEqual(scan.call_args.kwargs["max_items"], 15)


if __name__ == "__main__":
    unittest.main()

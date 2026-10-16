from __future__ import annotations

import unittest

from utils.video_processor import _build_filter_graph


class VideoProcessorTests(unittest.TestCase):
    def test_filter_graph_without_template_uses_fullscreen_reel_layout(self) -> None:
        graph = _build_filter_graph(None, None, None)
        self.assertIn("scale=1080:1920", graph)
        self.assertIn("setsar=1[vout]", graph)
        self.assertNotIn("scale=1080:1350", graph)
        self.assertNotIn("with_layout", graph)

    def test_filter_graph_with_template_preserves_legacy_card_layout(self) -> None:
        graph = _build_filter_graph(1, None, None)
        self.assertIn("scale=1080:1350", graph)
        self.assertIn("with_layout", graph)
        self.assertIn("setsar=1[vout]", graph)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from analytics.normalization import normalize_metrics


class AnalyticsNormalizationTests(unittest.TestCase):
    def test_facebook_normalization_uses_likes_summary_when_reactions_missing(self) -> None:
        normalized = normalize_metrics(
            {
                "likes": {"summary": {"total_count": 12}},
                "comments": {"summary": {"total_count": 3}},
            },
            "facebook",
        )

        self.assertEqual(normalized["likes"], 12.0)
        self.assertEqual(normalized["comments"], 3.0)


if __name__ == "__main__":
    unittest.main()

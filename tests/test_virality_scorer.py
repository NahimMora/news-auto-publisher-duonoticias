from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from scoring.virality import ViralityScorer
from storage.settings import get_settings


class ViralityScorerTests(unittest.TestCase):
    def tearDown(self) -> None:
        get_settings.cache_clear()

    def test_scores_conflictive_video_higher_than_flat_note(self) -> None:
        scorer = ViralityScorer()
        hot = scorer.score_item(
            {
                "title": "Video viral: robo, pelea y furia en plena calle",
                "summary": "Un clip corto que desató indignación y debate.",
                "body_text": "",
                "media_type": "video",
                "visible_metrics_json": '{"views": 120000, "likes": 8500, "comments": 900, "shares": 600}',
                "ranking_signals_json": '{"duration_seconds": 22}',
                "source": "x",
                "dedupe_status": "accepted",
            }
        )
        flat = scorer.score_item(
            {
                "title": "Parte oficial sobre actividad institucional",
                "summary": "Resumen de agenda sin conflicto visible.",
                "body_text": "",
                "media_type": "image",
                "visible_metrics_json": '{"views": 0, "likes": 0, "comments": 0, "shares": 0}',
                "ranking_signals_json": '{"duration_seconds": 0}',
                "source": "paparazzi",
                "dedupe_status": "accepted",
            }
        )
        self.assertGreater(hot.total, flat.total)
        self.assertTrue(hot.publish)
        self.assertIn("views_score", hot.source_scores)
        self.assertIn("celebrity_recognition", flat.source_scores)

    def test_curated_news_post_can_publish_from_manual_review_floor(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DUO_SCORE_THRESHOLD": "62",
                "DUO_SCORE_KEEP_FLOOR": "52",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            scorer = ViralityScorer(get_settings())
            score = scorer.score_item(
                {
                    "title": "Video: la llegada de Pequeño J al país para ser indagado por el triple crimen y las pruebas en su contra",
                    "summary": "Infobae mostró el arribo y las pruebas en su contra con fuerte impacto.",
                    "body_text": "",
                    "media_type": "image",
                    "visible_metrics_json": '{"views": 0, "likes": 0, "comments": 0, "shares": 0}',
                    "ranking_signals_json": '{"duration_seconds": 0}',
                    "source": "infobae",
                    "dedupe_status": "accepted",
                }
            )

        self.assertGreaterEqual(score.total, 52.0)
        self.assertTrue(score.publish)

    def test_salta_news_source_gets_local_priority_bonus(self) -> None:
        with patch.dict(os.environ, {"DUO_SALTA_PRIORITY_BONUS": "12"}, clear=False):
            get_settings.cache_clear()
            scorer = ViralityScorer(get_settings())
            base_row = {
                "title": "El Gobierno anuncio una medida para el transporte",
                "summary": "La decision abre debate politico durante la jornada.",
                "body_text": "La medida tendra impacto en usuarios y autoridades locales.",
                "media_type": "image",
                "visible_metrics_json": '{"views": 0, "likes": 0, "comments": 0, "shares": 0}',
                "ranking_signals_json": '{"duration_seconds": 0}',
                "dedupe_status": "accepted",
            }
            national = scorer.score_item({**base_row, "source": "tn"})
            local = scorer.score_item({**base_row, "source": "eltribuno"})

        self.assertGreater(local.total, national.total)
        self.assertTrue(local.source_scores["salta_source_priority"])
        self.assertIn("salta_priority_bonus", local.reason)

    def test_non_news_image_does_not_publish_from_manual_review_floor(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DUO_SCORE_THRESHOLD": "62",
                "DUO_SCORE_KEEP_FLOOR": "52",
            },
            clear=False,
        ):
            get_settings.cache_clear()
            scorer = ViralityScorer(get_settings())
            score = scorer.score_item(
                {
                    "title": "Escándalo en la tele sin demasiada novedad",
                    "summary": "Resumen de agenda sin conflicto visible.",
                    "body_text": "",
                    "media_type": "image",
                    "visible_metrics_json": '{"views": 0, "likes": 0, "comments": 0, "shares": 0}',
                    "ranking_signals_json": '{"duration_seconds": 0}',
                    "source": "paparazzi",
                    "dedupe_status": "accepted",
                }
            )

        self.assertFalse(score.publish)


if __name__ == "__main__":
    unittest.main()

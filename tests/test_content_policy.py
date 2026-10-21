"""Politica tecnica: sin listas de temas; solo fuente, validez, vigencia y video obligatorio."""
from __future__ import annotations

import dataclasses
import json
import unittest
from datetime import datetime, timedelta, timezone

from jobs.content_policy import ContentPolicy
from storage.settings import get_settings

NOW = datetime(2026, 10, 17, 18, 0, tzinfo=timezone.utc)
BODY = "Texto de la nota con suficientes palabras para no ser considerada vacia. " * 3


def row(source: str = "eltribuno", *, title: str = "Corte de agua en zona sur de la ciudad", hours_old: float = 2, video: bool = False, **extra) -> dict:
    assets = [{"kind": "image", "remote_url": "https://example.test/a.jpg"}]
    if video:
        assets.append({"kind": "video", "remote_url": "https://example.test/v.mp4"})
    payload = {
        "content_key": "k",
        "source": source,
        "source_type": "x_video" if source == "x" else "news",
        "title": title,
        "summary": "Bajada de la nota",
        "body_text": BODY,
        "created_at": (NOW - timedelta(hours=hours_old)).isoformat(),
        "assets_json": json.dumps(assets),
    }
    payload.update(extra)
    return payload


class ContentPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        get_settings.cache_clear()
        self.policy = ContentPolicy(get_settings())

    def check(self, payload: dict):
        return self.policy.evaluate_row(payload, now=NOW)

    def test_local_story_of_any_topic_is_valid(self) -> None:
        # Deportes, cultura, religion o clima ya no se filtran por tema: decide la relevancia.
        for title in ("Gimnasia y Tiro gano y suena con el ascenso", "Miles de fieles en la procesion del Milagro", "Alerta por tormentas fuertes en el Valle de Lerma"):
            self.assertTrue(self.check(row(title=title)).accepted, title)

    def test_politician_name_does_not_grant_entry_by_itself(self) -> None:
        # Sin video, una nacional solo pasa a evaluarse con la exigencia de imagen (relevancia >= 70).
        decision = self.check(row("tn", title="Milei hablo en un acto en Buenos Aires"))
        self.assertTrue(decision.reason.startswith("valida; video=no; imagen_si_relevancia>=70"), decision.reason)

    def test_paparazzi_requires_video_and_national_needs_high_relevance_without_it(self) -> None:
        self.assertEqual(self.check(row("paparazzi")).reason, "sin_video")
        for source in ("tn", "infobae"):
            decision = self.check(row(source))
            self.assertTrue(decision.accepted, source)
            self.assertIn("imagen_si_relevancia>=70", decision.reason)
        for source in ("tn", "infobae", "paparazzi"):
            self.assertTrue(self.check(row(source, video=True)).accepted, source)

    def without_trim(self) -> None:
        self.policy.config = dataclasses.replace(self.policy.config, trim_long_videos=False)

    def test_long_video_is_eligible_when_trimmed(self) -> None:
        # Con media.trim_long_videos se publican sus primeros 90 s: el video largo cuenta como video.
        self.assertTrue(self.policy.config.trim_long_videos)
        long_video = json.dumps([{"kind": "video", "remote_url": "https://example.test/v.mp4", "duration_seconds": 224.0}])
        for source in ("paparazzi", "tn"):
            decision = self.check(row(source, assets_json=long_video))
            self.assertTrue(decision.accepted, source)
            self.assertEqual(decision.reason, "valida; video=si")

    def test_long_national_video_falls_back_to_image_rule(self) -> None:
        self.without_trim()
        long_video = json.dumps([{"kind": "video", "remote_url": "https://example.test/v.mp4", "duration_seconds": 224.0}])
        decision = self.check(row("tn", assets_json=long_video))
        self.assertTrue(decision.accepted)
        self.assertIn("imagen_si_relevancia>=70", decision.reason)

    def test_declared_video_over_90_seconds_is_not_eligible(self) -> None:
        self.without_trim()
        long_video = json.dumps([{"kind": "video", "remote_url": "https://example.test/v.mp4", "duration_seconds": 224.0}])
        decision = self.check(row("paparazzi", assets_json=long_video))
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "video_mayor_90s")
        short_video = json.dumps([{"kind": "video", "remote_url": "https://example.test/v.mp4", "duration_seconds": 85.0}])
        self.assertTrue(self.check(row("paparazzi", assets_json=short_video)).accepted)

    def test_local_sources_do_not_require_video(self) -> None:
        for source in ("eltribuno", "informatesalta", "quepasasalta", "gobiernosalta", "policiasalta", "municipalidadsalta"):
            self.assertTrue(self.check(row(source)).accepted, source)

    def test_removed_sources_are_rejected_even_if_already_in_database(self) -> None:
        for source in ("nuevodiariodesalta", "fiscalespenalesalta", "justiciasalta", "noticiasargentinas", "minutouno", "elonce", "ambitofinanciero", "ariesonline", "eloncesalta"):
            decision = self.check(row(source))
            self.assertFalse(decision.accepted)
            self.assertTrue(decision.reason.startswith("fuente_inactiva"), decision.reason)

    def test_freshness_by_group(self) -> None:
        self.assertTrue(self.check(row(hours_old=23)).accepted)
        self.assertTrue(self.check(row(hours_old=25)).reason.startswith("fuera_de_vigencia"))
        self.assertTrue(self.check(row("tn", video=True, hours_old=13)).reason.startswith("fuera_de_vigencia"))
        self.assertTrue(self.check(row("paparazzi", video=True, hours_old=20)).accepted)

    def test_missing_date_is_rejected(self) -> None:
        self.assertEqual(self.check(row(created_at="")).reason, "sin_fecha")

    def test_non_article_pages_are_rejected(self) -> None:
        for title in ("Acceso Full", "Edición impresa", "En vivo - Velez vs Gimnasia", "El horóscopo de hoy sábado 17"):
            self.assertEqual(self.check(row(title=title)).reason, "no_es_nota", title)

    def test_live_blog_is_rejected(self) -> None:
        self.assertEqual(self.check(row("tn", video=True, raw_payload_json=json.dumps({"live_blog": True}))).reason, "vivo_minuto_a_minuto")

    def test_thin_content_is_rejected(self) -> None:
        self.assertEqual(self.check(row(body_text="", summary="corto")).reason, "texto_insuficiente")

    def test_x_feed_video_needs_video_but_little_text(self) -> None:
        self.assertTrue(self.check(row("x", video=True, body_text="", summary="Choque en la ruta")).accepted)
        self.assertEqual(self.check(row("x", body_text="", summary="Choque")).reason, "sin_video")


if __name__ == "__main__":
    unittest.main()


class AgencyRoundupTests(unittest.TestCase):
    def test_date_stamp_titles_are_not_articles(self) -> None:
        from jobs.content_policy import ContentPolicy

        self.assertTrue(ContentPolicy._is_non_article({"title": "Domingo, 18 de octubre de 2026 (12:00 GMT)"}))
        self.assertFalse(ContentPolicy._is_non_article({"title": "El domingo 18 de octubre habrá cortes de agua en Salta"}))

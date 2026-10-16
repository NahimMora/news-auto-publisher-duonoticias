from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from jobs.content_policy import ContentPolicy
from storage.settings import get_settings


class ContentPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(
            os.environ,
            {
                "DUO_TIMEZONE": "America/Buenos_Aires",
                "DUO_PUBLISH_REQUIRE_SAME_LOCAL_DAY": "true",
            },
            clear=False,
        )
        self.env.start()
        get_settings.cache_clear()

    def tearDown(self) -> None:
        self.env.stop()
        get_settings.cache_clear()

    def test_accepts_today_political_content(self) -> None:
        settings = get_settings()
        policy = ContentPolicy(settings)
        today = datetime.now(ZoneInfo(settings.timezone)).replace(hour=10, minute=0, second=0, microsecond=0)
        decision = policy.evaluate_row(
            {
                "title": "El Gobierno envio una nueva reforma al Congreso",
                "summary": "La medida abre debate politico durante la jornada.",
                "media_type": "image",
                "created_at": today.isoformat(),
                "tags_json": '["tn","nacional"]',
            }
        )
        self.assertTrue(decision.accepted)

    def test_rejects_old_video_even_if_relevant(self) -> None:
        settings = get_settings()
        policy = ContentPolicy(settings)
        old = datetime.now(ZoneInfo(settings.timezone)).replace(hour=10, minute=0, second=0, microsecond=0) - timedelta(days=1)
        decision = policy.evaluate_row(
            {
                "title": "Video de un operativo policial con detenidos",
                "summary": "La policia informo el allanamiento.",
                "media_type": "video",
                "created_at": old.isoformat(),
                "tags_json": '["x"]',
            }
        )
        self.assertFalse(decision.accepted)

    def test_accepts_old_video_when_same_day_rule_is_disabled(self) -> None:
        with patch.dict(os.environ, {"DUO_PUBLISH_REQUIRE_SAME_LOCAL_DAY": "false"}, clear=False):
            get_settings.cache_clear()
            settings = get_settings()
            policy = ContentPolicy(settings)
            old = datetime.now(ZoneInfo(settings.timezone)).replace(hour=10, minute=0, second=0, microsecond=0) - timedelta(days=1)
            decision = policy.evaluate_row(
                {
                    "title": "Video de un operativo policial con detenidos",
                    "summary": "La policia informo el allanamiento.",
                    "media_type": "video",
                    "created_at": old.isoformat(),
                    "tags_json": '["x"]',
                }
            )
        self.assertTrue(decision.accepted)
        self.assertIn("video_topic_bypass", decision.reason)

    def test_accepts_previous_day_x_video_when_x_same_day_rule_is_disabled(self) -> None:
        settings = get_settings()
        policy = ContentPolicy(settings)
        old = datetime.now(ZoneInfo(settings.timezone)).replace(hour=10, minute=0, second=0, microsecond=0) - timedelta(days=1)
        today = old + timedelta(days=1, hours=2)
        decision = policy.evaluate_row(
            {
                "source": "x",
                "source_type": "x_video",
                "title": "Video de un operativo policial con detenidos",
                "summary": "La policia informo el allanamiento.",
                "media_type": "video",
                "created_at": old.isoformat(),
                "assigned_time": today.isoformat(),
            }
        )
        self.assertTrue(decision.accepted)
        self.assertIn("video_topic_bypass", decision.reason)

    def test_rejects_previous_day_x_video_when_x_same_day_rule_is_enabled(self) -> None:
        with patch.dict(os.environ, {"DUO_X_REQUIRE_SAME_LOCAL_DAY": "true"}, clear=False):
            get_settings.cache_clear()
            settings = get_settings()
            policy = ContentPolicy(settings)
            old = datetime.now(ZoneInfo(settings.timezone)).replace(hour=10, minute=0, second=0, microsecond=0) - timedelta(days=1)
            today = old + timedelta(days=1, hours=2)
            decision = policy.evaluate_row(
                {
                    "source": "x",
                    "source_type": "x_video",
                    "title": "Video de un operativo policial con detenidos",
                    "summary": "La policia informo el allanamiento.",
                    "media_type": "video",
                    "created_at": old.isoformat(),
                    "assigned_time": today.isoformat(),
                }
            )
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, f"not_from_today:{old.date().isoformat()}")

    def test_accepts_x_manual_conflict_video_when_same_day_rule_is_disabled(self) -> None:
        with patch.dict(os.environ, {"DUO_PUBLISH_REQUIRE_SAME_LOCAL_DAY": "false"}, clear=False):
            get_settings.cache_clear()
            settings = get_settings()
            policy = ContentPolicy(settings)
            old = datetime.now(ZoneInfo(settings.timezone)).replace(hour=10, minute=0, second=0, microsecond=0) - timedelta(days=1)
            decision = policy.evaluate_row(
                {
                    "source": "x_manual",
                    "source_type": "x_video",
                    "title": "Pelea en la villa con códigos de honor únicos",
                    "summary": "La pelea se volvió viral y abrió debate por los códigos de la calle.",
                    "body_text": "Un clip viral mostró una pelea y reavivó el debate sobre violencia y conflicto social.",
                    "media_type": "video",
                    "created_at": old.isoformat(),
                }
            )
        self.assertTrue(decision.accepted)
        self.assertIn("video_topic_bypass", decision.reason)

    def test_accepts_generic_video_without_news_topic_match(self) -> None:
        with patch.dict(os.environ, {"DUO_PUBLISH_REQUIRE_SAME_LOCAL_DAY": "false"}, clear=False):
            get_settings.cache_clear()
            settings = get_settings()
            policy = ContentPolicy(settings)
            today = datetime.now(ZoneInfo(settings.timezone)).replace(hour=10, minute=0, second=0, microsecond=0)
            decision = policy.evaluate_row(
                {
                    "source": "x_manual",
                    "source_type": "x_video",
                    "title": "Huawei lanza laptop con función inesperada",
                    "summary": "Un clip mostró una función nueva que sorprendió a todos.",
                    "body_text": "El video se viralizó por una característica poco común y abrió debate entre usuarios.",
                    "media_type": "video",
                    "created_at": today.isoformat(),
                }
            )
        self.assertTrue(decision.accepted)
        self.assertIn("video_topic_bypass", decision.reason)

    def test_rejects_low_value_topic(self) -> None:
        settings = get_settings()
        policy = ContentPolicy(settings)
        today = datetime.now(ZoneInfo(settings.timezone)).replace(hour=10, minute=0, second=0, microsecond=0)
        decision = policy.evaluate_row(
            {
                "title": "La Liga: hora y formaciones del partido",
                "summary": "Fixture deportivo con datos de equipos y horario.",
                "media_type": "image",
                "created_at": today.isoformat(),
                "tags_json": '["tn","deportes"]',
            }
        )
        self.assertFalse(decision.accepted)

    def test_rejects_subscription_landing_page(self) -> None:
        settings = get_settings()
        policy = ContentPolicy(settings)
        today = datetime.now(ZoneInfo(settings.timezone)).replace(hour=10, minute=0, second=0, microsecond=0)
        decision = policy.evaluate_row(
            {
                "source": "ambitofinanciero",
                "title": "Acceso full - $1.800/MES",
                "summary": "Contenido promocional de suscripcion digital sin informacion periodistica publicable.",
                "body_text": "La pagina ofrece beneficios comerciales, acceso a contenidos y planes de pago para lectores.",
                "media_type": "image",
                "created_at": today.isoformat(),
                "tags_json": '["ambitofinanciero","suscripcion"]',
            }
        )
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "low_value_page")

    def test_rejects_partial_term_false_positive(self) -> None:
        settings = get_settings()
        policy = ContentPolicy(settings)
        today = datetime.now(ZoneInfo(settings.timezone)).replace(hour=10, minute=0, second=0, microsecond=0)
        decision = policy.evaluate_row(
            {
                "source": "ambitofinanciero",
                "title": "Mercado inmobiliario",
                "summary": "Un corredor historico conserva su valor patrimonial.",
                "media_type": "image",
                "created_at": today.isoformat(),
                "tags_json": '["ambitofinanciero","economia"]',
            }
        )
        self.assertFalse(decision.accepted)

    def test_rejects_generic_section_page(self) -> None:
        settings = get_settings()
        policy = ContentPolicy(settings)
        today = datetime.now(ZoneInfo(settings.timezone)).replace(hour=10, minute=0, second=0, microsecond=0)
        decision = policy.evaluate_row(
            {
                "source": "infobae",
                "title": "Policiales",
                "summary": "Policiales, Crimen y Justicia",
                "body_text": "",
                "media_type": "image",
                "created_at": today.isoformat(),
                "tags_json": '["infobae","nacional"]',
            }
        )
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "thin_content")

    def test_rejects_disabled_source_already_in_database(self) -> None:
        settings = get_settings()
        policy = ContentPolicy(settings)
        today = datetime.now(ZoneInfo(settings.timezone)).replace(hour=10, minute=0, second=0, microsecond=0)
        decision = policy.evaluate_row(
            {
                "source": "ariesonline",
                "title": "El Gobierno anuncio una medida",
                "summary": "La decision se debate en el Congreso.",
                "media_type": "image",
                "created_at": today.isoformat(),
                "tags_json": '["ariesonline"]',
            }
        )
        self.assertFalse(decision.accepted)
        self.assertIn("disabled_source", decision.reason)

    def test_rejects_schedule_on_different_local_day(self) -> None:
        settings = get_settings()
        policy = ContentPolicy(settings)
        today = datetime.now(ZoneInfo(settings.timezone)).replace(hour=10, minute=0, second=0, microsecond=0)
        tomorrow = today + timedelta(days=1)
        decision = policy.evaluate_row(
            {
                "source": "tn",
                "title": "El Gobierno envio una nueva reforma al Congreso",
                "summary": "La medida abre debate politico durante la jornada.",
                "media_type": "image",
                "created_at": today.isoformat(),
                "assigned_time": tomorrow.isoformat(),
                "tags_json": '["tn","nacional"]',
            }
        )
        self.assertFalse(decision.accepted)
        self.assertEqual(decision.reason, "scheduled_day_mismatch")

    def test_accepts_public_safety_alert(self) -> None:
        settings = get_settings()
        policy = ContentPolicy(settings)
        today = datetime.now(ZoneInfo(settings.timezone)).replace(hour=10, minute=0, second=0, microsecond=0)
        decision = policy.evaluate_row(
            {
                "source": "x_manual",
                "source_type": "x_video",
                "title": "Fernet Branca adulterado invade el Conurbano",
                "summary": "Alerta por una bebida adulterada que pone en riesgo la salud.",
                "body_text": "Vecinos denunciaron la venta de botellas falsificadas y exigieron controles.",
                "media_type": "video",
                "created_at": today.isoformat(),
            }
        )
        self.assertTrue(decision.accepted)
        self.assertIn("video_topic_bypass", decision.reason)


if __name__ == "__main__":
    unittest.main()

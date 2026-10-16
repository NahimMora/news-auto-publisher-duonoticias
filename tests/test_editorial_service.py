from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from editorial.service import EditorialAI, _EMOJI_RE
from storage.settings import get_settings


class EditorialServiceTests(unittest.TestCase):
    def test_normalized_payload_preserves_cta_and_personality(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            get_settings.cache_clear()
            service = EditorialAI(get_settings())
            row = {
                "source": "paparazzi",
                "title": "Titulo base",
                "summary": "Resumen de la nota.",
                "body_text": "Primer bloque de contexto. Segundo bloque.",
            }
            payload = {
                "hook": "Hook con emoji 😱",
                "context": "Contexto #viral",
                "tension": "Tension 🔥",
                "remate": "Cierre",
                "cta": "Vos que opinas?",
                "caption": "🚨 Texto custom #fuerte",
            }
            normalized = service._normalize_payload(
                payload,
                row=row,
                prompt="PROMPT",
                input_payload={},
                growth_feedback="",
            )

        self.assertEqual(normalized["cta"], "Vos que opinas?")
        self.assertEqual(normalized["style"], "paparazzi_legacy")
        self.assertIn("Texto custom", normalized["caption"])
        self.assertIn("Resumen de la nota.", normalized["caption"])
        self.assertIn("Vos que opinas?", normalized["caption"])
        self.assertNotIn("#fuerte", normalized["caption"])
        self.assertEqual(normalized["hook"], "Hook con emoji")
        self.assertEqual(normalized["overlay"], "Titulo base")

    def test_fallback_uses_source_specific_style(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            get_settings.cache_clear()
            service = EditorialAI(get_settings())
            package = service.generate(
                {
                    "source": "x",
                    "title": "Video con emoji 🔥",
                    "summary": "Resumen factual del video.",
                    "body_text": "Primer detalle. Segundo detalle.",
                }
            )

        self.assertEqual(package.cta, "")
        self.assertEqual(package.style, "x_fallback")
        self.assertNotIn("🔥", package.hook)
        self.assertIn("Resumen factual del video.", package.caption)
        self.assertNotIn("Fuente:", package.caption)

    def test_fallback_treats_x_manual_video_like_x(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            get_settings.cache_clear()
            service = EditorialAI(get_settings())
            package = service.generate(
                {
                    "source": "x_manual",
                    "source_type": "x_video",
                    "title": "Fernet Branca adulterado invade el Conurbano",
                    "summary": "😱 ¡Alerta máxima en el Conurbano! Venden Fernet Branca adulterado que pone en riesgo la salud.",
                    "body_text": '"Fernet falso" Porque en el Conurbano están vendiendo Fernet Branca adulterado.',
                }
            )

        self.assertEqual(package.style, "x_fallback")
        self.assertIn("😱", package.caption)
        self.assertNotIn("Fuente:", package.caption)
        self.assertGreaterEqual(len(_EMOJI_RE.findall(package.caption)), 3)

    def test_x_caption_strips_source_attribution_by_default(self) -> None:
        with patch.dict(os.environ, {"X_CAPTION_INCLUDE_SOURCE": "0"}):
            get_settings.cache_clear()
            service = EditorialAI(get_settings())
            normalized = service._normalize_payload(
                {
                    "titulo_instagram": "Clip fuerte",
                    "caption": "Esto ya esta dando que hablar. #viral @cuenta\n\nVideo original de Cuenta en X",
                    "source_attribution": "Video original de Cuenta en X",
                },
                row={"source": "x", "source_handle": "Cuenta"},
                prompt="PROMPT",
                input_payload={},
                growth_feedback="",
            )

        self.assertIn("Esto ya esta dando que hablar.", normalized["caption"])
        self.assertNotIn("Cuenta", normalized["caption"])
        self.assertNotIn("#", normalized["caption"])
        self.assertNotIn("@", normalized["caption"])

    def test_limit_caption_trims_incomplete_ending(self) -> None:
        caption = EditorialAI._limit_caption(
            "Primera frase completa.\n\nSegunda frase completa.\n\nEste cierre quedo cort",
            max_chars=500,
        )

        self.assertEqual(caption, "Primera frase completa.\n\nSegunda frase completa.")

    def test_truncated_article_excerpt_is_not_used_as_final_caption(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            get_settings.cache_clear()
            service = EditorialAI(get_settings())
            normalized = service._normalize_payload(
                {
                    "titulo_instagram": "Tension total en vivo",
                    "caption": "Tension total en vivo\n\nLa conductora exploto y marco el limite de […]",
                    "cta": "¿Que opinas?",
                },
                row={
                    "source": "paparazzi",
                    "title": "Tension total en vivo",
                    "summary": "La conductora exploto y marco el limite de […]",
                    "body_text": (
                        "La conductora exploto y marco el limite de […]\n"
                        "El cruce ocurrio durante el programa y dejo al panel en silencio. "
                        "La discusion venia escalando desde el inicio del bloque."
                    ),
                },
                prompt="PROMPT",
                input_payload={},
                growth_feedback="",
            )

        self.assertNotIn("[…]", normalized["caption"])
        self.assertIn("El cruce ocurrio durante el programa", normalized["caption"])
        self.assertIn("¿Que opinas?", normalized["caption"])

    def test_news_caption_gets_extra_emojis_when_model_returns_too_few(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}):
            get_settings.cache_clear()
            service = EditorialAI(get_settings())
            normalized = service._normalize_payload(
                {
                    "titulo_instagram": "Nueva medida del Gobierno",
                    "caption": "Nueva medida del Gobierno\n\nHabra cambios desde hoy.\n\nEl anuncio se hizo esta manana.\n\nQue opinas?",
                },
                row={
                    "source": "tn",
                    "title": "Nueva medida del Gobierno",
                    "summary": "Habra cambios desde hoy.",
                    "body_text": "El anuncio se hizo esta manana con detalles del paquete.",
                },
                prompt="PROMPT",
                input_payload={},
                growth_feedback="",
            )

        self.assertGreaterEqual(len(_EMOJI_RE.findall(normalized["caption"])), 3)


if __name__ == "__main__":
    unittest.main()

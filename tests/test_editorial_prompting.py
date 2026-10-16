from __future__ import annotations

import unittest

from editorial.prompting import build_editorial_user_prompt, is_x_editorial_row, load_master_prompt


class EditorialPromptingTests(unittest.TestCase):
    def test_uses_central_policy_prompts_per_source(self) -> None:
        paparazzi_prompt = load_master_prompt(row={"source": "paparazzi"})
        self.assertIn("seleccionar solo notas con potencial real", paparazzi_prompt)
        self.assertIn("POLITICA EDITORIAL CONFIGURABLE", paparazzi_prompt)

        x_prompt = load_master_prompt(row={"source": "x"})
        self.assertIn("reels y clips virales detectados en X", x_prompt)
        self.assertIn("3 a 6 emojis", x_prompt)

        x_manual_prompt = load_master_prompt(row={"source": "x_manual", "source_type": "x_video"})
        self.assertIn("reels y clips virales detectados en X", x_manual_prompt)

        news_prompt = load_master_prompt(row={"source": "tn"})
        self.assertIn("4 a 6 parrafos cortos", news_prompt)
        self.assertIn("2 a 4 emojis", news_prompt)

    def test_user_prompt_keeps_content_and_feedback(self) -> None:
        row = {
            "source": "x",
            "source_handle": "UnPocoTende",
            "title": "Escandalo total",
            "summary": "Se viralizo un clip fuerte",
            "body_text": "Primer detalle.\nSegundo detalle.",
            "canonical_url": "https://x.com/UnPocoTende/status/1",
            "score_json": '{"total": 88}',
            "visible_metrics_json": '{"views": 12000}',
            "ranking_signals_json": '{"strategy": "yt-dlp"}',
        }
        prompt = build_editorial_user_prompt(
            row,
            growth_feedback="CONTENIDO QUE FUNCIONA:\n- hook fuerte",
        )
        self.assertIn("handle_auditoria_no_mencionar: UnPocoTende", prompt)
        self.assertIn("Escandalo total", prompt)
        self.assertIn("CONTENIDO QUE FUNCIONA:", prompt)
        self.assertIn('{"total": 88}', prompt)

    def test_x_manual_rows_use_x_editorial_mode(self) -> None:
        row = {"source": "x_manual", "source_type": "x_video"}
        self.assertTrue(is_x_editorial_row(row))
        prompt = build_editorial_user_prompt(
            {
                "source": "x_manual",
                "source_type": "x_video",
                "source_handle": "porqueTTarg",
                "title": "Fernet adulterado",
                "summary": "Alerta sanitaria",
                "body_text": "Detalle del video.",
            },
            growth_feedback="sin feedback",
        )
        self.assertIn("CLIP DE X", prompt)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from formatter.motion_engine import (
    MotionConfig,
    MotionEngine,
    MotionRenderError,
    VisualBrief,
    extract_visual,
    split_text_slides,
    validate_highlights,
    validate_stats,
)
from storage.settings import get_settings

ROOT = Path(__file__).resolve().parents[1]
MOTION = ROOT / "motion"

NOTE = (
    "El turismo en Salta movio 142.000 visitantes durante el fin de semana largo. "
    "La ocupacion hotelera en la capital llego al 87% frente al 74% del ano anterior. "
    "El gasto promedio diario fue de $68.500 por turista, segun el Ministerio de Turismo."
)


def _config(tmp: Path, **overrides) -> MotionConfig:
    base = dict(
        enabled=True,
        node="node",
        motion_dir=tmp,
        photo_reel_modes={"breaking", "data"},
        photo_reel_seconds=14,
        max_reel_seconds=180,
        render_timeout_seconds=60,
        inbox=True,
    )
    base.update(overrides)
    return MotionConfig(**base)


class FakeWorker:
    """Imita el worker Node: escribe un archivo en `out` y devuelve el evento done."""

    def __init__(self, fail: bool = False) -> None:
        self.calls: list[dict] = []
        self.fail = fail

    def available(self) -> bool:
        return True

    def render(self, piece, out, kind="auto", *, timeout=None):
        self.calls.append({"piece": piece, "out": str(out), "kind": kind})
        if self.fail:
            raise MotionRenderError("boom")
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        if str(out).endswith(".jpg"):
            Image.new("RGB", (1080, 1350), (54, 25, 87)).save(out, quality=90)
        else:
            Path(out).write_bytes(b"\x00" * 60000)
        return {"event": "done", "out": str(out), "ms": 10}

    def close(self, *, force: bool = False) -> None:
        pass


class ValidationTests(unittest.TestCase):
    def test_stats_must_appear_in_the_note(self) -> None:
        stats = validate_stats(
            [
                {"valor": 142000, "etiqueta": "visitantes"},
                {"valor": 87, "unidad": "%", "etiqueta": "ocupacion", "comparar_con": 74, "etiqueta_comparacion": "2025"},
                {"valor": 68500, "prefijo": "$", "etiqueta": "gasto diario"},
                {"valor": 99000, "etiqueta": "inventada"},
                {"valor": 87, "etiqueta": "comparacion inventada", "comparar_con": 12},
            ],
            NOTE,
        )
        self.assertEqual([s["value"] for s in stats], [142000.0, 87.0, 68500.0, 87.0])
        self.assertEqual(stats[1]["compareValue"], 74.0)
        self.assertNotIn("compareValue", stats[3])  # 12 no figura en la nota
        self.assertEqual(stats[2]["prefix"], "$")

    def test_highlights_anchored_in_source(self) -> None:
        kept = validate_highlights(
            ["La ocupacion hotelera en la capital llego al 87%", "El gobernador anuncio un plan secreto de inversiones"],
            NOTE,
        )
        self.assertEqual(kept, ["La ocupacion hotelera en la capital llego al 87%"])

    def test_extract_visual_uses_gemini_block_and_falls_back(self) -> None:
        editorial = {
            "context": "Balance del fin de semana largo.",
            "raw_response": {
                "visual": {
                    "titular_audiovisual": "Así se movió el *turismo* en Salta",
                    "categoria": "turismo",
                    "ubicacion": "Salta",
                    "urgente": False,
                    "claves": [],
                    "cifras": [{"valor": 142000, "etiqueta": "visitantes"}],
                }
            },
        }
        brief = extract_visual(editorial, {"title": "t", "body_text": NOTE}, {}, fallback_title="t", theme="default")
        self.assertEqual(brief.headline, "Así se movió el *turismo* en Salta")
        self.assertEqual((brief.category, brief.location, brief.breaking), ("turismo", "Salta", False))
        self.assertEqual(len(brief.stats), 1)

        fallback = extract_visual({}, {"title": "Gol de River 🔥 #futbol"}, {}, fallback_title="Gol de River 🔥 #futbol", theme="sports")
        self.assertEqual(fallback.headline, "Gol de River")
        self.assertEqual(fallback.category, "deportes")
        self.assertEqual(fallback.stats, [])

    def test_unbalanced_emphasis_is_removed(self) -> None:
        brief = extract_visual({"raw_response": {"visual": {"titular_audiovisual": "Un *titular roto"}}}, {}, {}, fallback_title="x", theme="")
        self.assertEqual(brief.headline, "Un titular roto")

    def test_split_text_slides_never_cuts_words(self) -> None:
        text = " ".join(["Oracion numero %d con algunas palabras de relleno." % i for i in range(20)])
        slides = split_text_slides(text, max_chars=200, max_slides=2)
        self.assertEqual(len(slides), 2)
        for slide in slides:
            self.assertLessEqual(len(slide), 200)
            self.assertTrue(slide.endswith("."))


class EngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="duo_motion_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.photo = self.tmp / "foto.jpg"
        Image.new("RGB", (2000, 1500), (120, 120, 120)).save(self.photo)
        self.engine = MotionEngine(get_settings(), _config(self.tmp))
        self.engine.worker = FakeWorker()

    def _brief(self, **kw) -> VisualBrief:
        base = dict(headline="Titular *clave*", deck="", category="sociedad", location=None, breaking=False)
        base.update(kw)
        return VisualBrief(**base)

    def test_content_has_dimensions_and_source(self) -> None:
        content = self.engine.build_content("k1", {"source": "eltribuno", "title": "Original"}, self._brief(), photos=[str(self.photo)])
        self.assertEqual(content["source"]["name"], "El Tribuno")
        self.assertEqual((content["photos"][0]["width"], content["photos"][0]["height"]), (2000.0, 1500.0))
        self.assertNotIn("url", content["source"])

    def test_photo_reel_modes(self) -> None:
        self.assertEqual(self.engine.wants_photo_reel(self._brief(breaking=True)), "breaking")
        stats = [{"label": "a", "value": 1}, {"label": "b", "value": 2}]
        self.assertEqual(self.engine.wants_photo_reel(self._brief(stats=stats)), "data")
        self.assertIsNone(self.engine.wants_photo_reel(self._brief()))
        self.engine.config.photo_reel_modes = set()
        self.assertIsNone(self.engine.wants_photo_reel(self._brief(breaking=True)))

    def test_post_with_photo_slides_and_inbox(self) -> None:
        content = self.engine.build_content("k2", {"source": "tn"}, self._brief(), photos=[str(self.photo), str(self.photo)])
        result = self.engine.render_post("k2", content, self.tmp / "out")
        self.assertEqual(len(result["paths"]), 2)
        kinds = [c["piece"]["presentation"]["slide"]["kind"] for c in self.engine.worker.calls]
        self.assertEqual(kinds, ["cover", "photo"])
        self.assertTrue(list((self.tmp / "data" / "inbox").glob("*.json")))

    def test_video_reel_duration_is_capped(self) -> None:
        content = self.engine.build_content("k3", {"source": "x"}, self._brief())
        content["videos"] = [{"src": "C:/v.mp4", "durationSeconds": 400.0, "keepAudio": True, "trimStartSeconds": 0}]
        self.engine.render_reel("k3", content, "editorial", self.tmp / "out" / "k3.mp4")
        presentation = self.engine.worker.calls[0]["piece"]["presentation"]
        self.assertEqual(presentation["durationSeconds"], 180.0)
        self.assertEqual(content["source"]["name"], "Redes sociales")


class FormatterIntegrationTests(unittest.TestCase):
    def test_formatter_falls_back_to_legacy_when_motion_fails(self) -> None:
        from formatter.service import AssetFormatter

        with patch.dict(os.environ, {"DUO_MOTION_ENGINE": "1"}):
            formatter = AssetFormatter(get_settings())
        formatter.motion.worker = FakeWorker(fail=True)
        with patch.object(type(formatter.motion), "enabled", new=property(lambda self: True)), patch.object(
            formatter, "_format_image", return_value="legacy"
        ) as legacy:
            row = {"content_key": "k", "editorial_json": "{}", "assets_json": json.dumps([{"kind": "image", "path": __file__}])}
            with patch.object(formatter, "_motion_local_images", return_value=[__file__]), patch.object(
                formatter, "_validate_package"
            ):
                self.assertEqual(formatter.format_row(row), "legacy")
            legacy.assert_called_once()


@unittest.skipUnless(shutil.which("node") and (MOTION / "node_modules" / "tsx").exists(), "motion no instalado")
class ContractTests(unittest.TestCase):
    def test_python_pieces_validate_against_motion_schema(self) -> None:
        engine = MotionEngine(get_settings(), _config(MOTION, inbox=False))
        brief = VisualBrief(
            headline="Así se movió el *turismo*",
            deck="Balance",
            category="turismo",
            location="Salta",
            breaking=False,
            highlights=["La ocupacion hotelera en la capital llego al 87%"],
            stats=validate_stats([{"valor": 87, "unidad": "%", "etiqueta": "ocupacion", "comparar_con": 74}], NOTE),
        )
        content = engine.build_content("k-contract", {"source": "eltribuno", "canonical_url": "https://x.y/z"}, brief)
        pieces = [
            {"content": content, "presentation": {"template": "data", "hook": "auto", "format": "reel", "durationSeconds": 14, "theme": "light"}},
            {"content": content, "presentation": {"template": "static", "format": "portrait", "staticVariant": "auto", "slide": {"kind": "text", "index": 1, "total": 2, "text": "Hola"}}},
        ]
        proc = subprocess.run(
            ["node", str(MOTION / "node_modules" / "tsx" / "dist" / "cli.mjs"), "render/validate.ts"],
            cwd=str(MOTION),
            input=json.dumps(pieces),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()

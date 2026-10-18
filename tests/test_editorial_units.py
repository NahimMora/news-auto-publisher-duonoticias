"""Unidades de la reestructuracion: eventos, cupos, relevancia, captions, marcas de agua, extractores."""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from editorial import captions
from extractors.news.arc import ArcNewsExtractor
from extractors.news.informatesalta import InformateSaltaExtractor
from extractors.news.media import arc_videos, classify_video_url, parse_iso_duration
from extractors.news.quepasasalta import QuePasaSaltaExtractor
from jobs.allocation import Candidate, allocate
from jobs.events import EventProbe, extract_entities, match_event, material_update_signals
from jobs.relevance import compute_score, expand_item, fair_order
from storage.editorial_config import load_editorial_config
from storage.settings import get_settings
from utils import watermark


def config():
    get_settings.cache_clear()
    return load_editorial_config(get_settings())


class EventTests(unittest.TestCase):
    def probe(self, key, title, summary="", category="general"):
        return EventProbe.build(key, title, summary, category=category, published_at="2026-10-17T22:00:00+00:00")

    def test_same_fact_from_three_outlets_is_one_event(self) -> None:
        a = self.probe("pol", "Fueron halladas las dos niñas reportadas con paradero desconocido en Salta", "Las menores fueron localizadas por la División Búsqueda de Personas en barrio Santa Ana.", "policiales")
        b = self.probe("trib", "Encontraron a las dos niñas que fueron reportadas como desaparecidas en Salta", "Las menores habían sido vistas por última vez en barrio Santa Ana.", "policiales")
        c = self.probe("qp", "Operativo clave: así fue el paso a paso para hallar a las dos niñas desaparecidas", "La División Búsqueda de Personas trabajó en Santa Ana.", "policiales")
        self.assertIsNotNone(match_event(b, {"E": [a]}))
        self.assertIsNotNone(match_event(c, {"E": [a, b]}))

    def test_same_person_in_different_cases_is_not_grouped(self) -> None:
        a = self.probe("1", "Juan Pérez asumió como director del hospital de Orán", category="general")
        b = self.probe("2", "Juan Pérez participó de un festival folclórico en Cafayate", category="general")
        self.assertIsNone(match_event(b, {"E": [a]}))

    def test_generic_institutions_do_not_group_police_reports(self) -> None:
        reports = [
            self.probe("p1", "Fue detectado con código rojo durante un control vial en Capital", "Personal de la Policía de Salta en Distritos de Prevención.", "policiales"),
            self.probe("p2", "La Policía clausuró tres fiestas no autorizadas en el norte provincial", "Policía de Salta, Distritos de Prevención, Orán.", "policiales"),
        ]
        third = self.probe("p3", "Patrullajes preventivos con 30 aprehendidos y secuestro de armas", "Policía de Salta en Distritos de Prevención.", "policiales")
        self.assertIsNone(match_event(third, {"A": [reports[0]], "B": [reports[1]]}))

    def test_containment_matches_names(self) -> None:
        a = self.probe("a", "Crimen en Barrio Miguel Ortiz: apareció un video de una pelea", "El profesor Velarde fue apuñalado.", "policiales")
        b = self.probe("b", "Crimen en Miguel Ortíz: filtraron un video de Velarde atacando", "El video muestra al profesor fallecido.", "policiales")
        self.assertIsNotNone(match_event(b, {"E": [a]}))

    def test_entities(self) -> None:
        self.assertEqual(extract_entities("Axel Kicillof y Máximo Kirchner encabezaron actos por el Día de la Lealtad"), ["axel kicillof", "maximo kirchner", "dia de la lealtad"])
        self.assertEqual(extract_entities("¡Apareció Sofía en Salta! Fue hallada"), ["sofia"])

    def test_material_update_signals(self) -> None:
        self.assertTrue(material_update_signals("Murió uno de los heridos y detuvieron al conductor", "Choque deja dos heridos"))
        self.assertEqual(material_update_signals("Choque deja dos heridos en la ruta", "Choque deja dos heridos"), [])


class AllocationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = config()

    def cand(self, key, group, score, source="eltribuno", event="", salta=False):
        return Candidate(key, group, source, score, 50, event_key=event or key, salta_related=salta, queue_entered_at="2026-10-17T10:00:00+00:00")

    def test_caps_and_free_slots(self) -> None:
        pool = [self.cand(f"l{i}", "local", 90 - i, source=f"s{i % 3}") for i in range(9)]
        pool += [self.cand(f"n{i}", "national", 95 - i, source="tn") for i in range(4)]
        pool += [self.cand(f"p{i}", "paparazzi", 70 - i, source="paparazzi") for i in range(4)]
        plan = allocate(pool, self.cfg)
        slots = [item["slot"] for item in plan.selected]
        # Sin cupos libres (decision 2026-10-18): techo 10 = 6 locales + 2 nacionales + 2 Paparazzi.
        self.assertEqual(self.cfg.free_slots, 0)
        self.assertEqual(len(slots), 10)
        self.assertEqual(slots.count("national"), 2)
        self.assertEqual(slots.count("local"), 6)
        self.assertEqual(slots.count("paparazzi"), 2)
        self.assertNotIn("free", slots)

    def test_free_slots_never_go_to_national_when_enabled(self) -> None:
        from dataclasses import replace

        cfg = replace(self.cfg, free_slots=2, max_per_cycle=12)
        pool = [self.cand(f"n{i}", "national", 95 - i, source="tn") for i in range(4)]
        pool += [self.cand(f"p{i}", "paparazzi", 70 - i, source="paparazzi") for i in range(4)]
        plan = allocate(pool, cfg)
        free = [item["content_key"] for item in plan.selected if item["slot"] == "free"]
        self.assertEqual(len(free), 2)
        self.assertFalse(any(key.startswith("n") for key in free))

    def test_below_threshold_never_fills(self) -> None:
        plan = allocate([self.cand("l1", "local", 40)], self.cfg)
        self.assertEqual(plan.selected, [])
        self.assertIn("l1", plan.below_threshold)

    def test_one_slot_per_event_and_source_cap(self) -> None:
        pool = [self.cand("a", "local", 90, event="E"), self.cand("b", "local", 89, event="E")]
        pool += [self.cand(f"t{i}", "local", 80 - i, source="eltribuno") for i in range(5)]
        plan = allocate(pool, self.cfg)
        keys = plan.selected_keys
        self.assertIn("a", keys)
        self.assertNotIn("b", keys)
        self.assertEqual(plan.reasons["b"], "mismo_hecho_ya_elegido")
        local_tribuno = [i for i in plan.selected if i["slot"] == "local" and i["content_key"].startswith("t")]
        self.assertLessEqual(len(local_tribuno), self.cfg.max_per_source_per_cycle)

    def test_x_video_without_salta_link_waits_when_no_free_slots(self) -> None:
        plan = allocate([self.cand("x2", "x_feed", 90, source="x", salta=False)], self.cfg)
        self.assertEqual(plan.selected, [])
        self.assertIn("x2", plan.waiting)

    def test_salta_x_video_can_take_local_slot(self) -> None:
        plan = allocate([self.cand("x1", "x_feed", 70, source="x", salta=True)], self.cfg)
        self.assertEqual(plan.selected, [{"content_key": "x1", "slot": "local"}])

    def test_already_used_slots_count(self) -> None:
        pool = [self.cand(f"n{i}", "national", 95 - i, source="tn") for i in range(3)]
        plan = allocate(pool, self.cfg, used={"national": 2})
        self.assertEqual(plan.selected, [])


class RelevanceScoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = config()

    def test_score_is_weighted_and_explained(self) -> None:
        item = expand_item({"im": 8, "ur": 6, "ip": 9, "gr": 2, "nv": 7, "rp": 7, "rs": 2, "ri": 0, "pn": 0, "cs": 1})
        result = compute_score("local", item, self.cfg)
        expected = (8 * 0.25 + 6 * 0.15 + 9 * 0.25 + 2 * 0.10 + 7 * 0.15 + 7 * 0.10) * 10
        self.assertAlmostEqual(result.score, round(expected, 1))
        self.assertEqual(result.penalties, {})

    def test_routine_and_national_politics_are_penalized(self) -> None:
        item = expand_item({"im": 7, "ur": 7, "ip": 7, "gr": 7, "nv": 7, "rp": 7, "rs": 2, "ri": 1, "pn": 0, "cs": 1})
        official = compute_score("local", item, self.cfg, official=True)
        self.assertIn("rutina_institucional", official.penalties)
        national = compute_score("national", expand_item({"im": 8, "ur": 8, "ip": 8, "gr": 8, "nv": 8, "rp": 8, "pn": 1}), self.cfg)
        self.assertIn("politica_nacional_rutinaria", national.penalties)

    def test_local_outlet_note_without_salta_relation_is_penalized(self) -> None:
        result = compute_score("local", expand_item({"im": 7, "ur": 7, "ip": 7, "nv": 7, "rp": 7, "rs": 0}), self.cfg)
        self.assertIn("sin_relacion_salta", result.penalties)

    def test_fair_order_interleaves_sources(self) -> None:
        rows = [{"source": "infobae", "k": i} for i in range(5)] + [{"source": "eltribuno", "k": 9}]
        ordered = fair_order(rows, 3)
        self.assertIn("eltribuno", [r["source"] for r in ordered])


class CaptionTests(unittest.TestCase):
    def test_labels_and_source_mentions_are_removed(self) -> None:
        text = "¿Qué pasó?\nUn choque en la ruta 9, según informó El Tribuno.\n\n▪️ Por qué importa: afecta el tránsito.\n\nFuente: El Tribuno"
        clean = captions.strip_labels(text, ["El Tribuno"])
        self.assertNotIn("Qué pasó", clean)
        self.assertNotIn("Por qué importa", clean)
        self.assertNotIn("El Tribuno", clean)
        self.assertNotIn("Fuente", clean)

    def test_caps_title_is_fixed(self) -> None:
        self.assertEqual(captions.fix_title("URGENTE: CORTE DE AGUA EN SALTA!!!"), "Urgente: corte de agua en Salta!")
        self.assertEqual(captions.fix_title("Corte de agua en AFA"), "Corte de agua en AFA")
        self.assertEqual(captions.fix_title("PARO DE SAETA EN SALTA"), "Paro de SAETA en Salta")

    def test_unsupported_numbers_are_flagged(self) -> None:
        check = captions.check_caption("Murieron 5 personas en 2 choques.", source_text="Murieron cinco personas en 2 choques")
        self.assertIn("cifras_sin_respaldo:5", check.issues)

    def test_hashtags_are_moderate_and_geographic_only_when_salteno(self) -> None:
        self.assertEqual(captions.build_hashtags(group="national", category="policiales", salta_related=False), ["#DuoNoticias", "#Argentina", "#Policiales"])
        self.assertIn("#Salta", captions.build_hashtags(group="local", category="clima", salta_related=True))
        self.assertNotIn("#Salta", captions.build_hashtags(group="paparazzi", category="espectaculos", salta_related=False))

    def test_final_caption_is_under_2000_chars(self) -> None:
        final = captions.assemble("Parrafo largo. " * 400, ["#DuoNoticias", "#Salta"])
        self.assertLess(len(final), 2000)
        self.assertTrue(final.endswith("#DuoNoticias #Salta"))


class WatermarkTests(unittest.TestCase):
    def textured(self, w=1200, h=675, seed=1):
        rng = np.random.default_rng(seed)
        base = cv2.GaussianBlur(rng.integers(40, 200, (h, w), dtype=np.uint8), (0, 0), 6)
        return cv2.cvtColor(base, cv2.COLOR_GRAY2BGR)

    def stamp(self, image, mask_name, frac, alpha=0.45):
        mask = cv2.imread(str(watermark.MASK_DIR / mask_name), cv2.IMREAD_GRAYSCALE)
        h, w = image.shape[:2]
        tw = int(w * frac)
        m = cv2.resize(mask, (tw, int(mask.shape[0] * tw / mask.shape[1]))) > 127
        y, x = int(h * 0.45), (w - tw) // 2
        region = image[y : y + m.shape[0], x : x + tw].astype(np.float32)
        region[m] = region[m] * (1 - alpha) + 255 * alpha
        image[y : y + m.shape[0], x : x + tw] = region.astype(np.uint8)
        return image

    def test_eltribuno_watermark_detected_and_clean_image_passes(self) -> None:
        clean = self.textured()
        marked = self.stamp(self.textured(seed=2), "eltribuno_mask.png", 0.66)
        self.assertEqual(watermark.verdict_for_gray(cv2.cvtColor(clean, cv2.COLOR_BGR2GRAY), ["eltribuno"]).status, "clean")
        self.assertEqual(watermark.verdict_for_gray(cv2.cvtColor(marked, cv2.COLOR_BGR2GRAY), ["eltribuno"]).status, "watermark")

    def test_quepasa_watermark_detected(self) -> None:
        marked = self.stamp(self.textured(seed=3), "quepasasalta_text_mask.png", 0.4)
        self.assertEqual(watermark.verdict_for_gray(cv2.cvtColor(marked, cv2.COLOR_BGR2GRAY), ["quepasasalta"]).status, "watermark")

    def test_informate_band_detected_with_exact_height(self) -> None:
        frames = []
        for seed in range(6):
            frame = self.textured(720, 514, seed)
            frame[-39:, :] = (200, 120, 0)  # BGR del azul de la franja
            cv2.putText(frame, "informatesalta", (10, 505), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
            frames.append(frame)
        band = watermark.detect_bottom_band(frames)
        self.assertTrue(band.found)
        self.assertAlmostEqual(band.height_px, 39, delta=2)
        self.assertFalse(watermark.detect_bottom_band([self.textured(720, 514, s) for s in range(6)]).found)

    def test_too_tall_band_is_not_cropped(self) -> None:
        frames = []
        for seed in range(6):
            frame = self.textured(720, 514, seed)
            frame[-150:, :] = (200, 120, 0)
            frames.append(frame)
        self.assertEqual(watermark.detect_bottom_band(frames).reason, "franja_demasiado_alta")


class ExtractorParsingTests(unittest.TestCase):
    def test_informate_cover_video_from_lazy_attrs(self) -> None:
        html = """
        <div data-tadevel-template="web/article"><div data-tadevel-template="web/article-deco">
          <video autoplay data-tadevel-template="web/video" poster="https://flex-assets.tadevel-cdn.com/abc/thumb.jpg">
            <source data-tadevel-lazy-attrs="src=https%3A%2F%2Fflex-assets.tadevel-cdn.com%2Fabc%2Fvideo.mp4" type="video/mp4">
          </video>
          <header data-tadevel-template="web/article-header"><h1>Choque en avenida Tavella</h1></header>
          <div data-tadevel-template="web/article-body"><div class="article-body-content">
            <p>El impacto ocurrio en plena interseccion con el ingreso a la Ruta 26.<p>Ambulancias del SAMEC asistieron a los ocupantes.</p></p>
          </div></div>
          <div data-tadevel-template="web/article-related"><video><source src="https://flex-assets.tadevel-cdn.com/otra/video.mp4"></video></div>
        </div></div>
        <meta property="article:published_time" content="2026-10-17T11:59:00.000Z">
        """
        detail = InformateSaltaExtractor().parse_article_html(html, "https://informatesalta.com.ar/x/y_a" + "0" * 24)
        urls = [v["url"] for v in detail["video_candidates"]]
        self.assertIn("https://flex-assets.tadevel-cdn.com/abc/video.mp4", urls)
        self.assertNotIn("https://flex-assets.tadevel-cdn.com/otra/video.mp4", urls)
        self.assertEqual(detail["video_candidates"][0]["location"], "cover")
        self.assertEqual(len(detail["parrafos"]), 2)

    def test_quepasa_embedded_tweet_and_related_cards_ignored(self) -> None:
        html = """
        <script type="application/ld+json">{"@type":"NewsArticle","headline":"Crimen","datePublished":"2026-10-17T19:57:38-03:00","image":"https://www.quepasasalta.com.ar/files/image/1/1/a.mp4"}</script>
        <h1 class="content-title">Crimen en Miguel Ortiz</h1>
        <div class="media content-media"><img src="https://i1.quepasasalta.com.ar/files/image/1/2/b_1135_639!.jpg"></div>
        <div class="content vsmcontent">
          <p>La conmocion continua latente en los barrios saltenos tras el tragico episodio.</p>
          <figure><blockquote class="twitter-tweet"><a href="https://twitter.com/QuePasaSalta/status/2111586536055803990">link</a></blockquote></figure>
          <article class="item news"><video src="https://i1.quepasasalta.com.ar/files/image/9/9/otra.mp4"></video></article>
        </div>
        """
        detail = QuePasaSaltaExtractor().parse_article_html(html, "https://www.quepasasalta.com.ar/policiales/crimen-en-miguel-ortiz/")
        kinds = {(v["kind"], v["url"]) for v in detail["video_candidates"]}
        self.assertIn(("tweet", "https://x.com/QuePasaSalta/status/2111586536055803990"), kinds)
        self.assertFalse(any("otra.mp4" in url for _, url in kinds))

    def test_arc_genoa_and_jwplayer_videos(self) -> None:
        content = {
            "promo_items": {"basic": {"type": "custom_embed", "subtype": "genoa", "embed": {"id": "1", "config": {"highQuality": "https://vod.vodgc.net/x_1080P.mp4", "duration": 125958}}}},
            "content_elements": [
                {"type": "text", "content": "Texto suficientemente largo de la nota para el cuerpo."},
                {"type": "custom_embed", "subtype": "video", "embed": {"config": {"contentUrl": "https://cdn.jwplayer.com/videos/uM0gSUNX-gTHcH4FX.mp4", "duration": "P0Y0M0DT0H0M47S", "mediaId": "uM0gSUNX"}}},
            ],
        }
        videos = arc_videos(content)
        self.assertEqual([(v.location, v.provider) for v in videos], [("cover", "genoa"), ("body", "jwplayer")])
        self.assertAlmostEqual(videos[0].duration_seconds, 125.958, places=2)
        self.assertEqual(videos[1].duration_seconds, 47)

    def test_infobae_foreign_editions_are_excluded(self) -> None:
        extractor = ArcNewsExtractor("infobae", base_url="https://www.infobae.com", feeds=[], exclude_path_prefixes=["/mexico/", "/peru/"])
        self.assertFalse(extractor.is_article_url("https://www.infobae.com/mexico/2026/10/17/nota/"))
        self.assertTrue(extractor.is_article_url("https://www.infobae.com/sociedad/2026/10/17/nota/"))

    def test_video_url_classification(self) -> None:
        self.assertEqual(classify_video_url("https://x.com/a/status/1"), "tweet")
        self.assertEqual(classify_video_url("https://api.onvideo.news/embed/aa2f7645-fd32-40b7-a7c8-b0a4123f5c47"), "onvideo")
        self.assertEqual(classify_video_url("https://cdn.x/master.m3u8"), "hls")
        self.assertEqual(classify_video_url("https://www.googletagmanager.com/a.mp4"), "")
        self.assertEqual(parse_iso_duration("PT00H02M5S"), 125)


if __name__ == "__main__":
    unittest.main()

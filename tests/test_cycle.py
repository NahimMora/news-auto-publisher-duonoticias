"""Aceptacion del ciclo horario: cupos, cola de 12 h, duplicados, reinicios e idempotencia.

Todo con dobles: fuentes, Gemini, formateador, descargas y Meta. Nunca hay red ni
publicaciones reales.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List
from unittest.mock import patch

from jobs.pipeline import DuoPipeline
from storage.models import Asset, ExtractedContent, FormattedPackage, PublicationRecord
from storage.settings import get_settings
from utils.llm_client import LLMUsage
from utils.media_resolver import ResolvedVideo
from utils.watermark import WatermarkVerdict

BODY = "El hecho ocurrio en la ciudad y afecto a muchos vecinos que pidieron respuestas a las autoridades. " * 3


def note(source: str, title: str, *, video: bool = False, hours_old: float = 1.0, url: str = "", body: str = BODY) -> ExtractedContent:
    assets = [Asset(kind="image", remote_url=f"https://img.test/{abs(hash(title))}.jpg")]
    if video:
        assets.append(Asset(kind="video", remote_url=f"https://vid.test/{abs(hash(title))}.mp4", duration_seconds=40.0, meta={"video_kind": "mp4"}))
    return ExtractedContent(
        source=source,
        source_type="x_video" if source == "x" else "news",
        source_item_id=url or title,
        canonical_url=url or f"https://{source}.test/{abs(hash(title))}",
        title=title,
        summary="Bajada con informacion concreta del hecho.",
        body_text=body,
        media_type="video" if video else "image",
        created_at=(datetime.now(timezone.utc) - timedelta(hours=hours_old)).replace(microsecond=0).isoformat(),
        assets=assets,
    )


class FakeLLM:
    """Relevancia: el puntaje va en el titulo como [sNN]. Caption: texto fijo sin cifras."""

    def __init__(self) -> None:
        self.relevance_calls = 0
        self.relevance_items = 0
        self.caption_calls = 0

    def relevance(self, system: str, prompt: str):
        self.relevance_calls += 1
        items = []
        for block in prompt.split("id=")[1:]:
            ident = block.split(" ", 1)[0]
            match = re.search(r"\[s(\d+)\]", block)
            score = int(match.group(1)) if match else 40
            value = score / 10
            items.append({"id": ident, "im": value, "ur": value, "ip": value, "gr": value, "nv": value, "rp": value, "pr": value,
                          "rs": 2, "ri": 0, "pn": 0, "cs": 0 if "[sinctx]" in block else 1, "t": "sociedad", "m": "prueba"})
        self.relevance_items += len(items)
        return {"items": items}, LLMUsage(model="fake", input_tokens=100, output_tokens=50)

    def caption(self, system: str, prompt: str):
        self.caption_calls += 1
        title = re.search(r"titulo_original: (.*)", prompt).group(1)
        return (
            {"titulo": title.replace("[", "").replace("]", ""), "caption": "Vecinos de la zona contaron lo que paso.\n\nLas autoridades siguen el caso.",
             "contexto_suficiente": True, "visual": {"categoria": "sociedad"}},
            LLMUsage(model="fake", input_tokens=300, output_tokens=120),
        )


class FakeMedia:
    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self.calls = 0

    def resolve_asset(self, asset: Asset) -> ResolvedVideo:
        self.calls += 1
        path = self.folder / f"v{self.calls}.mp4"
        path.write_bytes(b"0" * 1000)
        return ResolvedVideo(path=str(path), duration_seconds=40.0, width=720, height=1280, has_audio=True, source_url=asset.remote_url, kind="mp4")


class FakePublisher:
    def __init__(self, fail: Dict[str, int] | None = None) -> None:
        self.fail = dict(fail or {})
        self.calls: List[tuple] = []

    def _record(self, platform: str, package: FormattedPackage) -> PublicationRecord:
        self.calls.append((platform, package.content_key, package.caption))
        if self.fail.get(platform, 0) > 0:
            self.fail[platform] -= 1
            return PublicationRecord(platform=platform, status="failed", caption=package.caption, error_message="error de red")
        return PublicationRecord(platform=platform, status="published", platform_media_id=f"{platform}-{len(self.calls)}", caption=package.caption,
                                 post_type=package.post_type, published_at=datetime.now(timezone.utc).isoformat())

    def publish_instagram(self, package, scheduled_for=""):
        return self._record("instagram", package)

    def publish_facebook(self, package, scheduled_for=""):
        return self._record("facebook", package)

    def get_ig_publish_limit(self):
        return {"remaining": 100}

    def find_recent_publication(self, platform, caption):
        return None


class CycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="duo_cycle_"))
        env = patch.dict(os.environ, {
            "DUO_DB_PATH": str(self.tmp / "duo.sqlite3"),
            "DUO_RATE_LIMITS_PATH": str(self.tmp / "rl.json"),
            "X_VIDEO_FEED_ENABLED": "0",
            "DUO_FORMATTED_VIDEO_DIR": str(self.tmp / "reels"),
            "DUO_FORMATTED_IMAGE_DIR": str(self.tmp / "images"),
        })
        env.start()
        self.addCleanup(env.stop)
        get_settings.cache_clear()
        self.addCleanup(get_settings.cache_clear)
        self.settings = replace(get_settings(), live_publish_enabled=True, enable_duo_web=False)
        self.llm = FakeLLM()
        self.batches: List[List[ExtractedContent]] = []
        self.publisher = FakePublisher()
        self.watermarked: set = set()
        for target, fake in (
            ("jobs.pipeline.check_image", self._fake_check_image),
            ("jobs.pipeline.check_video", lambda path, brands: WatermarkVerdict("clean")),
        ):
            patcher = patch(target, side_effect=fake)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.pipeline = self._pipeline()

    # -- dobles -----------------------------------------------------------

    def _fake_check_image(self, path, brands):
        return WatermarkVerdict("watermark", "eltribuno", 30.0, "marca_de_agua:eltribuno") if Path(path).name in self.watermarked else WatermarkVerdict("clean")

    def _pipeline(self) -> DuoPipeline:
        pipeline = DuoPipeline(self.settings, relevance_call=self.llm.relevance, editorial_call=self.llm.caption, media_resolver=FakeMedia(self.tmp))
        pipeline.publisher = self.publisher
        pipeline._download_image = self._download_image  # type: ignore[assignment]
        pipeline.formatter.format_row = self._format  # type: ignore[assignment]
        pipeline.source_registry.scan_source = self._scan  # type: ignore[assignment]
        pipeline.source_registry.enabled_source_names = lambda: ["batch"]  # type: ignore[assignment]
        return pipeline

    def _download_image(self, url: str, key: str) -> str:
        path = self.tmp / f"{key}.jpg"
        path.write_bytes(b"jpg")
        return str(path)

    def _scan(self, source, max_items=None, known=None):
        rows = self.batches.pop(0) if self.batches else []
        return [row for row in rows if not (known and known(row.canonical_url))]

    def _format(self, row, *, dry_run=False):
        editorial = json.loads(row["editorial_json"])
        media = json.loads(row.get("media_json") or "{}")
        path = self.tmp / f"{row['content_key']}.jpg"
        path.write_bytes(b"x" * 5000)
        kind = "video" if (media.get("video") or {}).get("path") else "image"
        return FormattedPackage(content_key=row["content_key"], post_type="reel" if kind == "video" else "image", caption=editorial["caption"],
                                assets=[Asset(kind=kind, path=str(path), duration_seconds=40.0 if kind == "video" else None)])

    def _status(self, title_marker: str) -> str:
        with self.pipeline.store.connection() as conn:
            row = conn.execute("SELECT pipeline_status FROM content_items WHERE title LIKE ?", (f"%{title_marker}%",)).fetchone()
        return row["pipeline_status"] if row else ""

    def _published_by_group(self) -> Dict[str, int]:
        with self.pipeline.store.connection() as conn:
            rows = conn.execute("SELECT source_group, assigned_slot FROM content_items WHERE pipeline_status = 'published'").fetchall()
        counts: Dict[str, int] = {}
        for row in rows:
            counts[row["source_group"]] = counts.get(row["source_group"], 0) + 1
            counts["slot:" + str(row["assigned_slot"])] = counts.get("slot:" + str(row["assigned_slot"]), 0) + 1
        return counts

    # -- escenarios ----------------------------------------------------------

    def _big_batch(self) -> List[ExtractedContent]:
        locales = ["Corte total de agua en barrio Tres Cerritos", "Paro de colectivos de SAETA anunciado para el lunes", "Cierre del puente de avenida Bicentenario por obras",
                   "Alerta por granizo en el Valle de Lerma", "Incendio en un deposito de Cerrillos deja familias evacuadas", "Nuevo horario de atencion en hospitales de Oran",
                   "Robo a una joyeria del microcentro salteno", "Gimnasia y Tiro clasifico a la final del torneo", "Festival de folclore en Cafayate convoca miles"]
        rows = [note("eltribuno" if i % 2 else "informatesalta", f"{t} [s{80 - i}]") for i, t in enumerate(locales)]
        rows += [note("tn" if i % 2 else "infobae", f"{t} [s{90 - i}]", video=True) for i, t in enumerate(
            ["Terremoto en la cordillera deja victimas", "Explosion en una refineria de Ensenada", "Inundaciones historicas en el litoral", "Apagon masivo en el AMBA"])]
        rows += [note("paparazzi", f"{t} [s{70 - i}]", video=True) for i, t in enumerate(
            ["Wanda Nara confirmo su separacion", "Murio un reconocido actor de telenovelas", "Tini anuncio una gira por el norte", "Lali grabo un video en Salta"])]
        rows.append(note("eltribuno", "Inauguracion de una plazoleta en un barrio [s30]"))  # bajo umbral
        return rows

    def test_quotas_with_more_than_twelve_eligible(self) -> None:
        self.batches.append(self._big_batch())
        summary = self.pipeline.run_cycle(live=True, render=True)
        counts = self._published_by_group()
        # Techo 10 por ciclo: 6 locales + 2 nacionales + 2 Paparazzi (sin cupos libres).
        self.assertEqual(summary["published"], 10)
        self.assertLessEqual(counts.get("national", 0), 2)
        self.assertEqual(counts.get("slot:national", 0), 2)
        self.assertEqual(counts.get("slot:local", 0), 6)
        self.assertEqual(counts.get("slot:paparazzi", 0), 2)
        self.assertEqual(counts.get("slot:free", 0), 0)
        # Lo flojo no rellena; lo que no entro queda pendiente.
        self.assertEqual(self._status("plazoleta"), "discarded")
        self.assertEqual(self._status("Apagon masivo"), "queued")
        # Una pieza = un cupo; mismo caption en Instagram y Facebook.
        by_key: Dict[str, Dict[str, str]] = {}
        for platform, key, caption in self.publisher.calls:
            by_key.setdefault(key, {})[platform] = caption
        self.assertEqual(len(by_key), 10)
        for captions in by_key.values():
            self.assertEqual(captions["instagram"], captions["facebook"])
            self.assertLess(len(captions["instagram"]), 2000)
        # Una sola evaluacion por lote; caption solo para las 12 elegidas.
        self.assertEqual(self.llm.relevance_calls, 2)  # 18 notas en lotes de 12
        self.assertEqual(self.llm.caption_calls, 10)

    def test_source_with_little_content_does_not_get_filled(self) -> None:
        self.batches.append([note("informatesalta", "Corte de agua en zona norte [s75]"), note("eltribuno", "Acto escolar en un barrio [s20]")])
        summary = self.pipeline.run_cycle(live=True)
        self.assertEqual(summary["published"], 1)

    def test_national_without_video_never_reaches_gemini(self) -> None:
        self.batches.append([note("tn", "Debate en el Congreso por el presupuesto [s95]"), note("paparazzi", "Foto de un famoso en la playa [s95]")])
        self.pipeline.run_cycle(live=True)
        self.assertEqual(self.llm.relevance_calls, 0)
        self.assertEqual(self._status("Congreso"), "discarded")

    def test_watermark_discards_before_relevance(self) -> None:
        item = note("eltribuno", "Entrevista con una vecina de Rosario de Lerma [s90]")
        self.watermarked.add(f"{item.ensure_content_key()}.jpg")
        self.batches.append([item])
        self.pipeline.run_cycle(live=True)
        self.assertEqual(self._status("Rosario de Lerma"), "discarded")
        self.assertEqual(self.llm.relevance_calls, 0)

    def test_same_event_in_two_outlets_is_one_publication(self) -> None:
        self.batches.append([
            note("informatesalta", "Choque fatal en la ruta 9 cerca de Cerrillos: murio un motociclista [s80]"),
            note("quepasasalta", "Choque fatal en ruta 9 en Cerrillos: murio un motociclista de 30 anos [s80]"),
        ])
        summary = self.pipeline.run_cycle(live=True)
        self.assertEqual(summary["published"], 1)
        self.assertEqual(summary["duplicates"], 1)

    def test_material_update_is_tracked_as_follow_up(self) -> None:
        self.batches.append([note("informatesalta", "Choque en la ruta 34 en Rosario de la Frontera deja dos heridos de gravedad [s80]")])
        self.pipeline.run_cycle(live=True)
        self.batches.append([note("eltribuno", "Choque en Rosario de la Frontera: murio uno de los heridos y detuvieron al conductor [s80]")])
        summary = self.pipeline.run_cycle(live=True, now=datetime.now(timezone.utc) + timedelta(hours=1))
        self.assertEqual(summary["updates"], 1)
        with self.pipeline.store.connection() as conn:
            role = conn.execute("SELECT event_role FROM content_items WHERE title LIKE '%murio uno%'").fetchone()["event_role"]
        self.assertEqual(role, "update")

    def test_published_story_that_reappears_is_not_reprocessed(self) -> None:
        item = note("informatesalta", "Corte de luz programado en Villa Las Rosas [s80]", url="https://informatesalta.test/corte")
        self.batches.append([item])
        self.pipeline.run_cycle(live=True)
        self.batches.append([note("informatesalta", "Corte de luz programado en Villa Las Rosas [s80]", url="https://informatesalta.test/corte")])
        summary = self.pipeline.run_cycle(live=True, now=datetime.now(timezone.utc) + timedelta(hours=1))
        self.assertEqual(summary["ingested"], 0)
        self.assertEqual(len([c for c in self.publisher.calls if c[0] == "instagram"]), 1)

    def test_pending_survive_restart_and_expire_after_twelve_hours(self) -> None:
        famous = ["Wanda Nara rompio el silencio", "Marcelo Tinelli volvio a la tele", "Susana Gimenez viajo a Miami", "Mirtha Legrand recibio el alta", "Pampita presento a su hija"]
        rows = [note("paparazzi", f"{name} [s{70 - i}] {'Famosa numero 4' if i == 4 else ''}", video=True) for i, name in enumerate(famous)]
        self.batches.append(rows)
        self.pipeline.run_cycle(live=True)
        self.assertEqual(len({c[1] for c in self.publisher.calls}), 2)  # solo los 2 cupos de Paparazzi
        # Reinicio: instancia nueva sobre la misma base; la pendiente sigue y entra en el ciclo siguiente.
        self.pipeline = self._pipeline()
        self.assertEqual(self._status("Famosa numero 4"), "queued")
        for hour in (1, 2):
            self.pipeline.run_cycle(live=True, now=datetime.now(timezone.utc) + timedelta(hours=hour))
        self.assertEqual(self._status("Famosa numero 4"), "published")

    def test_pending_expires_and_is_never_published(self) -> None:
        titles = ["Terremoto en Mendoza deja edificios danados", "Incendio forestal arrasa hectareas en Cordoba", "Catastrofe numero 2 inundacion en Corrientes evacuados"]
        self.batches.append([note("tn", f"{t} [s{90 - i}]", video=True) for i, t in enumerate(titles)])
        self.pipeline.run_cycle(live=True)
        self.assertEqual(self._status("Catastrofe numero 2"), "queued")
        with self.pipeline.store.connection() as conn:
            entered = conn.execute("SELECT queue_entered_at, queue_expires_at FROM content_items WHERE title LIKE '%numero 2%'").fetchone()
        self.assertEqual(datetime.fromisoformat(entered["queue_expires_at"]) - datetime.fromisoformat(entered["queue_entered_at"]), timedelta(hours=12))
        self.pipeline.run_cycle(live=True, now=datetime.now(timezone.utc) + timedelta(hours=12, minutes=5))
        self.assertEqual(self._status("Catastrofe numero 2"), "expired")
        self.assertFalse(any("numero 2" in c[2] or c[1] == "x" for c in self.publisher.calls if "Catastrofe numero 2" in c[2]))

    def test_instagram_ok_facebook_fails_is_completed_without_duplicates(self) -> None:
        self.publisher.fail = {"facebook": 1}
        self.batches.append([note("informatesalta", "Cortes de transito por la procesion del Milagro [s85]")])
        self.pipeline.run_cycle(live=True)
        self.assertEqual(self._status("procesion"), "scheduled")
        self.pipeline = self._pipeline()  # reinicio en el medio
        self.pipeline.run_cycle(live=True, now=datetime.now(timezone.utc) + timedelta(hours=1))
        platforms = [c[0] for c in self.publisher.calls]
        self.assertEqual(platforms.count("instagram"), 1)
        self.assertEqual(platforms.count("facebook"), 2)
        self.assertEqual(self._status("procesion"), "published")

    def test_x_video_without_context_is_not_published(self) -> None:
        self.batches.append([note("x", "Video [s80] [sinctx]", video=True, body="Mira esto")])
        summary = self.pipeline.run_cycle(live=True)
        self.assertEqual(summary["published"], 0)
        self.assertEqual(self._status("sinctx"), "discarded")

    def test_caption_is_cached_on_retry(self) -> None:
        self.batches.append([note("informatesalta", "Corte de agua en San Lorenzo [s80]")])
        with patch.object(self.publisher, "publish_instagram", side_effect=RuntimeError("caida")):
            self.pipeline.run_cycle(live=True)
        calls_before = self.llm.caption_calls
        self.pipeline.run_cycle(live=True, now=datetime.now(timezone.utc) + timedelta(hours=1))
        self.assertEqual(self.llm.caption_calls, calls_before)  # mismo caption, sin nueva llamada


if __name__ == "__main__":
    unittest.main()

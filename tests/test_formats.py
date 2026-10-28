"""Formatos: historias, resumen, servicio, actualizaciones, comentarios y reporte (sin red)."""
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from editorial import captions
from formats import pieces
from formats.comments import CommentResponder, looks_like_question
from formats.publish import FormatsPublisher, Outcome
from formats.report import OpsReport
from formats.runner import DryPublisher, FormatsRunner
from formats.store import FormatsStore

ART = ZoneInfo("America/Argentina/Salta")


def settings_for(tmp: Path) -> SimpleNamespace:
    return SimpleNamespace(
        base_dir=tmp, data_dir=tmp, sqlite_path=tmp / "db.sqlite3", timezone="America/Argentina/Salta", ffmpeg_path="ffmpeg",
        ig_user_id="1", ig_access_token="t", enable_instagram=True, enable_facebook=True, llm=SimpleNamespace(model="m"),
    )


class FiguresTests(unittest.TestCase):
    def test_word_and_digit_figures(self) -> None:
        self.assertEqual(pieces.figures("Avalancha deja tres montañistas muertos y 5 heridos"), {"muertos": 3, "heridos": 5})

    def test_change_between_versions(self) -> None:
        change = pieces.figure_change("Avalancha: tres montañistas muertos", "Ya son cuatro los muertos y cuatro heridos: dejó cuatro muertos")
        self.assertEqual(change, {"noun": "muertos", "before": 3, "after": 4})

    def test_no_change_without_common_figure(self) -> None:
        self.assertIsNone(pieces.figure_change("Hubo 400 evacuados", "Detuvieron a 2 personas"))


class DigestPickTests(unittest.TestCase):
    def note(self, key, relevance, category="sociedad", group="local", event=None, points=True):
        n = pieces.NoteView({"content_key": key, "relevance_score": relevance, "source_group": group, "event_key": event or key,
                             "editorial_json": '{"raw_response": {"que_se_sabe": %s, "visual": {"categoria": "%s"}}}' % ('["a"]' if points else "[]", category)},
                            Path(tempfile.gettempdir()))
        n._photo = "foto.jpg"
        return n

    def test_one_per_event_and_category_cap(self) -> None:
        notes = [self.note("a", 90, event="e1"), self.note("b", 85, event="e1"), self.note("c", 80), self.note("d", 75), self.note("e", 70, category="salud"), self.note("f", 60, category="deportes")]
        chosen = [n.key for n in pieces.pick_digest(notes, size=4)]
        self.assertNotIn("b", chosen)  # mismo acontecimiento que "a"
        self.assertEqual(chosen[:2], ["a", "c"])
        self.assertEqual(len(chosen), 4)

    def test_caps_national_notes(self) -> None:
        notes = [self.note(k, 90 - i, category=f"c{i}", group="national") for i, k in enumerate("abc")] + [self.note("z", 10, category="z")]
        chosen = pieces.pick_digest(notes, size=3, max_national=2)
        self.assertEqual(sum(n.group == "national" for n in chosen), 2)


class CommentFilterTests(unittest.TestCase):
    def test_questions(self) -> None:
        self.assertTrue(looks_like_question("¿A qué hora es el corte?"))
        self.assertTrue(looks_like_question("alguien sabe hasta cuando cortan la ruta"))
        self.assertFalse(looks_like_question("😢😢😢"))
        self.assertFalse(looks_like_question("Como pudo suceder una cosa así!!"))


class FakeMeta:
    def __init__(self, comments=None):
        self.comments = comments or []
        self.replies = []
        self.settings = SimpleNamespace(ig_user_id="1", ig_access_token="t", enable_instagram=True, enable_facebook=True)

    def fetch_publication_comments(self, platform, media, **_):
        return self.comments

    def reply_comments(self, platform, ids, message):
        self.replies.append((platform, list(ids), message))
        return [{"replied": True, "reply_id": "r1"}]

    def get_ig_publish_limit(self):
        return {"quota_total": 100, "quota_usage": 10, "remaining": 90}


class StoreCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="duo_fmt_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.settings = settings_for(self.tmp)
        self.store = FormatsStore(self.settings.sqlite_path)
        with self.store.connection() as conn:
            conn.executescript(
                """
                CREATE TABLE content_items (content_key TEXT, title TEXT, summary TEXT, body_text TEXT, source_group TEXT, editorial_json TEXT,
                    relevance_score REAL, event_key TEXT, event_role TEXT, source TEXT, assets_json TEXT, media_json TEXT, formatted_json TEXT,
                    pipeline_status TEXT, created_at TEXT, updated_at TEXT);
                CREATE TABLE publications (id INTEGER PRIMARY KEY, content_key TEXT, platform TEXT, status TEXT, platform_media_id TEXT,
                    platform_post_id TEXT, permalink TEXT, caption TEXT, post_type TEXT, published_at TEXT, created_at TEXT, error_message TEXT);
                CREATE TABLE analytics_snapshots (publication_id INTEGER, views INTEGER, likes INTEGER, comments INTEGER, shares INTEGER);
                CREATE TABLE cycles (cycle_id TEXT, mode TEXT, started_at TEXT, finished_at TEXT, summary_json TEXT);
                CREATE TABLE llm_usage (purpose TEXT, model TEXT, ok INTEGER, error TEXT, estimated_cost_usd REAL, created_at TEXT);
                CREATE TABLE queue_events (to_status TEXT, reason TEXT, created_at TEXT);
                """
            )
            now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            conn.execute("INSERT INTO content_items(content_key, title, body_text, source_group) VALUES ('k1', 'Corte de agua en zona sur', 'El corte es de 8 a 14 horas en barrio Santa Ana.', 'local')")
            conn.execute("INSERT INTO publications(content_key, platform, status, platform_media_id, published_at, created_at, post_type) VALUES ('k1', 'instagram', 'published', 'm1', ?, ?, 'image')", (now, now))


class CommentResponderTests(StoreCase):
    def responder(self, mode="auto", decide=None):
        meta = FakeMeta([{"id": "c1", "author_username": "vecina", "text": "¿Hasta qué hora es el corte?"}, {"id": "c2", "author_username": "x", "text": "😡😡"}])
        call = decide or (lambda system, prompt: {"items": [{"i": 0, "responder": True, "motivo": "pregunta", "respuesta": "Según la nota, de 8 a 14 horas."}]})
        cfg = {"mode": mode, "shadow_days": 3, "daily_cap": 15, "lookback_hours": 24, "exclude_groups": ["paparazzi"]}
        return CommentResponder(self.settings, meta, self.store, cfg, call=call), meta

    def test_shadow_mode_never_replies(self) -> None:
        responder, meta = self.responder()
        result = responder.run(datetime.now(ART))
        self.assertEqual(result["mode"], "shadow")
        self.assertEqual(meta.replies, [])
        rows = {r["comment_id"]: r for r in self.store.replies_since("2000")}
        self.assertEqual(rows["c1"]["decision"], "reply")
        self.assertEqual(rows["c2"]["reason"], "no_es_pregunta")

    def test_auto_goes_live_after_shadow_days(self) -> None:
        old = (datetime.now(timezone.utc) - timedelta(days=4)).replace(microsecond=0).isoformat()
        self.store.save_comment("old", platform="instagram", media_id="m0", content_key="", text="x", decision="skip", reason="", reply="", mode="shadow")
        with self.store.connection() as conn:
            conn.execute("UPDATE comment_replies SET created_at = ? WHERE comment_id = 'old'", (old,))
        responder, meta = self.responder()
        result = responder.run(datetime.now(ART))
        self.assertEqual(result["mode"], "live")
        self.assertEqual(meta.replies, [("instagram", ["c1"], "Según la nota, de 8 a 14 horas.")])

    def test_known_comments_are_not_reevaluated(self) -> None:
        calls = []
        responder, _ = self.responder(decide=lambda s, p: calls.append(p) or {"items": []})
        responder.run(datetime.now(ART))
        responder.run(datetime.now(ART))
        self.assertEqual(len(calls), 1)


class RunnerScheduleTests(StoreCase):
    def runner(self, config=None):
        runner = FormatsRunner(self.settings, FakeMeta(), config=config or {"window_hours": 3, "stories": {"max_per_day": 2}}, collect=lambda d: ({}, {}))
        runner.publisher = DryPublisher()
        return runner

    def test_failed_breaking_story_is_retried_next_cycle_on_instagram(self) -> None:
        runner = self.runner()
        sent = []
        runner.publisher.story = lambda path, platforms=(): sent.append((path, list(platforms))) or [Outcome("instagram", "story", "published", "m1")]
        now = datetime(2026, 10, 28, 9, 5, tzinfo=ART)
        failed_at = (now - timedelta(minutes=55)).astimezone(timezone.utc).isoformat()
        slot = "story-breaking:abc123"
        image = runner.out / "2026-10-28" / "story-breaking_abc123.jpg"
        image.parent.mkdir(parents=True)
        image.write_bytes(b"jpg")
        with self.store.connection() as conn:
            conn.execute("INSERT INTO format_publications (slot, kind, platform, post_type, status, error, created_at) VALUES (?, 'story-breaking', 'instagram', 'story', 'failed', 'Timeout', ?)", (slot, failed_at))
            conn.execute("INSERT INTO format_publications (slot, kind, platform, post_type, status, created_at) VALUES (?, 'story-breaking', 'facebook', 'story', 'published', ?)", (slot, failed_at))
        self.assertEqual(runner.retry_failed_stories(now), {"retry:abc123": {"instagram:story": "published"}})
        self.assertEqual(sent, [(str(image), ["instagram"])])
        self.assertIsNone(runner.retry_failed_stories(now))  # ya salio: no se repite

    def test_story_retry_gives_up_after_three_failures_or_two_hours(self) -> None:
        runner = self.runner()
        runner.publisher.story = lambda path, platforms=(): self.fail("no deberia reintentar")
        now = datetime(2026, 10, 28, 9, 5, tzinfo=ART)
        for slot, minutes, times in (("story-breaking:tres", 30, 3), ("story-breaking:vieja", 150, 1)):
            day = runner.out / "2026-10-28"
            day.mkdir(parents=True, exist_ok=True)
            (day / f"{slot.replace(':', '_')}.jpg").write_bytes(b"jpg")
            with self.store.connection() as conn:
                for _ in range(times):
                    conn.execute("INSERT INTO format_publications (slot, kind, platform, post_type, status, created_at) VALUES (?, 'story-breaking', 'instagram', 'story', 'failed', ?)",
                                 (slot, (now - timedelta(minutes=minutes)).astimezone(timezone.utc).isoformat()))
        self.assertIsNone(runner.retry_failed_stories(now))

    def test_slot_only_in_its_window_and_once(self) -> None:
        runner = self.runner()
        at = lambda h: datetime(2026, 10, 19, h, 5, tzinfo=ART)  # noqa: E731
        self.assertIsNone(runner._due("digest", at(7), hour=8))
        self.assertEqual(runner._due("digest", at(9), hour=8), "digest:2026-10-19")
        self.assertIsNone(runner._due("digest", at(11), hour=8))
        runner.store.set_run("digest:2026-10-19", "digest", "done")
        self.assertIsNone(runner._due("digest", at(9), hour=8))

    def test_daily_story_cap(self) -> None:
        runner = self.runner()
        now = datetime.now(ART)
        for i in range(2):
            runner.store.save_publication(f"s{i}", "story-post", "instagram", "story", "published")
        self.assertEqual(runner._stories_left(now), 0)
        with patch.object(runner, "_render", return_value="x.jpg"):
            self.assertEqual(runner._story("s9", "story-post", {}, now), {"skipped": "tope_diario_de_historias"})

    def test_facebook_only_note_still_counts_for_stories(self) -> None:
        # Feed de IG separado: una nota que salio solo en Facebook tambien entra a las historias, una vez por nota.
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        with self.store.connection() as conn:
            conn.execute("INSERT INTO content_items(content_key, title, source_group) VALUES ('k2', 'Robo de celulares en Salta', 'local')")
            conn.execute("INSERT INTO publications(content_key, platform, status, published_at, created_at, post_type) VALUES ('k2', 'facebook', 'published', ?, ?, 'image')", (now, now))
            conn.execute("INSERT INTO publications(content_key, platform, status, published_at, created_at, post_type) VALUES ('k1', 'facebook', 'published', ?, ?, 'image')", (now, now))
        since = datetime.now(ART) - timedelta(hours=1)
        runner = self.runner()
        self.assertEqual([n.key for n in runner._notes(since)], ["k1"])
        self.assertEqual(sorted(n.key for n in runner._notes(since, platforms=("instagram", "facebook"))), ["k1", "k2"])

    def test_services_post_only_on_new_alert(self) -> None:
        sig = FormatsRunner._services_signature
        calm = {"water": {"cuts": []}, "passes": [{"name": "Jama", "state": "ABIERTO"}]}
        cut = {"water": {"cuts": [{"zone": "Sur", "date": "2026-10-19"}]}, "passes": []}
        self.assertEqual(sig(calm), {"alerts": []})
        self.assertEqual(sig(cut), {"alerts": ["agua:Sur:2026-10-19"]})

    def test_pass_closed_outside_hours_is_normal(self) -> None:
        sig = FormatsRunner._services_signature
        # Socompa (23/10): sin horario y '24/7 off "Cerrado por temporada invernal."' en Cancilleria.
        service = {"passes": [{"name": "Jama", "state": "CERRADO", "hours": "09:00-19:15"}, {"name": "Socompa", "state": "CERRADO", "hours": ""},
                              {"name": "Sico", "state": "CERRADO", "hours": "09:00-19:00", "season_closed": True},
                              {"name": "Aguas Blancas - Bermejo", "state": "CERRADO", "hours": "24/7"}]}
        night = datetime(2026, 10, 22, 22, 0, tzinfo=ART)
        noon = datetime(2026, 10, 22, 12, 0, tzinfo=ART)
        self.assertEqual(sig(service, night), {"alerts": ["paso:Aguas Blancas - Bermejo"]})
        self.assertEqual(sig(service, noon), {"alerts": ["paso:Aguas Blancas - Bermejo", "paso:Jama"]})


EDESA_WIDGET = """<div class="outages-calendar"><h5>Octubre 2026</h5><span>Dom</span><span>Lun</span><span>22</span></div>
<div id="outages-list">
<div class="outage-card card d-none" data-date="2026-10-24" id="outage-OO-222164"><div class="outage-card-header card-header"><h2 class="mb-0">
<button class="outage-card-header-button btn" type="button"><i class="outage-icon fas fa-stop"></i><b class="outage-card-bold">ORAN Sudoeste</b> 24/10/2026 08:00</button></h2></div>
<div class="collapse"><div class="card-body">
<div><i class="fas fa-clock"></i><b class="outage-card-bold">Duración</b> 04:00:00</div>
<div><i class="fas fa-map-marker"></i><b class="outage-card-bold">Zona</b> En localidad de Oran Barrios Belgrano, Patron Costas, Pedrana</div>
<div><i class="fas fa-flag"></i><b class="outage-card-bold">Estado</b> <span class="badge">CANCELADO</span></div>
<div><i class="fas fa-comments"></i><b class="outage-card-bold">Motivo</b> Renovación de Red de media y baja Tensión</div>
</div></div></div></div>"""


class EdesaTests(unittest.TestCase):
    def test_reads_cards_not_the_calendar(self) -> None:
        from formats.sources import parse_edesa_cuts

        cuts = parse_edesa_cuts(EDESA_WIDGET)
        self.assertEqual(len(cuts), 1)
        cut = cuts[0]
        self.assertEqual((cut["branch"], cut["start"], cut["end"], cut["state"]), ("ORAN Sudoeste", "2026-10-24T08:00:00", "2026-10-24T12:00:00", "cancelado"))
        self.assertTrue(cut["zone"].startswith("En localidad de Oran"))

    def test_services_board_never_shows_raw_widget_text(self) -> None:
        power = {"cuts": [{"start": "2026-10-24T08:00:00", "state": "cancelado", "zone": "Oran"}]}
        box = pieces.services_extra(None, power, [], datetime(2026, 10, 24, 9, 0, tzinfo=ART))["power"]
        self.assertEqual(box, {"ok": True, "text": "Sin cortes programados para hoy."})


class QuakeTests(StoreCase):
    def quake(self, ident, mag, prov="SALTA", state="revisado", hours_ago=1.0):
        utc = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
        return {"id": ident, "utc": utc.isoformat(), "lat": -24.2, "lon": -67.2, "depth_km": 190, "magnitude": mag, "province": prov, "state": state}

    def test_only_new_reviewed_salta_quakes_of_magnitude_four(self) -> None:
        runner = FormatsRunner(self.settings, FakeMeta(), config={"quakes": {"min_magnitude": 4.0, "max_age_hours": 6}}, collect=lambda d: ({}, {}))
        runner.publisher = DryPublisher()
        runner._service = {"quakes": [
            self.quake("ok", 4.3),
            self.quake("chico", 3.6),
            self.quake("jujuy", 5.0, prov="JUJUY"),
            self.quake("preliminar", 4.8, state="preliminar"),
            self.quake("viejo", 4.5, hours_ago=12),
        ]}
        now = datetime.now(ART)
        with patch.object(runner, "_render", return_value="placa.jpg"):
            first = runner.quakes(now)
            second = runner.quakes(now)
        self.assertEqual(list(first), ["ok"])
        self.assertIsNone(second)  # cada sismo sale una sola vez

    def test_caption_places_epicenter(self) -> None:
        extra = pieces.quake_extra({"magnitude": 4.3, "depth_km": 192, "lat": -24.198, "lon": -67.16, "state": "sentido"}, datetime(2026, 10, 22, 21, 14))
        self.assertEqual(extra["near"], "Tolar Grande")
        caption = pieces.quake_caption(extra)
        self.assertIn("magnitud 4.3 a 49 km de Tolar Grande", caption)
        self.assertIn("Fue un sismo sentido", caption)


class ReportTests(StoreCase):
    def reporter(self, sent):
        return OpsReport(self.settings, None, self.store, {"every_days": 3, "recipient": "dueno@example.com"},
                         call=lambda s, p: {"asunto": "Todo en orden", "estado": "ok", "resumen": "Bien."}, sender=lambda to, subj, page: sent.append((to, subj)))

    def test_without_credentials_report_is_saved_pending(self) -> None:
        sent = []
        with patch.dict("os.environ", {"DUO_REPORT_SMTP_USER": "", "DUO_REPORT_SMTP_PASSWORD": ""}), patch("formats.report.is_production_machine", return_value=True):
            result = self.reporter(sent).send(datetime.now(ART))
        self.assertEqual(result["status"], "pending_credentials")
        self.assertTrue(Path(result["path"]).exists())
        self.assertEqual(sent, [])

    def test_sends_and_waits_three_days(self) -> None:
        sent = []
        env = {"DUO_REPORT_SMTP_USER": "duo@gmail.com", "DUO_REPORT_SMTP_PASSWORD": "app-pass", "DUO_REPORT_TO": ""}
        with patch.dict("os.environ", env), patch("formats.report.is_production_machine", return_value=True):
            rep = self.reporter(sent)
            self.assertTrue(rep.due(datetime.now(ART)))
            self.assertEqual(rep.send(datetime.now(ART))["status"], "sent")
            self.assertFalse(rep.due(datetime.now(ART) + timedelta(days=2)))
            self.assertTrue(rep.due(datetime.now(ART) + timedelta(days=3)))
        self.assertEqual(sent[0][0], "dueno@example.com")

    def test_never_sends_outside_production(self) -> None:
        sent = []
        with patch.dict("os.environ", {"DUO_REPORT_SMTP_USER": "a", "DUO_REPORT_SMTP_PASSWORD": "b"}), patch("formats.report.is_production_machine", return_value=False):
            self.assertEqual(self.reporter(sent).send(datetime.now(ART))["status"], "blocked_machine")
        self.assertEqual(sent, [])


class HookVariantTests(unittest.TestCase):
    def test_alternates_by_key_and_records_variant(self) -> None:
        payload = {"gancho": "🚨 A", "gancho_b": "📍 B"}
        variants = {captions.apply_hook_variant(payload, f"k{i}")["variante_gancho"] for i in range(12)}
        self.assertEqual(variants, {"A", "B"})
        b_key = next(f"k{i}" for i in range(12) if captions.apply_hook_variant(payload, f"k{i}")["variante_gancho"] == "B")
        self.assertEqual(captions.apply_hook_variant(payload, b_key)["gancho"], "📍 B")

    def test_long_or_missing_b_keeps_a(self) -> None:
        for key in ("k1", "k2", "k3", "k4"):
            self.assertEqual(captions.apply_hook_variant({"gancho": "A", "gancho_b": "x" * 200}, key)["variante_gancho"], "A")
            self.assertEqual(captions.apply_hook_variant({"gancho": "A"}, key)["gancho"], "A")


class FacebookFormatTests(unittest.TestCase):
    def test_story_uploads_unpublished_photo_then_story(self) -> None:
        calls = []

        class Meta:
            settings = SimpleNamespace(enable_instagram=False, enable_facebook=True)

            def _get_fb_page_id(self):
                return "page"

            def _get_fb_publish_token(self):
                return "tok"

            def _asset_media_url(self, asset):
                return "https://cdn/x.jpg"

            def _request(self, method, path, data=None, **_):
                calls.append((path, data))
                return {"id": "photo1"} if path.endswith("/photos") else {"success": True, "post_id": "story1"}

            def cleanup_package_assets(self, package):
                calls.append(("cleanup", None))

        outcomes = FormatsPublisher(Meta()).story("x.jpg", platforms=["facebook"])
        self.assertEqual(outcomes[0].status, "published")
        self.assertEqual(calls[0], ("/page/photos", {"url": "https://cdn/x.jpg", "published": "false"}))
        self.assertEqual(calls[1], ("/page/photo_stories", {"photo_id": "photo1"}))
        self.assertEqual(calls[-1][0], "cleanup")

    def test_dry_publisher_publishes_nothing(self) -> None:
        self.assertEqual({o.status for o in DryPublisher().post("c", ["a.jpg", "b.jpg"])}, {"dry_run"})
        self.assertIsInstance(DryPublisher().story("a.jpg")[0], Outcome)


if __name__ == "__main__":
    unittest.main()


class RecapTests(unittest.TestCase):
    def test_one_note_per_event(self) -> None:
        from types import SimpleNamespace

        from formats.pieces import one_per_event

        # 22/10: la comisaria porteña y el "va a haber motín" eran el mismo acontecimiento (n.º 1 y 2).
        notes = [SimpleNamespace(row={"event_key": k, "title": t}) for k, t in (
            ("event:e2bc", "rehén"), ("event:e2bc", "motín"), ("", "suelta 1"), ("event:3634", "Maradona"), ("", "suelta 2"))]
        self.assertEqual([n.row["title"] for n in one_per_event(notes)], ["rehén", "suelta 1", "Maradona", "suelta 2"])


class ServicePlacaTests(StoreCase):
    def runner(self) -> FormatsRunner:
        runner = FormatsRunner(self.settings, FakeMeta(), config={"window_hours": 3}, collect=lambda d: ({}, {}))
        runner.publisher = DryPublisher()
        return runner

    def test_edesa_zone_formats(self) -> None:
        z = pieces.edesa_zone
        self.assertEqual(z("LOCALIDAD: ATOCHA - Barrio: SAN RAFAEL - Barrio: LA LONJA II - ZONAS ALEDAÑAS.-", "SALTA Oeste 1"),
                         {"place": "Atocha", "detail": "San Rafael, La Lonja II y zonas aledañas"})
        self.assertEqual(z("Salta Capital: Perímetro comprendido entre calles Belgrano, Dean Funes, Vicente López y Caseros", "SALTA Centro")["detail"],
                         "Entre Belgrano, Dean Funes, Vicente López y Caseros")
        self.assertEqual(z("Sobre Ruta Nacional 81 desde km 1743", "ORAN RN81")["place"], "Orán")  # sin localidad: la de la sucursal
        self.assertIsNone(z("Sobre Ruta 9 km 10", "XYZ Norte"))
        self.assertTrue(pieces.is_major_place("Salta Capital"))
        self.assertFalse(pieces.is_major_place("Atocha"))

    def test_cut_goes_out_the_day_before_and_only_capital_to_ig(self) -> None:
        runner = self.runner()
        now = datetime(2026, 10, 24, 9, 0, tzinfo=ART)
        runner._service = {"power": {"cuts": [
            {"id": "A", "branch": "SALTA Centro", "start": "2026-10-25T08:00:00", "end": "2026-10-25T12:00:00", "zone": "Salta Capital: barrios Centro", "state": "programado", "reason": ""},
            {"id": "B", "branch": "SALTA Oeste 1", "start": "2026-10-25T08:00:00", "end": "2026-10-25T12:00:00", "zone": "LOCALIDAD: ATOCHA - Barrio: SAN RAFAEL", "state": "programado", "reason": ""},
            {"id": "C", "branch": "METAN", "start": "2026-10-27T08:00:00", "end": "2026-10-27T12:00:00", "zone": "En Metán: Barrios X", "state": "programado", "reason": ""},
        ]}}
        with patch.object(runner, "_render", return_value="placa.jpg"):
            out = runner.cuts(now)
            again = runner.cuts(now)
        self.assertEqual(sorted(out), ["cut:A", "cut:B"])  # el del 27 todavia no
        self.assertIn("instagram:image", out["cut:A"]["post"])
        self.assertNotIn("instagram:image", out["cut:B"]["post"])  # Atocha: solo Facebook + historia
        self.assertIn("facebook:image", out["cut:B"]["post"])
        self.assertIsNone(again)

    def test_pass_placa_only_for_new_in_hours_closure(self) -> None:
        runner = self.runner()
        passes = [{"name": "Jama", "country": "Chile", "state": "CERRADO", "hours": "09:00-19:15", "at": "2026-10-23 11:20:00", "note": ""}]
        runner.store.set_run("services_state:2026-10-23T10", "services_state", "done", {"signature": {"alerts": []}})
        runner._service = {"passes": passes}
        with patch.object(runner, "_render", return_value="placa.jpg"):
            out = runner.services(datetime(2026, 10, 23, 11, 30, tzinfo=ART))
            again = runner.services(datetime(2026, 10, 23, 12, 30, tzinfo=ART))
        self.assertIn("Jama", out["passes"])
        self.assertNotIn("passes", again or {})  # sigue cerrado: no se repite

    def test_payday_from_official_note(self) -> None:
        row = {"title": "Administración Pública Provincial : el sábado 31 de octubre se pagarán los sueldos y la Compensación Transitoria",
               "body_text": "El Gobierno provincial informa que el sábado 31 de octubre se hará efectivo el pago de los sueldos para Salud, Seguridad, Educación y el resto de la Administración Pública Provincial. Todos los sectores percibirán sus haberes en una misma jornada.",
               "created_at": "2026-10-21T05:58:00+00:00"}
        extra = pieces.payday_extra(row, datetime(2026, 10, 23).date())
        self.assertEqual((extra["date"], extra["daysLeft"], extra["firstWeekday"]), ("2026-10-31", 8, 3))
        self.assertEqual(extra["sectors"], ["Salud", "Seguridad", "Educación", "Resto de la Administración"])
        self.assertIsNone(pieces.payday_extra({**row, "body_text": "Salud cobra el lunes 2 de noviembre y Educación el martes 3 de noviembre."}, datetime(2026, 10, 23).date()))

    def test_anses_today_and_holiday(self) -> None:
        cal = {"groups": [
            {"group": 16, "kind": "superior", "label": "Jubilaciones y pensiones que superan el haber mínimo", "digits": ["0", "1"], "date": "2026-10-23"},
            {"group": 17, "kind": "superior", "label": "x", "digits": ["2", "3"], "date": "2026-10-26"},
        ], "valid_until": {"10": "2026-11-10"}, "resolucion": "Res. 349/2025"}
        today = datetime(2026, 10, 23).date()
        extra = pieces.anses_extra(cal, today)
        self.assertEqual(extra["groups"][0]["digits"], ["0", "1"])
        self.assertEqual(extra["upcoming"][0]["label"], "vie 26".replace("vie", "lun"))
        self.assertEqual(extra["validUntil"], "10/11")
        self.assertIsNone(pieces.anses_extra(cal, today, [{"fecha": "2026-10-23"}]))  # feriado: ANSES corre los pagos
        self.assertIsNone(pieces.anses_extra(cal, datetime(2026, 10, 24).date()))

    def test_dollar_board(self) -> None:
        quotes = [{"id": "oficial", "name": "Oficial", "buy": 1500, "sell": 1550, "prev": 1545, "updated": "2026-10-22T18:00:00.000Z"},
                  {"id": "blue", "name": "Blue", "buy": 1545, "sell": 1565, "prev": 1565, "updated": "2026-10-22T20:59:00.000Z"}]
        extra = pieces.dollar_extra(quotes, datetime(2026, 10, 23, 11, 0, tzinfo=ART))
        self.assertEqual(extra["kind"], "dollar2")
        self.assertAlmostEqual(extra["gap"], 0.9677, places=3)
        self.assertEqual(extra["updated"], "actualizado 22/10 17:59 h")
        self.assertEqual(extra["bg"]["photo"], "bg/dolar.jpg")

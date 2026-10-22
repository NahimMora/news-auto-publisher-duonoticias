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

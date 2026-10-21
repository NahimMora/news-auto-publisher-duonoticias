"""Avisos por correo de fallas puntuales (formats/alerts.py), sin red ni SMTP."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from extractors.news.common import normalize_url
from formats.alerts import FailureAlerts
from formats.store import FormatsStore

NOW = datetime(2026, 10, 20, 22, 30, tzinfo=timezone.utc)


def iso(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).isoformat()


class AlertsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="duo_alerts_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        (self.tmp / "runtime").mkdir()
        (self.tmp / "runtime" / "heartbeat.json").write_text(json.dumps({"state": "sleeping", "last_error": ""}), encoding="utf-8")
        self.settings = SimpleNamespace(data_dir=self.tmp, sqlite_path=self.tmp / "db.sqlite3", timezone="America/Argentina/Salta")
        self.store = FormatsStore(self.settings.sqlite_path)
        with self.store.connection() as conn:
            conn.executescript(
                """
                CREATE TABLE content_items (source TEXT, extracted_at TEXT);
                CREATE TABLE publications (platform TEXT, status TEXT, error_message TEXT, created_at TEXT);
                CREATE TABLE cycles (cycle_id TEXT, mode TEXT, started_at TEXT, summary_json TEXT);
                CREATE TABLE llm_usage (ok INTEGER, error TEXT, created_at TEXT);
                """
            )
            conn.execute("INSERT INTO content_items VALUES ('tn', ?), ('policiasalta', ?)", (iso(0.5), iso(60)))
        self.sent: list = []

    def alerts(self, **cfg) -> FailureAlerts:
        return FailureAlerts(self.settings, self.store, cfg, enabled_sources=["tn", "policiasalta"], free_disk_gb=lambda: 100.0,
                             quota=lambda: {"quota_usage": 83, "quota_total": 100})

    def send(self, subject: str, page: str) -> None:
        self.sent.append((subject, page))

    def keys(self, **cfg) -> set:
        return {p.key for p in self.alerts(**cfg).check(NOW)}

    def test_silent_source_is_reported(self) -> None:
        # Policia: el scraper respondia pero no entraba ninguna nota (todas tomadas como repetidas).
        self.assertEqual(self.keys(scraper_silence_hours={"default": 13, "policiasalta": 40}), {"scraper_sin_notas:policiasalta"})

    def test_failing_scraper_is_reported_after_consecutive_failures(self) -> None:
        self.store.save_scraper_result("tn", ok=False, detail="HTTP 503")
        self.assertNotIn("scraper_falla:tn", self.keys())
        self.store.save_scraper_result("tn", ok=False, detail="HTTP 503")
        self.assertIn("scraper_falla:tn", self.keys())
        self.store.save_scraper_result("tn", ok=True, items=3)
        self.assertNotIn("scraper_falla:tn", self.keys())

    def test_cycles_without_publishing_and_failed_posts(self) -> None:
        with self.store.connection() as conn:
            for i in range(3):
                conn.execute("INSERT INTO cycles VALUES (?, 'live', ?, ?)", (f"c{i}", iso(i), json.dumps({"published": 0, "allocation": {"waiting": 19}})))
            conn.execute("INSERT INTO publications VALUES ('instagram', 'failed', 'token expirado', ?)", (iso(0.5),))
            conn.execute("INSERT INTO publications VALUES ('facebook', 'failed', 'viejo', ?)", (iso(5),))
        problems = {p.key: p for p in self.alerts().check(NOW)}
        self.assertIn("sin_publicar", problems)
        self.assertIn("83 de 100", problems["sin_publicar"].detail)
        self.assertIn("publicacion_falla:instagram", problems)
        self.assertNotIn("publicacion_falla:facebook", problems)

    def test_email_once_then_repeat_then_resolved(self) -> None:
        alerts = self.alerts(repeat_hours=12)
        first = alerts.run(NOW, self.send)
        self.assertEqual(first["email"], "sent")
        self.assertIn("policiasalta", self.sent[0][0])
        # Mismo problema una hora despues: no se repite el correo.
        self.assertNotIn("email", alerts.run(NOW + timedelta(hours=1), self.send))
        self.assertEqual(len(self.sent), 1)
        # Pasadas 12 h sigue abierto: recordatorio.
        alerts.run(NOW + timedelta(hours=13), self.send)
        self.assertEqual(len(self.sent), 2)
        # Se arregla: llega "volvio a funcionar" y el estado queda limpio.
        with self.store.connection() as conn:
            conn.execute("INSERT INTO content_items VALUES ('policiasalta', ?)", (iso(-13),))
        resolved = alerts.run(NOW + timedelta(hours=14), self.send)
        self.assertEqual(resolved["resolved"], ["scraper_sin_notas:policiasalta"])
        self.assertTrue(self.sent[-1][0].startswith("✅"))
        self.assertNotIn("email", alerts.run(NOW + timedelta(hours=15), self.send))

    def test_without_smtp_nothing_is_marked_as_sent(self) -> None:
        self.assertEqual(self.alerts().run(NOW, None)["email"], "not_sent")
        self.assertEqual(self.alerts().run(NOW, self.send)["email"], "sent")

    def test_failed_send_is_retried_next_hour(self) -> None:
        def boom(subject, page):
            raise OSError("smtp caido")

        self.assertTrue(self.alerts().run(NOW, boom)["email"].startswith("failed"))
        self.assertEqual(self.alerts().run(NOW, self.send)["email"], "sent")


class NormalizeUrlTests(unittest.TestCase):
    def test_wordpress_post_id_is_kept(self) -> None:
        # Policia publica /?p=20210: sin el id todas las notas eran la portada y se tomaban como repetidas.
        self.assertEqual(normalize_url("https://prensa.policiadesalta.gob.ar/?p=20210"), "https://prensa.policiadesalta.gob.ar/?p=20210")
        self.assertNotEqual(normalize_url("https://x.gob.ar/?p=1"), normalize_url("https://x.gob.ar/?p=2"))

    def test_tracking_params_are_still_removed(self) -> None:
        self.assertEqual(normalize_url("https://tn.com.ar/a/b/?utm_source=x&fbclid=1#c"), "https://tn.com.ar/a/b")


if __name__ == "__main__":
    unittest.main()

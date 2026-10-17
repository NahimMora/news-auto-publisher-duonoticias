"""24/7 reliability: idempotent publishing, reconciliation and Meta rate limits."""
from __future__ import annotations

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from jobs.content_policy import ContentPolicy
from jobs.pipeline import DuoPipeline
from publishers.rate_limits import RateLimitRegistry, is_rate_limit_error
from storage.models import ExtractedContent, FormattedPackage, PublicationRecord, ScheduleDecision
from storage.settings import get_settings

ENV = {
    "DUO_LIVE_PUBLISH_ENABLED": "1",
    "COMPUTERNAME": "FERNANDO",
    "DUO_SAFE_MODE_DEFAULT": "0",
    "ENABLE_INSTAGRAM": "1",
    "ENABLE_FACEBOOK": "1",
    "DUO_PUBLISH_DEFAULT_MAX_POSTS": "8",
}


class ScriptedPublisher:
    """Publica o falla segun el guion por plataforma; registra llamadas."""

    def __init__(self, script: dict[str, str] | None = None, found: dict | None = None, find_error: bool = False) -> None:
        self.script = script or {}
        self.calls: list[str] = []
        self.found = found
        self.find_error = find_error

    def _record(self, platform: str, package: FormattedPackage) -> PublicationRecord:
        self.calls.append(platform)
        outcome = self.script.get(platform, "ok")
        if outcome == "ok":
            return PublicationRecord(platform=platform, status="published", platform_media_id=f"{platform}-1", caption=package.caption)
        return PublicationRecord(platform=platform, status="failed", error_message=outcome, caption=package.caption)

    def publish_instagram(self, package, scheduled_for=""):
        return self._record("instagram", package)

    def publish_facebook(self, package, scheduled_for=""):
        return self._record("facebook", package)

    def find_recent_publication(self, platform, caption):
        if self.find_error:
            raise RuntimeError("graph caido")
        return self.found if self.found is not None else {}


class ReliabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="duo_rel_")
        self.addCleanup(self.tmp.cleanup)
        env = dict(ENV, DUO_DB_PATH=str(Path(self.tmp.name) / "duo.sqlite3"))
        patcher = patch.dict(os.environ, env, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        get_settings.cache_clear()
        self.addCleanup(get_settings.cache_clear)
        self.pipeline = DuoPipeline(get_settings())
        self.pipeline.rate_limits = RateLimitRegistry(Path(self.tmp.name) / "rl.json")

    def _queue_item(self, caption: str = "Caption unico de prueba") -> str:
        now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        key = self.pipeline.store.upsert_content(
            ExtractedContent(
                source="news",
                source_type="article",
                source_item_id=caption,
                canonical_url=f"https://example.com/{abs(hash(caption))}",
                title="El Gobierno anuncio una medida politica",
                summary="El Congreso analizara el proyecto durante la jornada.",
                media_type="image",
                created_at=now,
            )
        )
        self.pipeline.store.save_formatted(key, FormattedPackage(content_key=key, post_type="image", caption=caption))
        self.pipeline.store.save_schedule(key, ScheduleDecision(scheduled_for=now, slot_label="09:00", priority_rank=1, reason="t"))
        return key

    def test_rate_limit_defers_without_burning_the_item(self) -> None:
        key = self._queue_item()
        self.pipeline.publisher = ScriptedPublisher({"instagram": "{'error': {'code': 9, 'error_subcode': 2207042}}"})  # type: ignore[assignment]
        self.pipeline.run_publisher(safe_mode=False)
        row = self.pipeline.store.find_content(key)
        statuses = self.pipeline.store.publication_statuses(key)
        self.assertEqual(row["pipeline_status"], "scheduled")  # sigue en la cola
        self.assertEqual(statuses["facebook"]["status"], "published")
        self.assertEqual(statuses["instagram"]["status"], "deferred")
        self.assertIsNotNone(self.pipeline.rate_limits.blocked_until("instagram"))

        # Mientras dure el bloqueo no se llama a Instagram ni se republica Facebook.
        publisher = ScriptedPublisher()
        self.pipeline.publisher = publisher  # type: ignore[assignment]
        self.pipeline.run_publisher(safe_mode=False)
        self.assertEqual(publisher.calls, [])

        # Vencido el bloqueo, completa solo la plataforma pendiente.
        self.pipeline.rate_limits = RateLimitRegistry(Path(self.tmp.name) / "rl2.json")
        self.pipeline.run_publisher(safe_mode=False)
        self.assertEqual(publisher.calls, ["instagram"])
        self.assertEqual(self.pipeline.store.find_content(key)["pipeline_status"], "published")

    def test_interrupted_publish_found_in_account_is_not_duplicated(self) -> None:
        key = self._queue_item()
        self.pipeline.store.mark_publication_in_flight(key, "instagram", "Caption unico de prueba", "image")
        publisher = ScriptedPublisher(found={"id": "ig-real", "permalink": "https://instagram.com/p/x"})
        self.pipeline.publisher = publisher  # type: ignore[assignment]
        self.pipeline.run_publisher(safe_mode=False)
        statuses = self.pipeline.store.publication_statuses(key)
        self.assertEqual(statuses["instagram"]["status"], "published")
        self.assertEqual(statuses["instagram"]["platform_media_id"], "ig-real")
        self.assertNotIn("instagram", publisher.calls)  # no se republico
        self.assertIn("facebook", publisher.calls)

    def test_interrupted_publish_verified_absent_is_retried(self) -> None:
        key = self._queue_item()
        self.pipeline.store.mark_publication_in_flight(key, "instagram", "Caption unico de prueba", "image")
        publisher = ScriptedPublisher(found={})
        self.pipeline.publisher = publisher  # type: ignore[assignment]
        self.pipeline.run_publisher(safe_mode=False)
        self.assertEqual(sorted(publisher.calls), ["facebook", "instagram"])
        self.assertEqual(self.pipeline.store.find_content(key)["pipeline_status"], "published")

    def test_unverifiable_interruption_waits_for_manual_retry(self) -> None:
        key = self._queue_item()
        self.pipeline.store.mark_publication_in_flight(key, "instagram", "Caption unico de prueba", "image")
        publisher = ScriptedPublisher(find_error=True)
        self.pipeline.publisher = publisher  # type: ignore[assignment]
        self.pipeline.run_publisher(safe_mode=False)
        self.assertEqual(self.pipeline.store.publication_statuses(key)["instagram"]["status"], "ambiguous")
        self.assertEqual(publisher.calls, [])
        self.assertTrue(self.pipeline.retry(key))
        self.assertEqual(self.pipeline.store.publication_statuses(key)["instagram"]["status"], "failed")


class RateLimitDetectionTests(unittest.TestCase):
    def test_detects_meta_limit_signatures(self) -> None:
        for message in (
            "{'error': {'message': '(#4) Application request limit reached', 'code': 4}}",
            "{'error': {'code': 9, 'error_subcode': 2207042}}",
            "Instagram publishing limit reached",
            "Blocked with status 429",
        ):
            self.assertTrue(is_rate_limit_error(message), message)
        self.assertFalse(is_rate_limit_error("{'error': {'code': 190, 'message': 'Invalid OAuth access token'}}"))
        self.assertFalse(is_rate_limit_error(""))

    def test_daily_cap_blocks_longer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            reg = RateLimitRegistry(Path(tmp) / "rl.json", short_minutes=30, daily_minutes=180)
            now = datetime(2026, 10, 17, 12, tzinfo=timezone.utc)
            self.assertEqual(reg.block("instagram", "2207042", now=now), now + timedelta(minutes=180))
            self.assertEqual(reg.block("facebook", "(#4) rate limit", now=now), now + timedelta(minutes=30))
            self.assertIsNone(reg.blocked_until("instagram", now=now + timedelta(minutes=181)))


class LocalNewsPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch.dict(os.environ, {"DUO_PUBLISH_REQUIRE_SAME_LOCAL_DAY": "true"}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        get_settings.cache_clear()
        self.addCleanup(get_settings.cache_clear)
        self.policy = ContentPolicy(get_settings())
        self.today = datetime.now(ZoneInfo(get_settings().timezone)).replace(hour=10, minute=0, second=0, microsecond=0).isoformat()

    def _row(self, source: str, title: str) -> dict:
        return {"source": source, "title": title, "summary": "Detalle de la nota con contexto suficiente para publicar hoy.", "media_type": "image", "created_at": self.today}

    def test_local_source_sports_story_is_accepted(self) -> None:
        decision = self.policy.evaluate_row(self._row("nuevodiariodesalta", "La atleta Milagros D'Amico conquisto la plata en el Sudamericano"))
        self.assertTrue(decision.accepted, decision.reason)
        self.assertIn("salta_local", decision.reason)

    def test_national_source_story_in_salta_is_accepted(self) -> None:
        decision = self.policy.evaluate_row(self._row("infobae", "Una leyenda del futbol llega a Salta como pastor evangelico"))
        self.assertTrue(decision.accepted, decision.reason)

    def test_national_generic_story_still_filtered(self) -> None:
        decision = self.policy.evaluate_row(self._row("infobae", "Las mejores recetas para el fin de semana largo"))
        self.assertFalse(decision.accepted)

    def test_local_gate_can_be_disabled(self) -> None:
        with patch.dict(os.environ, {"DUO_POLICY_ACCEPT_SALTA_LOCAL": "0"}):
            policy = ContentPolicy(get_settings())
        decision = policy.evaluate_row(self._row("nuevodiariodesalta", "La atleta Milagros D'Amico conquisto la plata en el Sudamericano"))
        self.assertFalse(decision.accepted)


if __name__ == "__main__":
    unittest.main()

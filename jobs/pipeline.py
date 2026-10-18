"""Ciclo horario de DUO Noticias: recopilar, seleccionar, producir y publicar.

Orden de cada ciclo (``run_cycle``), de lo barato a lo caro:

 1. Recuperacion: lo que quedo a mitad de produccion por un reinicio vuelve a la
    cola (sin reiniciar su vencimiento); se reconcilian publicaciones "en vuelo".
 2. Vencimiento: lo que espero 12 h sin cupo pasa a ``expired`` (nunca se publica).
 3. Recopilacion: fuentes activas; las URLs ya conocidas no se vuelven a bajar.
    Videos de X solo desde el intercambio de HolaSalta.
 4. Filtros tecnicos (``ContentPolicy``): fuente, validez, vigencia, video obligatorio.
 5. Acontecimientos (``jobs/events.py``): el mismo hecho de varios medios es UNA
    candidata (la mejor version); lo ya publicado solo vuelve como actualizacion.
 6. Marca de agua en la imagen principal (El Tribuno, Que Pasa Salta), local.
 7. Relevancia por lotes (una llamada cada 12 notas), en orden justo por fuente.
 8. Cola: lo que supera el umbral de su grupo queda pendiente hasta 12 h.
 9. Asignacion de cupos (``jobs/allocation.py``): maximo 12 piezas por ciclo.
10. Produccion de lo elegido: video real verificado (recorte de franja Informate,
    descarte por marca de agua), caption canonico (cache), pieza audiovisual.
11. Validacion y publicacion en Instagram y Facebook con el mismo caption,
    idempotente por plataforma.
12. Registro: transiciones, costos de IA, resultado del ciclo, articulo web preparado.

Las publicaciones reales exigen ``live=True`` + ``DUO_LIVE_PUBLISH_ENABLED=true``
en la PC de produccion; en cualquier otro caso el ciclo produce y valida pero no
publica.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence
from zoneinfo import ZoneInfo

from analytics.service import AnalyticsCollector
from editorial.service import EditorialAI
from extractors.registry import SourceRegistry
from extractors.x.service import XExtractionService, XImportError, tweet_id_from_url
from extractors.x_video_feed import XVideoFeed
from formatter.service import AssetFormatter
from growth.feedback import GrowthFeedbackService
from growth.reporting import DailyReportService
from growth.source_ranking import SourceRankingService
from growth.validation import ScoreValidationService
from jobs.allocation import Candidate, allocate
from jobs.content_policy import ContentPolicy, normalize_title_fingerprint
from jobs.events import (
    EventProbe,
    event_category,
    match_event,
    material_update_signals,
    new_event_key,
    version_quality,
)
from jobs.relevance import RelevanceEvaluator, fair_order
from publishers.duo_web import DUO_WEB_PLATFORM, build_duo_web_publisher
from publishers.meta_api import MetaGraphPublisher
from publishers.rate_limits import RateLimitRegistry, is_rate_limit_error
from publishers.web_prep import build_web_article
from storage.editorial_config import EditorialConfig, load_editorial_config
from storage.models import Asset, ExtractedContent, FormattedPackage, PublicationRecord, safe_json
from storage.settings import PipelineSettings, get_settings
from storage.sqlite_store import PipelineStore
from utils.media_resolver import MediaResolver, VideoUnavailable
from utils.watermark import check_image, check_video, handle_informate_band

# Ventana para buscar el mismo acontecimiento entre notas recientes.
EVENT_WINDOW_HOURS = 72
# Notas nuevas evaluadas por ciclo como maximo (intercaladas por fuente).
MAX_RELEVANCE_PER_CYCLE = 150
WATERMARK_BRANDS = {"eltribuno": ["eltribuno"], "quepasasalta": ["quepasasalta"]}


def cycle_id_for(moment: datetime, zone: ZoneInfo) -> str:
    """Un ciclo por hora local: 2026-10-17T15."""
    return moment.astimezone(zone).strftime("%Y-%m-%dT%H")


class DuoPipeline:
    def __init__(
        self,
        settings: PipelineSettings | None = None,
        *,
        relevance_call: Callable | None = None,
        editorial_call: Callable | None = None,
        media_resolver: MediaResolver | None = None,
        x_fetch: Callable | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.config: EditorialConfig = load_editorial_config(self.settings)
        self.store = PipelineStore(self.settings)
        self.zone = ZoneInfo(self.settings.timezone)
        self.source_registry = SourceRegistry(self.settings, self.config)
        self.x_extractor = XExtractionService(self.settings, **({"fetch": x_fetch} if x_fetch else {}))
        self.content_policy = ContentPolicy(self.settings, self.config)
        self.relevance = RelevanceEvaluator(self.config, self.settings.llm, call=relevance_call, usage_sink=self.store.record_llm_usage)
        self.editorial = EditorialAI(self.settings, self.config, call=editorial_call)
        self.formatter = AssetFormatter(self.settings)
        self.media = media_resolver or MediaResolver(
            self.settings.data_dir / "media_cache",
            ffmpeg=self.settings.ffmpeg_path,
            ffprobe=self.settings.ffprobe_path,
            min_seconds=self.config.min_video_seconds,
            max_download_mb=self.config.max_download_mb,
            max_seconds=self.config.clip_seconds * self.config.max_clips + 3,
        )
        self.rate_limits = RateLimitRegistry(
            Path(os.getenv("DUO_RATE_LIMITS_PATH") or (self.settings.data_dir / "runtime" / "meta_rate_limits.json"))
        )
        self.publisher = MetaGraphPublisher(self.settings)
        self.duo_web = build_duo_web_publisher(self.settings)
        self.analytics = AnalyticsCollector(self.store, self.publisher, self.settings)
        self.growth = GrowthFeedbackService(self.store, self.settings)
        self.source_ranking = SourceRankingService(self.store, self.settings)
        self.validator = ScoreValidationService(self.store, self.settings)
        self.reporting = DailyReportService(self.store, self.growth, self.validator, self.source_ranking, self.settings)
        self.logger = logging.getLogger("duo.pipeline")
        # La simulacion lee el intercambio de HolaSalta con un estado propio (nunca el de produccion).
        self.simulate_x_feed = False

    # ======================================================================
    # Ciclo horario
    # ======================================================================

    def run_cycle(
        self,
        *,
        live: bool = False,
        max_news: int | None = None,
        render: bool = True,
        now: datetime | None = None,
        scrape: bool = True,
    ) -> Dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        publish_enabled = bool(live and self.settings.live_publish_enabled)
        cycle_id = cycle_id_for(now, self.zone)
        started = time.monotonic()
        self.store.start_cycle(cycle_id, "live" if publish_enabled else "simulacion")
        summary: Dict[str, Any] = {
            "cycle_id": cycle_id,
            "live": publish_enabled,
            "recovered": 0,
            "expired": 0,
            "ingested": 0,
            "discarded_policy": 0,
            "duplicates": 0,
            "updates": 0,
            "watermark_discarded": 0,
            "evaluated": 0,
            "queued": 0,
            "below_threshold": 0,
            "selected": 0,
            "produced": 0,
            "published": 0,
            "production_errors": 0,
            "decisions": [],
        }
        summary["recovered"] = self._recover(cycle_id, publish_enabled=publish_enabled)
        summary["expired"] = self._expire(now)
        if scrape:
            ingest = self.run_scraper(max_news=max_news, dry_run=not publish_enabled, cycle_id=cycle_id, now=now)
            for key, value in ingest.items():
                summary[key] = summary.get(key, 0) + value
        evaluated = self._evaluate_pending(cycle_id, now=now)
        for key, value in evaluated.items():
            summary[key] = summary.get(key, 0) + value
        plan = self._allocate(cycle_id, now=now, publish_enabled=publish_enabled)
        summary["selected"] = len(plan.selected)
        summary["allocation"] = {"usage": plan.usage, "waiting": len(plan.waiting)}
        budget_deadline = started + self.config.production_budget_minutes * 60
        try:
            for item in plan.selected:
                if time.monotonic() > budget_deadline:
                    self.store.transition(item["content_key"], "queued", "sin_tiempo_en_el_ciclo:vuelve_a_la_cola", cycle_id="")
                    continue
                outcome = self._produce_and_publish(item["content_key"], cycle_id, publish_enabled=publish_enabled, render=render)
                summary["decisions"].append(outcome)
                if outcome.get("status") in {"published", "ready"}:
                    summary["produced"] += 1
                if outcome.get("status") == "published":
                    summary["published"] += 1
                if outcome.get("status") == "error":
                    summary["production_errors"] += 1
        finally:
            self.formatter.close()
        if publish_enabled:
            summary["analytics"] = self.run_analytics()
            summary["comment_actions"] = self.run_comment_engagement()
            summary["daily_reports"] = self._maybe_build_daily_report()
        summary["queue"] = self.store.queue_counts()
        summary["seconds"] = round(time.monotonic() - started, 1)
        self.store.finish_cycle(cycle_id, {k: v for k, v in summary.items() if k != "decisions"})
        return summary

    def run_pipeline(self, *, max_news: int | None = None, dry_run: bool = False, safe_mode: bool = False, **_: Any) -> Dict[str, Any]:
        """Compatibilidad con los comandos run-once / dry-run."""
        return self.run_cycle(live=not (dry_run or safe_mode), max_news=max_news, render=not dry_run)

    # -- 1) recuperacion ---------------------------------------------------

    def _recover(self, cycle_id: str, *, publish_enabled: bool) -> int:
        recovered = 0
        if publish_enabled:
            reconciled = self._reconcile_in_flight()
            if reconciled:
                self.logger.info("Publicaciones interrumpidas reconciliadas: %s", reconciled)
        for row in self.store.stranded_processing_rows(cycle_id):
            key = str(row["content_key"])
            statuses = self.store.publication_statuses(key)
            if any(str(s.get("status") or "") == "published" for s in statuses.values()):
                # Ya salio en alguna red: se completa en este ciclo sin ocupar un cupo nuevo.
                self.store.transition(key, "scheduled", "completar_plataformas_tras_reinicio", cycle_id=cycle_id)
                if publish_enabled:
                    self._publish_row(self.store.find_content(key) or row, cycle_id)
            else:
                self.store.transition(key, "queued", "reinicio:vuelve_a_la_cola", cycle_id="")
            recovered += 1
        return recovered

    # -- 2) vencimiento -----------------------------------------------------

    def _expire(self, now: datetime) -> int:
        rows = self.store.expirable_rows(now.replace(microsecond=0).isoformat())
        for row in rows:
            self.store.transition(str(row["content_key"]), "expired", f"vencida:{self.config.pending_ttl_hours:.0f}h_sin_cupo")
        return len(rows)

    # -- 3-6) recopilacion e ingreso ---------------------------------------------

    def run_scraper(
        self,
        *,
        max_news: int | None = None,
        dry_run: bool = False,
        cycle_id: str | None = None,
        now: datetime | None = None,
        **_: Any,
    ) -> Dict[str, int]:
        totals = {"ingested": 0, "discarded_policy": 0, "duplicates": 0, "updates": 0, "watermark_discarded": 0}
        if max_news == 0:
            return totals
        for source in self.source_registry.enabled_source_names():
            try:
                rows = self.source_registry.scan_source(source, max_items=max_news, known=self.store.known_url)
            except Exception as exc:  # una fuente caida no frena al resto
                self.logger.exception("Extractor %s fallo: %s", source, exc)
                continue
            for key, value in self._ingest_rows(rows, now=now).items():
                totals[key] += value
        for key, value in self._import_x_video_feed(dry_run=dry_run, now=now).items():
            totals[key] += value
        return totals

    def scan_source(self, source: str, *, max_items: int | None = None) -> int:
        return self._ingest_rows(self.source_registry.scan_source(source, max_items=max_items, known=self.store.known_url))["ingested"]

    def _import_x_video_feed(self, *, dry_run: bool = False, now: datetime | None = None) -> Dict[str, int]:
        """Videos de X del intercambio de HolaSalta (solo lectura del archivo compartido)."""
        totals = {"ingested": 0, "discarded_policy": 0, "duplicates": 0, "updates": 0, "watermark_discarded": 0}
        if not self.settings.x_video_feed_enabled or self.settings.x_video_feed_max_per_cycle <= 0:
            return totals
        if not self.config.is_enabled("x"):
            return totals
        feed = XVideoFeed(
            self.settings.x_video_feed_path,
            self.settings.x_video_feed_state_path or (self.settings.data_dir / "runtime" / "x_video_feed_state.json"),
            max_age_hours=self.settings.x_video_feed_max_age_hours,
        )
        if dry_run and not self.simulate_x_feed:
            return totals  # el estado del feed de produccion solo avanza en ciclos reales
        try:
            jobs = feed.pending_jobs()
        except Exception as exc:
            self.logger.exception("Feed de videos de X fallo: %s", exc)
            return totals
        for job_id, url in jobs[: self.settings.x_video_feed_max_per_cycle]:
            if self.store.has_source_item("x", tweet_id_from_url(url)):
                feed.mark(job_id, "skipped_duplicate")
                continue
            try:
                content = self.x_extractor.import_url(url)
            except XImportError as exc:
                feed.mark(job_id, "failed", error=str(exc))
                continue
            result = self._ingest_rows([content], now=now)
            for key, value in result.items():
                totals[key] += value
            feed.mark(job_id, "imported", content_key=content.ensure_content_key())
        return totals

    def import_x_url(self, url: str, *, dry_run: bool = False) -> str:
        content = self.x_extractor.import_url(url, dry_run=dry_run)
        self._ingest_rows([content])
        return content.ensure_content_key()

    def _ingest_rows(self, rows: Sequence[ExtractedContent], *, now: datetime | None = None) -> Dict[str, int]:
        totals = {"ingested": 0, "discarded_policy": 0, "duplicates": 0, "updates": 0, "watermark_discarded": 0}
        for content in rows:
            key = self.store.upsert_content(content)
            totals["ingested"] += 1
            group = self.config.group_of(content.source, content.source_type)
            with self.store.connection() as conn:
                conn.execute("UPDATE content_items SET source_group = ? WHERE content_key = ?", (group, key))
            row = self.store.find_content(key) or {}
            if row.get("eligibility_json"):
                continue  # ya procesada por el flujo nuevo en otro ciclo
            policy = self.content_policy.evaluate_row(row, now=now)
            self.store.transition(key, "extracted", f"politica:{policy.reason}", eligibility_json=safe_json({"policy": policy.reason}))
            if not policy.accepted:
                self.store.transition(key, "discarded", f"politica:{policy.reason}")
                totals["discarded_policy"] += 1
                continue
            role = self._track_event(row)
            if role == "duplicate":
                totals["duplicates"] += 1
                continue
            if role == "update":
                totals["updates"] += 1
            if self._image_watermark_blocks(row):
                totals["watermark_discarded"] += 1
        return totals

    def _probe(self, row: Dict[str, Any]) -> EventProbe:
        group = self.config.group_of(row.get("source"), row.get("source_type"))
        return EventProbe.build(
            str(row.get("content_key") or ""),
            str(row.get("title") or ""),
            str(row.get("summary") or ""),
            str(row.get("lead") or str(row.get("body_text") or "")[:600]),
            category=event_category(row.get("source"), row.get("canonical_url"), group),
            published_at=str(row.get("created_at") or row.get("extracted_at") or ""),
        )

    def _track_event(self, row: Dict[str, Any]) -> str:
        """Asigna la nota a un acontecimiento. Devuelve primary | update | duplicate."""
        key = str(row["content_key"])
        since = (datetime.now(timezone.utc) - timedelta(hours=EVENT_WINDOW_HOURS)).replace(microsecond=0).isoformat()
        members: Dict[str, List[EventProbe]] = {}
        for other in self.store.recent_event_members(since):
            if other.get("content_key") == key:
                continue
            members.setdefault(str(other["event_key"]), []).append(self._probe(other))
        probe = self._probe(row)
        match = match_event(probe, members)
        source = str(row.get("source") or "")
        if match is None:
            event_key = new_event_key(key)
            self.store.create_event(event_key, content_key=key, title=probe.title, category=probe.category, source=source)
            self.store.attach_to_event(key, event_key, "primary", source)
            return "primary"
        event = self.store.get_event(match.event_key) or {}
        if event.get("published_content_key"):
            signals = material_update_signals(probe.text + " " + str(row.get("body_text") or "")[:1500], str(event.get("published_text") or ""))
            if signals:
                self.store.attach_to_event(key, match.event_key, "update", source)
                self.store.update_event(match.event_key, last_update_reason=";".join(signals)[:300])
                self.store.transition(key, "extracted", f"actualizacion:{';'.join(signals)[:200]}")
                return "update"
            self.store.attach_to_event(key, match.event_key, "duplicate", source)
            self.store.transition(key, "duplicate", f"hecho_ya_publicado:{match.event_key}:{match.reason}")
            return "duplicate"
        primary_key = str(event.get("primary_content_key") or "")
        primary = self.store.find_content(primary_key) if primary_key else None
        primary_status = str((primary or {}).get("pipeline_status") or "")
        if primary is None or primary_status in {"discarded", "skipped", "filtered", "expired"}:
            # La version anterior no siguio: esta toma su lugar como candidata.
            self.store.attach_to_event(key, match.event_key, "primary", source)
            self.store.update_event(match.event_key, primary_content_key=key)
            return "primary"
        better = version_quality(row) > version_quality(primary) + 0.5
        if better and primary_status in {"extracted", "queued", "retry"}:
            self.store.attach_to_event(key, match.event_key, "primary", source)
            self.store.update_event(match.event_key, primary_content_key=key)
            self.store.attach_to_event(primary_key, match.event_key, "duplicate", str(primary.get("source") or ""))
            self.store.transition(primary_key, "duplicate", f"mejor_version:{key}")
            if primary_status in {"queued", "retry"}:
                # Hereda puntaje y vencimiento: el reloj de 12 h no se reinicia.
                with self.store.connection() as conn:
                    conn.execute(
                        """
                        UPDATE content_items SET relevance_json = ?, relevance_score = ?, relevance_version = ?,
                            score_total = ?, queue_entered_at = ?, queue_expires_at = ?
                        WHERE content_key = ?
                        """,
                        (
                            primary.get("relevance_json"), primary.get("relevance_score"), primary.get("relevance_version"),
                            primary.get("relevance_score"), primary.get("queue_entered_at"), primary.get("queue_expires_at"), key,
                        ),
                    )
                self.store.transition(key, "queued", f"reemplaza_a:{primary_key}")
            return "primary"
        self.store.attach_to_event(key, match.event_key, "duplicate", source)
        self.store.transition(key, "duplicate", f"mismo_hecho:{match.event_key}:{match.reason}")
        return "duplicate"

    def _image_watermark_blocks(self, row: Dict[str, Any]) -> bool:
        """Marca de agua en la imagen principal (solo si la nota no tiene video: si lo tiene,
        el recurso principal es el video y se revisa en produccion)."""
        source = str(row.get("source") or "")
        spec = self.config.source(source)
        if not spec or spec.watermark_policy != "discard":
            return False
        assets = self._assets(row)
        if any(a.kind == "video" for a in assets):
            return False
        image = next((a for a in assets if a.kind == "image" and (a.path or a.remote_url)), None)
        if image is None:
            return False
        local = image.path or self._download_image(image.remote_url, str(row["content_key"]))
        if not local:
            return False
        verdict = check_image(local, WATERMARK_BRANDS.get(source, []))
        self._update_eligibility(row, {"watermark": verdict.status, "watermark_score": verdict.score, "brand": verdict.brand})
        if verdict.blocks:
            # Marca clara: descarte. Caso ambiguo: queda en revision, nunca se publica solo.
            status = "review" if verdict.status == "ambiguous" else "discarded"
            self.store.transition(str(row["content_key"]), status, f"{verdict.reason}:score={verdict.score}")
            return True
        return False

    # -- 7-8) relevancia y cola --------------------------------------------------

    def _evaluate_pending(self, cycle_id: str, *, now: datetime) -> Dict[str, int]:
        totals = {"evaluated": 0, "queued": 0, "below_threshold": 0}
        pending = self.store.pending_relevance(limit=1000)
        if not pending:
            return totals
        to_score: List[Dict[str, Any]] = []
        for row in pending:
            event = self.store.get_event(str(row.get("event_key") or "")) if row.get("event_key") else None
            if event and event.get("relevance_json") and row.get("event_role") != "update":
                # El hecho ya se evaluo con otra version: se reutiliza el puntaje (sin IA).
                payload = json.loads(str(event["relevance_json"]))
                self.store.save_relevance(str(row["content_key"]), {**payload, "heredado_de_evento": True}, float(payload.get("score") or 0), str(payload.get("version") or ""))
                totals.update(self._enqueue(self.store.find_content(str(row["content_key"])) or row, payload, now=now, totals=totals))
                continue
            assets = self._assets(row)
            video = next((a for a in assets if a.kind == "video"), None)
            row = {**row, "_has_video": video is not None, "_video_seconds": video.duration_seconds if video else None}
            to_score.append(row)
        if not to_score:
            return totals
        if not self.relevance.available:
            self.logger.warning("Sin clave de IA: %s notas quedan sin evaluar (no se publica nada sin puntaje)", len(to_score))
            return totals
        batch = fair_order(to_score, MAX_RELEVANCE_PER_CYCLE)
        results = self.relevance.evaluate(batch, cycle_id=cycle_id)
        for row in batch:
            key = str(row["content_key"])
            result = results.get(key)
            if result is None:
                continue
            payload = result.as_payload(model=self.settings.llm.model, version=self.relevance.version)
            self.store.save_relevance(key, payload, result.score, self.relevance.version)
            if row.get("event_key"):
                self.store.update_event(str(row["event_key"]), relevance_score=result.score, relevance_json=safe_json(payload))
            totals["evaluated"] += 1
            totals.update(self._enqueue(self.store.find_content(key) or row, payload, now=now, totals=totals))
        return totals

    def _enqueue(self, row: Dict[str, Any], payload: Dict[str, Any], *, now: datetime, totals: Dict[str, int]) -> Dict[str, int]:
        key = str(row["content_key"])
        threshold = self.config.threshold_for(row.get("source"), row.get("source_type"))
        score = float(payload.get("score") or 0.0)
        flags = payload.get("flags") or {}
        if str(row.get("source_type") or "") == "x_video" and flags.get("contexto_suficiente") is False:
            self.store.transition(key, "discarded", "video_x_sin_contexto_suficiente")
            totals["below_threshold"] += 1
            return totals
        if score < threshold:
            self.store.transition(key, "discarded", f"bajo_umbral:{score:.0f}<{threshold:.0f}:{payload.get('motivo') or ''}")
            totals["below_threshold"] += 1
            return totals
        event = self.store.get_event(str(row.get("event_key") or "")) if row.get("event_key") else None
        entered = str((event or {}).get("first_eligible_at") or row.get("queue_entered_at") or now.replace(microsecond=0).isoformat())
        expires = (datetime.fromisoformat(entered) + timedelta(hours=self.config.pending_ttl_hours)).isoformat()
        if event and not event.get("first_eligible_at"):
            self.store.update_event(str(row["event_key"]), first_eligible_at=entered)
        self.store.transition(key, "queued", f"pendiente:score={score:.0f}>= {threshold:.0f}", queue_entered_at=entered, queue_expires_at=expires)
        totals["queued"] += 1
        return totals

    # -- 9) asignacion -------------------------------------------------------------

    def _allocate(self, cycle_id: str, *, now: datetime, publish_enabled: bool):
        rows = self.store.queue_rows_for_allocation(now.replace(microsecond=0).isoformat())
        used: Dict[str, int] = {}
        blocked_events: List[str] = []
        for row in self.store.rows_in_cycle(cycle_id):
            if str(row.get("pipeline_status") or "") in {"selected", "editorialized", "formatted", "scheduled", "publishing", "published"}:
                slot = str(row.get("assigned_slot") or "")
                used[slot] = used.get(slot, 0) + 1
                if row.get("event_key"):
                    blocked_events.append(str(row["event_key"]))
        candidates = []
        for row in rows:
            flags = (json.loads(str(row.get("relevance_json") or "{}")) or {}).get("flags") or {}
            candidates.append(
                Candidate(
                    content_key=str(row["content_key"]),
                    group=self.config.group_of(row.get("source"), row.get("source_type")),
                    source=str(row.get("source") or ""),
                    score=float(row.get("relevance_score") or 0.0),
                    threshold=self.config.threshold_for(row.get("source"), row.get("source_type")),
                    event_key=str(row.get("event_key") or ""),
                    salta_related=int(flags.get("relacion_salta") or 0) >= 2,
                    queue_entered_at=str(row.get("queue_entered_at") or ""),
                    title=str(row.get("title") or ""),
                )
            )
        plan = allocate(candidates, self.config, used=used, capacity_left=self._capacity_left(now, publish_enabled), blocked_events=blocked_events)
        for item in plan.selected:
            self.store.transition(item["content_key"], "selected", plan.reasons.get(item["content_key"], ""), cycle_id=cycle_id, assigned_slot=item["slot"])
        return plan

    def _capacity_left(self, now: datetime, publish_enabled: bool) -> Optional[int]:
        caps: List[int] = []
        if self.config.max_pieces_per_day > 0:
            midnight = now.astimezone(self.zone).replace(hour=0, minute=0, second=0, microsecond=0)
            caps.append(max(0, self.config.max_pieces_per_day - self.store.pieces_published_since(midnight.astimezone(timezone.utc).isoformat())))
        if publish_enabled and self.settings.enable_instagram:
            try:
                remaining = self.publisher.get_ig_publish_limit().get("remaining")
                if isinstance(remaining, int):
                    caps.append(max(0, remaining))
            except Exception as exc:
                self.logger.warning("No se pudo leer el limite de publicacion de Instagram: %s", exc)
        return min(caps) if caps else None

    # -- 10-12) produccion y publicacion ---------------------------------------------

    def _produce_and_publish(self, content_key: str, cycle_id: str, *, publish_enabled: bool, render: bool) -> Dict[str, Any]:
        row = self.store.find_content(content_key) or {}
        outcome: Dict[str, Any] = {"content_key": content_key, "title": row.get("title"), "source": row.get("source"), "slot": row.get("assigned_slot")}
        try:
            media = self._prepare_media(row, render=render)
            if media.get("discard"):
                self.store.transition(content_key, "review" if media.get("review") else "discarded", media["discard"])
                self._promote_alternative(row)
                return {**outcome, "status": "discarded", "reason": media["discard"]}
            row = self.store.find_content(content_key) or row
            editorial = self.editorial.generate(
                row,
                extra_text=str(media.get("video_text") or ""),
                update=row.get("event_role") == "update",
                usage_sink=self.store.record_llm_usage,
                cycle_id=cycle_id,
            )
            if not editorial.publish:
                self.store.save_editorial(content_key, editorial, status="discarded")
                self.store.transition(content_key, "discarded", f"redaccion:{editorial.reason}")
                return {**outcome, "status": "discarded", "reason": editorial.reason}
            self.store.save_editorial(content_key, editorial)
            row = self.store.find_content(content_key) or row
            if not render:
                package = self.formatter.format_row(row, dry_run=True)
                self.store.transition(content_key, "queued" if not publish_enabled else "editorialized", "simulacion:sin_render", cycle_id="" if not publish_enabled else cycle_id)
                return {**outcome, "status": "ready", "post_type": package.post_type, "caption": editorial.caption, "simulated": True}
            package = self._reuse_or_format(row)
            self.store.save_formatted(content_key, package)
            block = self._formatted_publish_block_reason(self.store.find_content(content_key) or row)
            if block:
                raise RuntimeError(f"validacion:{block}")
            if self._already_published_like(row):
                self.store.transition(content_key, "duplicate", "validacion:ya_publicado_similar")
                return {**outcome, "status": "discarded", "reason": "ya_publicado_similar"}
            self.store.transition(content_key, "scheduled", "lista_para_publicar", cycle_id=cycle_id, assigned_time=datetime.now(timezone.utc).replace(microsecond=0).isoformat())
            if not publish_enabled:
                # Simulacion: la pieza queda producida y validada, pero no sale ni ocupa cupo real.
                self.store.transition(content_key, "queued", "simulacion:producida_no_publicada", cycle_id="")
                return {**outcome, "status": "ready", "post_type": package.post_type, "caption": package.caption, "assets": [a.path for a in package.assets]}
            published = self._publish_row(self.store.find_content(content_key) or row, cycle_id)
            return {**outcome, "status": "published" if published else "pending_platforms", "post_type": package.post_type}
        except Exception as exc:
            self.logger.exception("Produccion fallida %s: %s", content_key, exc)
            retries = int(row.get("retry_count") or 0) + 1
            with self.store.connection() as conn:
                conn.execute("UPDATE content_items SET retry_count = ? WHERE content_key = ?", (retries, content_key))
            if retries >= self.config.max_retries:
                self.store.transition(content_key, "discarded", f"reintentos_agotados:{str(exc)[:200]}")
                self._promote_alternative(row)
            else:
                self.store.transition(content_key, "retry", f"error_recuperable:{str(exc)[:200]}", cycle_id="")
            return {**outcome, "status": "error", "reason": str(exc)[:300]}

    def _prepare_media(self, row: Dict[str, Any], *, render: bool) -> Dict[str, Any]:
        """Video real verificado; si no hay, imagen (solo donde la fuente lo permite)."""
        key = str(row["content_key"])
        source = str(row.get("source") or "")
        spec = self.config.source(source)
        requires_video = self.config.requires_video(source) or str(row.get("source_type") or "") == "x_video"
        existing = json.loads(str(row.get("media_json") or "{}") or "{}")
        cached_video = existing.get("video") if isinstance(existing.get("video"), dict) else {}
        cached_path = str(cached_video.get("path") or "")
        if cached_path and not cached_video.get("simulated") and Path(cached_path).is_file():
            return existing  # video ya verificado en un ciclo anterior: no se vuelve a bajar
        videos = [a for a in self._assets(row) if a.kind == "video"]
        failures: List[str] = []
        for asset in videos:
            if not render and asset.duration_seconds:
                # Simulacion sin render: se usa la duracion declarada, sin descargar.
                media = {"video": {"path": "", "duration_seconds": asset.duration_seconds, "kind": asset.meta.get("video_kind"), "simulated": True}}
                self._save_media(key, media)
                return media
            try:
                resolved = self.media.resolve_asset(asset)
            except VideoUnavailable as exc:
                failures.append(f"{asset.meta.get('video_kind') or 'video'}:{exc.reason}")
                continue
            path = resolved.path
            if spec and spec.watermark_policy == "informate_band":
                try:
                    path, band = handle_informate_band(path, str(Path(path).with_name(Path(path).stem + "_sinfranja.mp4")), ffmpeg=self.settings.ffmpeg_path)
                except RuntimeError as exc:
                    failures.append(str(exc))
                    continue
            elif spec and spec.watermark_policy == "discard":
                verdict = check_video(path, WATERMARK_BRANDS.get(source, []))
                if verdict.blocks:
                    return {"discard": f"{verdict.reason}:video:score={verdict.score}", "review": verdict.status == "ambiguous"}
            media = {"video": {"path": path, "duration_seconds": resolved.duration_seconds, "kind": resolved.kind,
                               "width": resolved.width, "height": resolved.height, "has_audio": resolved.has_audio},
                     "video_text": resolved.text, "failures": failures}
            self._save_media(key, media)
            return media
        if requires_video:
            return {"discard": "video_inutilizable:" + (",".join(failures) or "sin_video")}
        media = {"video": None, "failures": failures, "fallback": "imagen" if failures else ""}
        if failures and spec and spec.watermark_policy == "discard" and self._image_watermark_blocks(row):
            return {"discard": "marca_de_agua_en_imagen_alternativa"}
        self._save_media(key, media)
        return media

    def _save_media(self, content_key: str, media: Dict[str, Any]) -> None:
        with self.store.connection() as conn:
            conn.execute("UPDATE content_items SET media_json = ? WHERE content_key = ?", (safe_json(media), content_key))

    def _reuse_or_format(self, row: Dict[str, Any]) -> FormattedPackage:
        """Un reintento de publicacion no vuelve a renderizar si los archivos siguen ahi."""
        payload = self._load_json(row.get("formatted_json"))
        if payload and not (payload.get("meta") or {}).get("dry_run"):
            package = self._formatted_from_row(row)
            current_caption = str(self._load_json(row.get("editorial_json")).get("caption") or "")
            # Solo si la pieza corresponde al caption validado actual (nunca un paquete del flujo viejo).
            if package.caption == current_caption and package.assets and all(a.path and Path(a.path).exists() for a in package.assets):
                return package
        return self.formatter.format_row(row, dry_run=False)

    def _promote_alternative(self, row: Dict[str, Any]) -> None:
        """Si la version elegida de un hecho no sirvio (sin video, marca de agua), pasa la siguiente."""
        event_key = str(row.get("event_key") or "")
        if not event_key:
            return
        alternatives = [m for m in self.store.event_members(event_key) if m.get("pipeline_status") == "duplicate" and m.get("content_key") != row.get("content_key")]
        if not alternatives:
            return
        best = max(alternatives, key=lambda m: version_quality(m))
        if self.content_policy.evaluate_row(best).accepted:
            self.store.attach_to_event(str(best["content_key"]), event_key, "primary", str(best.get("source") or ""))
            self.store.update_event(event_key, primary_content_key=str(best["content_key"]))
            self.store.transition(str(best["content_key"]), "extracted", f"promovida_por_falla_de:{row.get('content_key')}")

    def _publish_row(self, row: Dict[str, Any], cycle_id: str) -> bool:
        content_key = str(row["content_key"])
        target_platforms = self._enabled_publish_platforms()
        if not target_platforms:
            return False
        statuses = self.store.publication_statuses(content_key)
        if any(str(statuses.get(p, {}).get("status") or "") == "ambiguous" for p in target_platforms):
            return False  # interrumpida sin evidencia: reintento manual, nunca duplicar
        pending = [p for p in target_platforms if str(statuses.get(p, {}).get("status") or "") not in {"published", "in_flight"}]
        blocked = [p for p in pending if self.rate_limits.blocked_until(p)]
        pending = [p for p in pending if p not in blocked]
        package = self._formatted_from_row(row)
        rate_limited: List[str] = []
        for result in self._publish_platform_records(package, scheduled_for=str(row.get("assigned_time") or ""), platforms=pending):
            if result.status != "published" and is_rate_limit_error(result.error_message):
                self.rate_limits.block(result.platform, result.error_message or "")
                rate_limited.append(result.platform)
                self.store.resolve_publication(content_key, result.platform, status="deferred", error_message=str(result.error_message or "")[:500])
                continue
            self.store.save_publication(content_key, result)
        self.store.refresh_content_publish_state(content_key, target_platforms)
        final = self.store.publication_statuses(content_key)
        done = all(str(final.get(p, {}).get("status") or "") == "published" for p in target_platforms)
        if done:
            self.store.transition(content_key, "published", "publicada:" + ",".join(target_platforms), cycle_id=cycle_id)
            self._after_publish(self.store.find_content(content_key) or row)
        else:
            reason = f"plataformas_pendientes:{','.join(sorted(set(blocked + rate_limited)) or [p for p in target_platforms if str(final.get(p, {}).get('status')) != 'published'])}"
            partially_out = any(str(s.get("status")) == "published" for s in final.values())
            # Ya salio en una red (o espera un limite de tasa): se completa la plataforma
            # pendiente sin ocupar un cupo nuevo. Si no salio en ninguna, vuelve a reintento.
            next_status = "scheduled" if partially_out or blocked or rate_limited else "retry"
            self.store.transition(content_key, next_status, reason, cycle_id=cycle_id)
        return done

    def _after_publish(self, row: Dict[str, Any]) -> None:
        event_key = str(row.get("event_key") or "")
        if event_key:
            event = self.store.get_event(event_key) or {}
            text = " ".join(str(row.get(k) or "") for k in ("title", "summary")) + " " + str(row.get("body_text") or "")[:1500]
            self.store.update_event(
                event_key,
                published_content_key=str(row["content_key"]),
                published_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                published_text=(str(event.get("published_text") or "") + " " + text)[-6000:],
                update_count=int(event.get("update_count") or 0) + (1 if row.get("event_role") == "update" else 0),
            )
        if self.settings.web_prepare_articles and event_key:
            try:
                article = build_web_article(row, self._load_json(row.get("editorial_json")), self._load_json(row.get("formatted_json")), self.config)
                if self.store.slug_taken(article["slug"], event_key):
                    article["slug"] = f"{article['slug']}-{str(row['content_key'])[:4]}"
                self.store.upsert_web_article(article)
            except Exception as exc:
                self.logger.warning("No se pudo preparar el articulo web de %s: %s", row.get("content_key"), exc)

    # ======================================================================
    # Publicacion manual y utilidades (CLI)
    # ======================================================================

    def preview_publications(self, *, max_posts: int | None = None, safe_mode: bool = False) -> List[Dict[str, object]]:
        rows = self.store.queue_rows_for_allocation(datetime.now(timezone.utc).replace(microsecond=0).isoformat())
        return self._publication_preview(rows[: max_posts or self.config.max_per_cycle])

    def preview_publication(self, content_key: str) -> Dict[str, object]:
        row = self.store.find_content(content_key)
        if not row:
            return {"error": "not_found", "content_key": content_key}
        preview = self._publication_preview([row])[0]
        preview["caption"] = (row.get("final_caption") or "")[:500]
        preview["formatted"] = bool(row.get("formatted_json"))
        preview["status"] = row.get("pipeline_status")
        return preview

    def publish_now(self, content_key: str, *, live: bool = False, platform: str = "both", force: bool = False) -> Dict[str, object]:
        row = self.store.find_content(content_key)
        if not row:
            return {"live": False, "error": "not_found", "content_key": content_key}
        preview = self.preview_publication(content_key)
        if not live or not self.settings.live_publish_enabled:
            return {"live": False, "blocked_reason": "safe_preview", "preview": preview}
        block_reason = self._formatted_publish_block_reason(row)
        if block_reason:
            return {"live": False, "blocked_reason": block_reason, "preview": preview}
        requested = self._requested_platforms(platform)
        if not force:
            statuses = self.store.publication_statuses(content_key)
            requested = [p for p in requested if str(statuses.get(p, {}).get("status") or "") != "published"]
            if not requested:
                return {"live": False, "blocked_reason": "already_published", "preview": preview}
        package = self._formatted_from_row(row)
        scheduled_for = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        results, ids = [], []
        for result in self._publish_platform_records(package, scheduled_for=scheduled_for, platforms=requested):
            ids.append(self.store.save_publication(content_key, result))
            results.append(result.as_dict())
        self.store.refresh_content_publish_state(content_key, self._requested_platforms(platform))
        return {"live": True, "publication_ids": ids, "results": results, "preview": preview}

    def upcoming_publications(self, *, limit: int = 3) -> List[Dict[str, object]]:
        return self.preview_publications(max_posts=limit)

    def run_publisher(self, **_: Any) -> int:
        """Publica lo que quedo listo (scheduled) en este ciclo; respeta la idempotencia."""
        if not self.settings.live_publish_enabled:
            self.logger.warning("Publicacion bloqueada: DUO_LIVE_PUBLISH_ENABLED=0")
            return 0
        cycle_id = cycle_id_for(datetime.now(timezone.utc), self.zone)
        self._reconcile_in_flight()
        published = 0
        for row in self.store.rows_by_status("scheduled", limit=50):
            published += int(self._publish_row(row, cycle_id))
        return published

    def _reconcile_in_flight(self) -> Dict[str, int]:
        """Resuelve publicaciones que quedaron "en vuelo" por una caida.

        - Caption encontrado en la cuenta -> published (con su id): sin duplicar.
        - Verificado que no esta -> failed (se puede reintentar).
        - No se pudo verificar -> ambiguous (requiere `retry` manual).
        """
        summary = {"published": 0, "failed": 0, "ambiguous": 0}
        finder = getattr(self.publisher, "find_recent_publication", None)
        for row in self.store.list_in_flight_publications():
            content_key = str(row.get("content_key") or "")
            platform = str(row.get("platform") or "")
            try:
                if not callable(finder):
                    raise RuntimeError("publicador sin reconciliacion")
                found = finder(platform, str(row.get("caption") or ""))
            except Exception as exc:
                self.store.resolve_publication(content_key, platform, status="ambiguous", error_message=f"reconciliacion_pendiente: {exc}"[:500])
                summary["ambiguous"] += 1
                continue
            if found and found.get("id"):
                self.store.resolve_publication(content_key, platform, status="published", media_id=found["id"], permalink=found.get("permalink", ""))
                summary["published"] += 1
            else:
                self.store.resolve_publication(content_key, platform, status="failed", error_message="interrumpida_antes_de_publicar")
                summary["failed"] += 1
            self.store.refresh_content_publish_state(content_key, self._enabled_publish_platforms())
            self.store.defer_publish(content_key, "reintento_tras_interrupcion")
        return {k: v for k, v in summary.items() if v}

    def _publish_platform_records(self, package: FormattedPackage, *, scheduled_for: str, platforms: Sequence[str]) -> List[PublicationRecord]:
        """El mismo paquete (mismo caption) para cada red; el resultado se registra por plataforma."""
        records: List[PublicationRecord] = []
        cleanup_hook = getattr(self.publisher, "cleanup_package_assets", None)
        sentinel = object()
        previous_defer = package.meta.get("defer_cleanup", sentinel)
        package.meta["defer_cleanup"] = True
        try:
            for platform in platforms:
                try:
                    if platform in {"instagram", "facebook"}:
                        self.store.mark_publication_in_flight(package.content_key, platform, package.caption, package.post_type)
                    if platform == "instagram":
                        records.append(self.publisher.publish_instagram(package, scheduled_for=scheduled_for))
                    elif platform == "facebook":
                        records.append(self.publisher.publish_facebook(package, scheduled_for=scheduled_for))
                    elif platform == DUO_WEB_PLATFORM and self.duo_web is not None:
                        row = self.store.find_content(package.content_key) or {}
                        records.append(self.duo_web.publish(package, row=row, scheduled_for=scheduled_for))
                except Exception as platform_exc:
                    self.logger.warning("Platform %s publish error: %s", platform, platform_exc)
                    records.append(PublicationRecord(platform=platform, status="publish_failed", error_message=str(platform_exc), mode="live", dry_run=False))
        finally:
            if previous_defer is sentinel:
                package.meta.pop("defer_cleanup", None)
            else:
                package.meta["defer_cleanup"] = previous_defer
            if callable(cleanup_hook) and platforms:
                try:
                    cleanup_hook(package)
                except Exception:
                    pass
        return records

    def _enabled_publish_platforms(self) -> List[str]:
        platforms: List[str] = []
        if self.settings.enable_instagram:
            platforms.append("instagram")
        if self.settings.enable_facebook:
            platforms.append("facebook")
        if self.settings.enable_duo_web and self.duo_web is not None:
            platforms.append(DUO_WEB_PLATFORM)
        return platforms

    @staticmethod
    def _requested_platforms(platform: str) -> List[str]:
        value = (platform or "both").lower().strip()
        if value in {"instagram", "facebook", DUO_WEB_PLATFORM}:
            return [value]
        return ["instagram", "facebook"]

    def _formatted_publish_block_reason(self, row: Dict[str, Any]) -> str:
        """Validacion previa a publicar, valida para reels de video real y posts.

        Reemplaza el chequeo del formateador viejo que exigia una plantilla de
        layout legada (``layout_template``) y bloqueaba todos los reels del motor
        audiovisual. Ahora se verifica lo que importa: archivos reales, duraciones
        dentro de los limites de la plataforma y caption dentro del maximo.
        """
        payload = self._load_json(row.get("formatted_json"))
        if not payload:
            return "not_formatted"
        meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
        if meta.get("dry_run"):
            return "dry_run_formatted_rebuild_required"
        caption = str(payload.get("caption") or "")
        if not caption.strip():
            return "caption_vacio"
        if len(caption) >= 2000:
            return f"caption_largo:{len(caption)}"
        assets = [a for a in payload.get("assets") or [] if isinstance(a, dict)]
        if not assets:
            return "sin_assets"
        post_type = str(payload.get("post_type") or "")
        videos = [a for a in assets if a.get("kind") == "video"]
        for asset in assets:
            path = str(asset.get("path") or "")
            if not path or not Path(path).exists():
                return f"archivo_inexistente:{Path(path).name if path else '-'}"
        if post_type == "reel" and not videos:
            return "reel_sin_video_real"
        for video in videos:
            duration = float(video.get("duration_seconds") or 0.0)
            if duration and (duration < 3 or duration > (60.5 if post_type == "carousel" else 180.5)):
                return f"duracion_fuera_de_limite:{duration:.0f}s"
        return ""

    def _already_published_like(self, row: Dict[str, Any]) -> bool:
        content_key = str(row.get("content_key") or "")
        canonical_url = str(row.get("canonical_url") or "").strip().rstrip("/")
        title_fp = normalize_title_fingerprint(row.get("title"))
        for item in self.store.published_fingerprints(limit=500):
            if str(item.get("content_key") or "") == content_key:
                continue
            if canonical_url and canonical_url == str(item.get("canonical_url") or "").strip().rstrip("/"):
                return True
            other = normalize_title_fingerprint(item.get("title"))
            if title_fp and other and title_fp == other:
                return True
        return False

    def run_analytics(self) -> int:
        return len(self.analytics.collect_due_snapshots())

    def run_comment_engagement(self) -> int:
        if not self.settings.enable_comment_engagement:
            return 0
        now = datetime.now(timezone.utc).replace(microsecond=0)
        min_ts = (now - timedelta(minutes=self.settings.comment_max_age_minutes)).isoformat()
        max_ts = (now - timedelta(minutes=self.settings.comment_min_age_minutes)).isoformat()
        count = 0
        with self.store.connection() as conn:
            rows = conn.execute(
                """
                SELECT p.id, p.platform, p.platform_media_id FROM publications p
                LEFT JOIN comment_actions c ON c.publication_id = p.id
                WHERE p.platform = 'instagram' AND p.status = 'published' AND p.published_at BETWEEN ? AND ? AND c.id IS NULL
                """,
                (min_ts, max_ts),
            ).fetchall()
        for row in rows:
            try:
                actions = self.publisher.engage_instagram_comments(str(row["platform_media_id"]), self.settings.comment_reply_emoji)
            except Exception:
                continue
            for action in actions:
                self.store.save_comment_action(
                    int(row["id"]), platform="instagram", comment_id=str(action["comment_id"]),
                    author_username=str(action["author_username"]), comment_text=str(action["comment_text"]),
                    liked=bool(action["liked"]), replied=bool(action["replied"]), reply_id=str(action["reply_id"]),
                    payload=dict(action["payload"]),
                )
                count += 1
        return count

    def _maybe_build_daily_report(self) -> int:
        now = datetime.now(self.zone)
        if now.hour < 23:
            return 0
        if self.store.get_daily_report(now.date().isoformat()) or not self.store.report_publications_for_date(now.date()):
            return 0
        report = self.reporting.build_report(now.date(), write_json=True)
        return 1 if int(report.get("posts_published") or 0) > 0 else 0

    def validate_scoring(self, *, lookback_days: int = 30, checkpoint_label: str | None = "T3") -> Dict[str, object]:
        return self.validator.validate(lookback_days=lookback_days, checkpoint_label=checkpoint_label)

    def show_source_ranking(self, *, lookback_days: int | None = None) -> List[Dict[str, object]]:
        return self.source_ranking.rank_sources(lookback_days=lookback_days)

    def build_daily_report(self, *, report_date: date | None = None, write_json: bool = True) -> Dict[str, object]:
        return self.reporting.build_report(report_date, write_json=write_json)

    def show_stats(self) -> Dict[str, Any]:
        return self.store.stats_summary()

    def show_queue(self) -> List[Dict[str, Any]]:
        return self.store.queue_summary()

    def queue_rows(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self.store.queue_rows(limit=limit)

    def inspect(self, content_key: str) -> Dict[str, Any] | None:
        payload = self.store.inspect_content(content_key)
        if payload is not None:
            payload["queue_history"] = self.store.queue_history(content_key)
        return payload

    def skip(self, content_key: str, reason: str) -> bool:
        self.store.transition(content_key, "discarded", f"manual:{reason}")
        return True

    def retry(self, content_key: str) -> bool:
        return self.store.retry_content(content_key)

    def retry_failed(self) -> int:
        rows = self.store.rows_by_status("retry", limit=200)
        for row in rows:
            self.store.transition(str(row["content_key"]), "queued", "manual:retry_failed")
        return len(rows)

    def requeue_pending_for_rebuild(self) -> int:
        return self.store.requeue_unpublished_for_rebuild()

    def _min_publish_content_timestamp(self) -> str:
        hours = max(self.config.max_content_age_hours.values() or [24])
        return (datetime.now(timezone.utc) - timedelta(hours=hours)).replace(microsecond=0).isoformat()

    def llm_usage(self, *, hours: int = 24) -> List[Dict[str, Any]]:
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).replace(microsecond=0).isoformat()
        return self.store.llm_usage_summary(since)

    # -- auxiliares -------------------------------------------------------------

    def _assets(self, row: Dict[str, Any]) -> List[Asset]:
        return AssetFormatter._load_assets(row.get("assets_json"))

    def _download_image(self, url: str, content_key: str) -> str:
        from utils.image_processor import process_image

        folder = self.settings.data_dir / "media_cache" / "images"
        folder.mkdir(parents=True, exist_ok=True)
        try:
            result = process_image(url, f"{content_key}_main.jpg", str(folder))
        except Exception:
            return ""
        return str(result or "")

    def _update_eligibility(self, row: Dict[str, Any], values: Dict[str, Any]) -> None:
        current = self._load_json(row.get("eligibility_json"))
        with self.store.connection() as conn:
            conn.execute("UPDATE content_items SET eligibility_json = ? WHERE content_key = ?", (safe_json({**current, **values}), row["content_key"]))

    @staticmethod
    def _load_json(raw: object) -> Dict[str, Any]:
        try:
            payload = json.loads(str(raw or ""))
        except ValueError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _formatted_from_row(self, row: Dict[str, object]) -> FormattedPackage:
        payload = self._load_json(row.get("formatted_json"))
        assets = AssetFormatter._load_assets(json.dumps(payload.get("assets") or []))
        return FormattedPackage(
            content_key=str(row.get("content_key") or ""),
            post_type=str(payload.get("post_type") or "image"),
            caption=str(payload.get("caption") or ""),
            thumbnail_path=str(payload.get("thumbnail_path") or ""),
            assets=assets,
            meta=dict(payload.get("meta") or {}),
        )

    @staticmethod
    def _publication_preview(rows: Sequence[Dict[str, object]]) -> List[Dict[str, object]]:
        return [
            {
                "content_key": row.get("content_key"),
                "title": row.get("title"),
                "source": row.get("source"),
                "score": row.get("relevance_score"),
                "status": row.get("pipeline_status"),
                "slot": row.get("assigned_slot"),
                "queue_expires_at": row.get("queue_expires_at"),
                "post_type": row.get("assigned_post_type"),
            }
            for row in rows
        ]

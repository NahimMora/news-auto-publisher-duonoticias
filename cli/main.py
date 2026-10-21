from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import socket
import sys
import time
from contextlib import contextmanager
from datetime import date, datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, List
from zoneinfo import ZoneInfo

from jobs.pipeline import DuoPipeline
from storage.settings import get_settings
from utils import media_storage
from utils.machine_guard import is_production_machine


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AutoPublicador Duo 24/7 CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    _add_run_once(subparsers.add_parser("run-once", help="Run one pipeline cycle"))
    _add_run_once(subparsers.add_parser("dry-run", help="Run one dry-run cycle"))
    run_247 = subparsers.add_parser("run-24-7", help="Run loop with watchdog-style error isolation")
    run_247.add_argument("--interval-minutes", type=float, default=float(os.getenv("DUO_LOOP_MINUTES", "60")))
    run_247.add_argument("--max-news", type=int, default=None)
    run_247.add_argument("--max-posts", type=int, default=None)
    run_247.add_argument("--live", action="store_true")
    run_247.add_argument("--cycles", type=int, default=0, help="Optional finite cycle count for smoke tests")

    scan_sources = subparsers.add_parser("scan-sources", help="Scan enabled news sources")
    scan_sources.add_argument("--max", dest="max_items", type=int, default=None)
    scan_source = subparsers.add_parser("scan-source", help="Scan one source")
    scan_source.add_argument("--source", required=True)
    scan_source.add_argument("--max", dest="max_items", type=int, default=None)
    cycle = subparsers.add_parser("cycle", help="Run one hourly cycle (no publica sin --live en FERNANDO)")
    cycle.add_argument("--live", action="store_true")
    cycle.add_argument("--max-news", type=int, default=None)
    cycle.add_argument("--no-render", action="store_true", help="Produce caption y plan de formato sin renderizar")
    simulate = subparsers.add_parser("simulate", help="Ciclo simulado sobre una base separada (nunca publica)")
    simulate.add_argument("--db", default="", help="Base SQLite de simulacion (default data/simulation.sqlite3)")
    simulate.add_argument("--max-news", type=int, default=None)
    simulate.add_argument("--render", action="store_true", help="Renderizar las piezas elegidas")
    simulate.add_argument("--no-scrape", action="store_true", help="Solo reevaluar lo que ya esta en la base")
    usage = subparsers.add_parser("llm-usage", help="Llamadas, tokens y costo estimado de Gemini")
    usage.add_argument("--hours", type=int, default=24)
    subparsers.add_parser("queue-state", help="Conteo por estado de la cola editorial")

    import_x = subparsers.add_parser("import-x-url", help="Import one X URL (solo links puntuales, sin scraping de cuentas)")
    import_x.add_argument("--url", required=True)
    import_x.add_argument("--dry-run", action="store_true")


    publish = subparsers.add_parser("publish-pending", help="Publish due items or preview safely")
    publish.add_argument("--max-posts", type=int, default=None)
    publish.add_argument("--live", action="store_true")
    publish.add_argument("--content-type", choices=("reels", "news", "all"), default="all",
                         help="reels=X clips only, news=image/carousel only, all=unified queue")
    publish.add_argument("--force-due", action="store_true",
                         help="Ignore scheduled time and publish immediately")
    publish_now = subparsers.add_parser("publish-now", help="Publish or preview one formatted item by content key")
    publish_now.add_argument("--content-key", required=True)
    publish_now.add_argument("--platform", choices=("instagram", "facebook", "both"), default="both")
    publish_now.add_argument("--live", action="store_true")
    publish_now.add_argument("--force", action="store_true")

    subparsers.add_parser("analytics-collect", help="Collect analytics checkpoints")
    growth_report = subparsers.add_parser("growth-report", help="Build growth feedback report")
    growth_report.add_argument("--date", dest="report_date", default=None)
    growth_report.add_argument("--no-write", action="store_true")
    source_ranking = subparsers.add_parser("source-ranking", help="Show X/source ranking")
    source_ranking.add_argument("--lookback-days", type=int, default=None)

    queue = subparsers.add_parser("queue", help="Show queue")
    queue.add_argument("--format", choices=("json", "table"), default="json")
    queue.add_argument("--limit", type=int, default=50)
    inspect_cmd = subparsers.add_parser("inspect", help="Inspect one content item")
    inspect_cmd.add_argument("--content-key", required=True)
    retry_cmd = subparsers.add_parser("retry", help="Retry one content item")
    retry_cmd.add_argument("--content-key", required=True)
    skip_cmd = subparsers.add_parser("skip", help="Skip one content item")
    skip_cmd.add_argument("--content-key", required=True)
    skip_cmd.add_argument("--reason", required=True)

    subparsers.add_parser("safe-mode", help="Preview due publications without live publish")
    subparsers.add_parser("test-meta", help="Check Meta credentials without publishing")
    test_source = subparsers.add_parser("test-source", help="Scan a source with max=1")
    test_source.add_argument("--source", required=True)
    subparsers.add_parser("autorun-health", help="Check 24/7 autorun health")
    subparsers.add_parser("preflight", help="Gate for live 24/7 start: exit 1 if live publishing cannot work")
    subparsers.add_parser("doctor", help="Check runtime configuration")
    subparsers.add_parser("status", help="Show status summary")

    _add_legacy_aliases(subparsers)
    return parser


def _add_run_once(cmd: argparse.ArgumentParser) -> None:
    cmd.add_argument("--max-news", type=int, default=None)
    cmd.add_argument("--max-posts", type=int, default=None)
    cmd.add_argument("--dry-run", action="store_true")
    cmd.add_argument("--safe-mode", action="store_true")


def _add_legacy_aliases(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    legacy_pipeline = subparsers.add_parser("run-pipeline", help=argparse.SUPPRESS)
    _add_run_once(legacy_pipeline)
    legacy_scraper = subparsers.add_parser("run-scraper", help=argparse.SUPPRESS)
    legacy_scraper.add_argument("--max-news", type=int, default=None)
    legacy_publisher = subparsers.add_parser("run-publisher", help=argparse.SUPPRESS)
    legacy_publisher.add_argument("--live", action="store_true")
    legacy_publisher.add_argument("--dry-run", action="store_true")
    legacy_publisher.add_argument("--max-posts", type=int, default=None)
    legacy_publisher.add_argument("--safe-mode", action="store_true")
    subparsers.add_parser("run-analytics", help=argparse.SUPPRESS)
    subparsers.add_parser("show-stats", help=argparse.SUPPRESS)
    subparsers.add_parser("show-queue", help=argparse.SUPPRESS)
    subparsers.add_parser("retry-failed", help=argparse.SUPPRESS)
    subparsers.add_parser("requeue-pending", help=argparse.SUPPRESS)
    validation = subparsers.add_parser("validate-scoring", help=argparse.SUPPRESS)
    validation.add_argument("--lookback-days", type=int, default=30)
    validation.add_argument("--checkpoint", default="T3")
    ranking = subparsers.add_parser("show-source-ranking", help=argparse.SUPPRESS)
    ranking.add_argument("--lookback-days", type=int, default=None)
    report = subparsers.add_parser("daily-report", help=argparse.SUPPRESS)
    report.add_argument("--date", dest="report_date", default=None)
    report.add_argument("--no-write", action="store_true")

    formats = subparsers.add_parser("formats", help="Formatos (historias, resumen, servicio, top semanal...): vista previa o publicacion ahora")
    formats.add_argument("--step", action="append", required=True, help="weather_story, weather_alert_post, digest, services, holidays, dollar, recap, weekly, comments, report")
    formats.add_argument("--live", action="store_true", help="Publicar de verdad (solo FERNANDO); sin esto solo renderiza en data/formats/preview")
    ops = subparsers.add_parser("ops-report", help="Reporte de operaciones por correo")
    ops.add_argument("--send", action="store_true", help="Generar y enviar ahora")
    ops.add_argument("--watchdog", action="store_true", help="Avisar si el servicio no late y enviar el reporte si esta vencido")


def main(argv: List[str] | None = None) -> None:
    _configure_console_encoding()
    logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    args = build_parser().parse_args(argv)
    if args.command == "simulate":
        _print_json(_simulate(args))
        return
    pipeline = DuoPipeline()
    settings = pipeline.settings
    command = args.command

    if command in {"run-once", "dry-run", "run-pipeline"}:
        dry_run = command == "dry-run" or bool(getattr(args, "dry_run", False))
        safe_mode = bool(getattr(args, "safe_mode", False)) or settings.safe_mode_default
        result = pipeline.run_cycle(live=not (dry_run or safe_mode), max_news=getattr(args, "max_news", None), render=not dry_run)
        _print_json(result)
        return
    if command == "run-24-7":
        _run_247(pipeline, args)
        return
    if command == "formats":
        from formats.runner import STEPS, run_steps

        unknown = [s for s in args.step if s not in STEPS]
        if unknown:
            raise SystemExit(f"formatos desconocidos: {unknown}; opciones: {', '.join(STEPS)}")
        live = bool(args.live)
        if live and not (is_production_machine() and settings.live_publish_enabled):
            raise SystemExit("--live solo en FERNANDO con DUO_LIVE_PUBLISH_ENABLED=true")
        _print_json(run_steps(settings, pipeline.publisher, args.step, live=live, usage_sink=pipeline.store.record_llm_usage))
        return
    if command == "ops-report":
        from datetime import datetime as _dt

        from formats.report import OpsReport
        from formats.runner import load_config
        from formats.store import FormatsStore

        reporter = OpsReport(settings, pipeline.publisher, FormatsStore(settings.sqlite_path), load_config(settings.base_dir).get("report") or {},
                             usage_sink=pipeline.store.record_llm_usage)
        now = _dt.now().astimezone()
        if args.watchdog:
            _print_json(reporter.watchdog(now))
        elif args.send:
            _print_json(reporter.send(now))
        else:
            _print_json({"due": reporter.due(now), "recipient": reporter.recipient})
        return
    if command in {"scan-sources", "run-scraper"}:
        _print_json(pipeline.run_scraper(max_news=getattr(args, "max_items", None) or getattr(args, "max_news", None), dry_run=True))
        return
    if command in {"scan-source", "test-source"}:
        count = pipeline.scan_source(args.source, max_items=getattr(args, "max_items", None) or 1)
        _print_json({"source": args.source, "ingested": count})
        return
    if command == "cycle":
        _print_json(pipeline.run_cycle(live=bool(args.live), max_news=args.max_news, render=not args.no_render))
        return
    if command == "llm-usage":
        _print_json(pipeline.llm_usage(hours=args.hours))
        return
    if command == "queue-state":
        _print_json(pipeline.store.queue_counts())
        return
    if command == "import-x-url":
        key = pipeline.import_x_url(args.url, dry_run=args.dry_run)
        _print_json({"content_key": key, "url": args.url, "dry_run": args.dry_run})
        return
    if command in {"publish-pending", "run-publisher"}:
        live = bool(getattr(args, "live", False)) and settings.live_publish_enabled
        content_type = getattr(args, "content_type", "all") or "all"
        ct = None if content_type == "all" else content_type
        if not live or bool(getattr(args, "dry_run", False)) or bool(getattr(args, "safe_mode", False)):
            preview = pipeline.preview_publications(max_posts=getattr(args, "max_posts", None), safe_mode=True)
            _print_json({"live": False, "blocked_reason": "safe_preview", "content_type": content_type, "preview": preview, "count": len(preview)})
            return
        published = pipeline.run_publisher()
        analytics = pipeline.run_analytics() if published > 0 else 0
        _print_json({"live": True, "content_type": content_type, "published": published, "analytics_collected": analytics})
        return
    if command == "publish-now":
        live = bool(getattr(args, "live", False)) and settings.live_publish_enabled
        _print_json(pipeline.publish_now(args.content_key, live=live, platform=args.platform, force=args.force))
        return
    if command in {"analytics-collect", "run-analytics"}:
        _print_json({"analytics": pipeline.run_analytics()})
        return
    if command in {"growth-report", "daily-report"}:
        parsed_date = date.fromisoformat(args.report_date) if getattr(args, "report_date", None) else None
        _print_json(pipeline.build_daily_report(report_date=parsed_date, write_json=not getattr(args, "no_write", False)))
        return
    if command in {"source-ranking", "show-source-ranking"}:
        _print_json(pipeline.show_source_ranking(lookback_days=args.lookback_days))
        return
    if command in {"queue", "show-queue"}:
        rows = pipeline.queue_rows(limit=getattr(args, "limit", 50))
        if getattr(args, "format", "json") == "table":
            print(_format_table(rows))
        else:
            _print_json(rows)
        return
    if command == "inspect":
        _print_json(pipeline.inspect(args.content_key) or {"error": "not_found", "content_key": args.content_key})
        return
    if command == "retry":
        _print_json({"content_key": args.content_key, "retried": pipeline.retry(args.content_key)})
        return
    if command == "skip":
        _print_json({"content_key": args.content_key, "skipped": pipeline.skip(args.content_key, args.reason)})
        return
    if command == "safe-mode":
        preview = pipeline.preview_publications(max_posts=settings.publish_default_max_posts, safe_mode=True)
        _print_json({"safe_mode": True, "preview": preview, "count": len(preview)})
        return
    if command == "test-meta":
        _print_json(_test_meta(pipeline))
        return
    if command == "autorun-health":
        _print_json(_autorun_health(pipeline))
        return
    if command == "preflight":
        payload = _preflight(pipeline)
        _print_json(payload)
        if not payload["ok"]:
            raise SystemExit(1)
        return
    if command in {"doctor", "status"}:
        payload = _doctor(pipeline) if command == "doctor" else pipeline.show_stats()
        _print_json(payload)
        return
    if command == "validate-scoring":
        _print_json(pipeline.validate_scoring(lookback_days=args.lookback_days, checkpoint_label=args.checkpoint))
        return
    if command == "retry-failed":
        _print_json({"reset": pipeline.retry_failed()})
        return
    if command == "requeue-pending":
        _print_json({"requeued": pipeline.requeue_pending_for_rebuild()})
        return
    if command == "show-stats":
        _print_json(pipeline.show_stats())
        return


def _simulate(args: argparse.Namespace) -> dict[str, Any]:
    """Ciclo completo sobre una base de simulacion: nunca publica ni toca la base real."""
    from dataclasses import replace

    base = get_settings()
    db = Path(args.db) if args.db else base.data_dir / "simulation.sqlite3"
    settings = replace(
        base,
        sqlite_path=db,
        live_publish_enabled=False,
        enable_duo_web=False,
        # Estado propio del intercambio de HolaSalta: el archivo compartido se lee igual (solo lectura).
        x_video_feed_state_path=db.with_name(db.stem + "_x_feed_state.json"),
    )
    pipeline = DuoPipeline(settings)
    pipeline.simulate_x_feed = True
    summary = pipeline.run_cycle(live=False, max_news=args.max_news, render=bool(args.render), scrape=not args.no_scrape)
    summary["simulation_db"] = str(db)
    summary["llm_usage_last_hour"] = pipeline.llm_usage(hours=1)
    return summary


def _current_cycle_id(pipeline: DuoPipeline) -> str:
    from jobs.pipeline import cycle_id_for

    return cycle_id_for(datetime.now(timezone.utc), ZoneInfo(pipeline.settings.timezone))


def _run_247(pipeline: DuoPipeline, args: argparse.Namespace) -> None:
    safe_mode = not bool(args.live)
    logger = logging.getLogger("duo.autorun")
    _configure_runtime_file_logging(pipeline.settings)
    with _runtime_lock(pipeline.settings) as acquired:
        if not acquired:
            # Lock de proceso: nunca dos ciclos simultaneos (la tarea relanza cada 5 min).
            message = "autorun ya esta ejecutandose; se omite esta instancia"
            logger.warning(message)
            print(message)
            return
        _run_247_locked(pipeline, args, safe_mode=safe_mode)


def _run_247_locked(pipeline: DuoPipeline, args: argparse.Namespace, *, safe_mode: bool) -> None:
    """Un ciclo por hora alineado a ``cycle.align_minute``. Un ciclo lento no se pisa con el
    siguiente: se espera al proximo comienzo de hora libre."""
    logger = logging.getLogger("duo.autorun")
    cycles = 0
    try:
        while True:
            last_id = str(_read_runtime_heartbeat(pipeline.settings).get("last_cycle_id") or "")
            current = _current_cycle_id(pipeline)
            if current == last_id:
                wait = _seconds_until_next_cycle(pipeline)
                _write_runtime_heartbeat(pipeline, {"state": "waiting", "live": not safe_mode, "safe_mode": safe_mode,
                                                    "next_sleep_seconds": int(wait), "last_cycle_id": last_id, "last_error": ""})
                _log_and_print(logger, f"ciclo {current} ya corrido; esperando {int(wait)} s")
                time.sleep(wait)
                continue
            cycles += 1
            started_dt = datetime.now(timezone.utc).replace(microsecond=0)
            _log_and_print(logger, f"[{started_dt.astimezone().strftime('%Y-%m-%d %H:%M:%S')}] ciclo {current} iniciado live={not safe_mode}")
            _write_runtime_heartbeat(pipeline, {"state": "running", "cycle": cycles, "started_at": started_dt.isoformat(),
                                                "safe_mode": safe_mode, "live": not safe_mode, "last_cycle_id": last_id, "last_error": ""})
            last_error = ""
            try:
                result = pipeline.run_cycle(live=not safe_mode, max_news=args.max_news)
                _log_and_print(logger, json.dumps({k: v for k, v in result.items() if k != "decisions"}, ensure_ascii=False, default=str))
            except Exception as exc:
                last_error = str(exc)
                logger.exception("cycle failed: %s", exc)
                result = {"error": last_error}
            wait = 0 if (args.cycles and cycles >= args.cycles) else _seconds_until_next_cycle(pipeline)
            heartbeat = _heartbeat_payload(cycle=cycles, started_at=started_dt, result={k: v for k, v in result.items() if k != "decisions"},
                                           safe_mode=safe_mode, last_error=last_error, next_sleep_seconds=int(wait))
            heartbeat["last_cycle_id"] = current
            _write_runtime_heartbeat(pipeline, heartbeat)
            if args.cycles and cycles >= args.cycles:
                _log_and_print(logger, "ciclos solicitados completados")
                break
            _log_and_print(logger, f"durmiendo {int(wait)} segundos")
            time.sleep(wait)
    except KeyboardInterrupt:
        _write_runtime_heartbeat(pipeline, {"state": "stopped", "safe_mode": safe_mode, "live": not safe_mode, "last_error": "KeyboardInterrupt"})
        _log_and_print(logger, "CTRL+C recibido. Cierre limpio.")


def _seconds_until_next_cycle(pipeline: DuoPipeline) -> float:
    zone = ZoneInfo(pipeline.settings.timezone)
    now = datetime.now(zone)
    minute = int(pipeline.config.align_minute) % 60
    target = now.replace(minute=minute, second=5, microsecond=0)
    if target <= now:
        from datetime import timedelta

        target += timedelta(hours=1)
    return max(5.0, (target - now).total_seconds())


def _doctor(pipeline: DuoPipeline) -> dict[str, Any]:
    settings = pipeline.settings
    settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    dirs = [settings.data_dir, settings.output_dir, settings.formatted_video_dir, settings.formatted_image_dir, settings.backup_dir]
    for folder in dirs:
        folder.mkdir(parents=True, exist_ok=True)
    return {
        "env": {
            "llm_provider": settings.llm.provider,
            "llm_model": settings.llm.model,
            "llm_api_key": "configured" if settings.llm.ready else "missing",
            "x_video_feed": str(settings.x_video_feed_path),
            "live_publish_enabled": settings.live_publish_enabled,
            "enable_instagram": settings.enable_instagram,
            "enable_facebook": settings.enable_facebook,
            "enable_comment_engagement": settings.enable_comment_engagement,
        },
        "paths": {
            "base_dir": str(settings.base_dir),
            "sqlite_path": str(settings.sqlite_path),
            "sqlite_accessible": _sqlite_accessible(pipeline),
            "output_dir": str(settings.output_dir),
            "backup_dir": str(settings.backup_dir),
            "webapp_holasalta_path": str(settings.webapp_holasalta_path) if settings.webapp_holasalta_path else "optional_not_set",
        },
        "binaries": {
            "ffmpeg": shutil.which(settings.ffmpeg_path) or "missing",
            "ffprobe": shutil.which(settings.ffprobe_path) or "missing",
        },
        "meta": {
            "permissions_configured": list(settings.meta_permissions),
            "instagram_credentials": "configured" if settings.ig_access_token and settings.ig_user_id else "missing",
            "facebook_credentials": "configured" if settings.fb_access_token or settings.fb_page_id else "missing",
            "comment_engagement": "disabled" if not settings.enable_comment_engagement else "enabled_requires_instagram_manage_comments",
        },
        "media_storage": _media_storage_status(),
        "sources": {
            "config_path": str(settings.sources_config_path),
            "enabled": pipeline.source_registry.enabled_source_names(),
        },
        "config": {
            "thresholds_path": str(settings.thresholds_config_path),
            "editorial_policy_path": str(settings.editorial_policy_path),
            "safe_mode_default": settings.safe_mode_default,
            "editorial_scoring_path": str(settings.editorial_scoring_path),
            "cycle_minutes": pipeline.config.interval_minutes,
            "max_per_cycle": pipeline.config.max_per_cycle,
            "group_quotas": pipeline.config.group_quotas,
            "free_slots": pipeline.config.free_slots,
            "pending_ttl_hours": pipeline.config.pending_ttl_hours,
        },
        "internet": _internet_check(),
        "queue": pipeline.show_queue(),
    }


def _media_storage_status() -> dict[str, Any]:
    cfg = media_storage.get_config()
    payload: dict[str, Any] = {"provider": cfg.provider}
    if cfg.provider != "r2":
        payload.update(
            {
                "ready": bool(os.getenv("CLOUDINARY_CLOUD_NAME") and os.getenv("CLOUDINARY_API_KEY") and os.getenv("CLOUDINARY_API_SECRET")),
                "mode": "legacy_cloudinary_or_base_url",
            }
        )
        return payload
    missing = []
    if not cfg.r2_account_id and not cfg.r2_endpoint_url:
        missing.append("R2_ACCOUNT_ID")
    if not cfg.r2_bucket:
        missing.append("R2_BUCKET")
    if not cfg.r2_access_key_id:
        missing.append("R2_ACCESS_KEY_ID")
    if not cfg.r2_secret_access_key:
        missing.append("R2_SECRET_ACCESS_KEY")
    if not cfg.r2_public_base_url:
        missing.append("R2_PUBLIC_BASE_URL")
    invalid = []
    if cfg.r2_access_key_id.lower().startswith(("http://", "https://")):
        invalid.append("R2_ACCESS_KEY_ID_is_public_url")
    payload.update(
        {
            "ready": not missing and not invalid,
            "missing": missing,
            "invalid": invalid,
            "account_id": "configured" if cfg.r2_account_id else "missing",
            "endpoint_url": cfg.r2_endpoint_url or "missing",
            "bucket": "configured" if cfg.r2_bucket else "missing",
            "access_key_id": "configured" if cfg.r2_access_key_id else "missing",
            "secret_access_key": "configured" if cfg.r2_secret_access_key else "missing",
            "public_base_url": cfg.r2_public_base_url or "missing",
            "custom_domain": os.getenv("R2_CUSTOM_DOMAIN", "").strip() or "optional_not_set",
            "site_folder": cfg.r2_site_folder,
            "temp_folder": cfg.r2_temp_folder,
            "delete_after_publish": cfg.r2_delete_after_publish,
        }
    )
    return payload


def _autorun_health(pipeline: DuoPipeline) -> dict[str, Any]:
    settings = pipeline.settings
    now = datetime.now(timezone.utc).replace(microsecond=0)
    retry_limit = _safe_recovery_retry_limit()
    min_extracted_at = pipeline._min_publish_content_timestamp()
    counts = pipeline.store.autorun_health_counts(
        now.isoformat(),
        min_extracted_at=min_extracted_at,
        retry_limit=retry_limit,
    )
    heartbeat = _read_runtime_heartbeat(settings)
    issues: list[str] = []
    critical: list[str] = []

    if not settings.live_publish_enabled:
        critical.append("DUO_LIVE_PUBLISH_ENABLED=false")
    if settings.enable_instagram and not (settings.ig_access_token and settings.ig_user_id):
        critical.append("instagram_credentials_missing")
    if settings.enable_facebook and not (settings.fb_access_token and settings.fb_page_id):
        critical.append("facebook_credentials_missing")
    if not _sqlite_accessible(pipeline):
        critical.append("sqlite_unavailable")
    if shutil.which(settings.ffmpeg_path) is None:
        issues.append("ffmpeg_missing")
    if shutil.which(settings.ffprobe_path) is None:
        issues.append("ffprobe_missing")

    heartbeat_age_seconds = None
    if not heartbeat:
        issues.append("heartbeat_missing")
    else:
        heartbeat_age_seconds = _heartbeat_age_seconds(heartbeat, now)
        stale_minutes = _heartbeat_stale_minutes()
        if heartbeat_age_seconds is None:
            issues.append("heartbeat_timestamp_invalid")
        elif heartbeat_age_seconds > stale_minutes * 60:
            issues.append(f"heartbeat_stale_over_{stale_minutes}_minutes")
        if heartbeat.get("last_error"):
            issues.append("last_cycle_error_present")
        if settings.live_publish_enabled and heartbeat.get("live") is False:
            issues.append("last_heartbeat_not_live")

    if int(counts.get("retry_exhausted") or 0) > 0:
        issues.append("retry_exhausted_items_present")
    if int(counts.get("stale_unpublished") or 0) > 0:
        issues.append("stale_unpublished_items_present")

    status = "ok"
    if issues:
        status = "degraded"
    if critical:
        status = "critical"
    return {
        "status": status,
        "checked_at": now.isoformat(),
        "critical": critical,
        "issues": issues,
        "heartbeat": heartbeat or {},
        "heartbeat_age_seconds": heartbeat_age_seconds,
        "runtime": {
            "lock_path": str(_runtime_lock_path(settings)),
            "heartbeat_path": str(_runtime_heartbeat_path(settings)),
            "log_path": str(_runtime_log_path(settings)),
            "retry_limit": retry_limit,
            "min_publish_content_timestamp": min_extracted_at,
        },
        "queue": counts,
    }


def _preflight(pipeline: DuoPipeline) -> dict[str, Any]:
    """Everything a live 24/7 start needs; only names and states, never secret values."""
    settings = pipeline.settings
    critical: list[str] = []
    warnings: list[str] = []

    if not is_production_machine():
        critical.append("not_production_machine")
    if not settings.live_publish_enabled:
        critical.append("DUO_LIVE_PUBLISH_ENABLED_false_or_not_production_machine")
    if not _sqlite_accessible(pipeline):
        critical.append("sqlite_unavailable")
    sources = pipeline.source_registry.enabled_source_names()
    if not sources:
        critical.append("no_enabled_sources")
    if settings.x_video_feed_enabled and not settings.x_video_feed_path.exists():
        # No frena: HolaSalta puede no haberlo escrito todavia; se reintenta cada ciclo.
        warnings.append("x_video_feed_file_missing")
    if not settings.llm.ready:
        # Without it editorial silently falls back to template captions.
        critical.append(f"{settings.llm.api_key_env}_missing")

    platforms: dict[str, str] = {}
    if settings.enable_instagram:
        ready = bool(settings.ig_access_token and settings.ig_user_id)
        platforms["instagram"] = "ready" if ready else "missing_credentials"
        if ready and not _media_storage_status().get("ready"):
            platforms["instagram"] = "media_storage_not_ready"
    if settings.enable_facebook:
        platforms["facebook"] = "ready" if settings.fb_access_token and settings.fb_page_id else "missing_credentials"
    if settings.enable_duo_web:
        if pipeline.duo_web is None:
            platforms["duo_web"] = f"not_configured_mode_{settings.duo_web_mode}"
        else:
            platforms["duo_web"] = "ready"
    for name, state in platforms.items():
        if state != "ready":
            critical.append(f"{name}_{state}")
    if not platforms:
        critical.append("no_enabled_publish_platforms")

    for binary in (settings.ffmpeg_path, settings.ffprobe_path):
        if shutil.which(binary) is None:
            warnings.append(f"{Path(binary).name}_missing")
    if _internet_check() != "ok":
        warnings.append("internet_unavailable")
    # Motor audiovisual: si falta, el formateador legado produce las piezas (no bloquea).
    motion = pipeline.formatter.motion
    motion_state = "ready" if motion.enabled else ("disabled" if not motion.config.enabled else "unavailable_legacy_fallback")
    if motion_state == "unavailable_legacy_fallback":
        warnings.append("motion_engine_unavailable_legacy_fallback")
    for platform, entry in pipeline.rate_limits.snapshot().items():
        warnings.append(f"{platform}_rate_limited_until_{entry.get('until', '')}")

    return {
        "ok": not critical,
        "checked_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "machine": os.getenv("COMPUTERNAME", ""),
        "critical": critical,
        "warnings": warnings,
        "sources": sources,
        "platforms": platforms,
        "llm": {"provider": settings.llm.provider, "model": settings.llm.model},
        "motion_engine": motion_state,
    }


def _sqlite_accessible(pipeline: DuoPipeline) -> bool:
    try:
        with pipeline.store.connection() as conn:
            conn.execute("SELECT 1").fetchone()
        return True
    except Exception:
        return False


def _internet_check() -> str:
    try:
        socket.create_connection(("1.1.1.1", 53), timeout=2).close()
        return "ok"
    except OSError:
        return "unavailable"


def _test_meta(pipeline: DuoPipeline) -> dict[str, Any]:
    settings = pipeline.settings
    payload: dict[str, Any] = {
        "live_publish_enabled": settings.live_publish_enabled,
        "instagram": "missing_credentials",
        "facebook": "missing_credentials",
        "publishes_live": False,
    }
    if settings.ig_access_token and settings.ig_user_id:
        try:
            payload["instagram"] = pipeline.publisher.get_ig_publish_limit() or "credentials_present_no_limit_payload"
        except Exception as exc:
            payload["instagram"] = f"error: {exc}"
    if settings.fb_access_token or settings.fb_page_id:
        payload["facebook"] = "configured"
    return payload


def _runtime_dir(settings: Any) -> Path:
    runtime = settings.data_dir / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    return runtime


def _runtime_lock_path(settings: Any) -> Path:
    return _runtime_dir(settings) / "autorun.lock"


def _runtime_heartbeat_path(settings: Any) -> Path:
    return _runtime_dir(settings) / "heartbeat.json"


def _runtime_log_path(settings: Any) -> Path:
    log_dir = settings.base_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / "autorun_24_7.log"


def _configure_runtime_file_logging(settings: Any) -> None:
    path = _runtime_log_path(settings)
    root = logging.getLogger()
    marker = str(path)
    for handler in root.handlers:
        if getattr(handler, "_duo_autorun_path", "") == marker:
            return
    handler = RotatingFileHandler(path, maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s"))
    handler._duo_autorun_path = marker  # type: ignore[attr-defined]
    root.addHandler(handler)


@contextmanager
def _runtime_lock(settings: Any):
    path = _runtime_lock_path(settings)
    handle = path.open("a+", encoding="utf-8")
    acquired = False
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(" ")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                acquired = True
            except OSError:
                acquired = False
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except OSError:
                acquired = False
        if acquired:
            handle.seek(0)
            handle.truncate()
            handle.write(
                json.dumps(
                    {
                        "pid": os.getpid(),
                        "acquired_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                    },
                    ensure_ascii=False,
                )
            )
            handle.flush()
        yield acquired
    finally:
        if acquired:
            try:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        handle.close()


def _write_runtime_heartbeat(pipeline: DuoPipeline, payload: dict[str, Any]) -> None:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    full_payload = {
        "updated_at": now.isoformat(),
        "pid": os.getpid(),
        "timezone": pipeline.settings.timezone,
        "cycle_id": _current_cycle_id(pipeline),
        **payload,
    }
    path = _runtime_heartbeat_path(pipeline.settings)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(full_payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    temp_path.replace(path)


def _read_runtime_heartbeat(settings: Any) -> dict[str, Any]:
    path = _runtime_heartbeat_path(settings)
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _heartbeat_payload(
    *,
    cycle: int,
    started_at: datetime,
    result: dict[str, Any],
    safe_mode: bool,
    last_error: str,
    next_sleep_seconds: int,
) -> dict[str, Any]:
    finished_at = datetime.now(timezone.utc).replace(microsecond=0)
    return {
        "state": "sleeping" if next_sleep_seconds else "completed",
        "cycle": cycle,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": max(0, int((finished_at - started_at).total_seconds())),
        "safe_mode": safe_mode,
        "live": not safe_mode,
        "result": result,
        "published": int(result.get("published") or 0) if isinstance(result, dict) else 0,
        "publish_blocked_reason": result.get("publish_blocked_reason") if isinstance(result, dict) else "",
        "last_error": last_error,
        "next_sleep_seconds": next_sleep_seconds,
    }


def _heartbeat_age_seconds(heartbeat: dict[str, Any], now: datetime) -> int | None:
    raw = str(heartbeat.get("updated_at") or "").strip()
    if not raw:
        return None
    try:
        updated_at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    return max(0, int((now - updated_at.astimezone(timezone.utc)).total_seconds()))


def _safe_recovery_retry_limit() -> int:
    raw = os.getenv("DUO_SAFE_RECOVERY_MAX_RETRIES", "3").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 3


def _heartbeat_stale_minutes() -> int:
    raw = os.getenv("DUO_HEARTBEAT_STALE_MINUTES", "90").strip()
    try:
        return max(5, int(raw))
    except ValueError:
        return 90


def _log_and_print(logger: logging.Logger, message: str) -> None:
    print(message)
    logger.info(message)


def _format_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "Sin items en cola."
    headers = ["status", "score", "source", "type", "slot", "key", "title"]
    lines = [" | ".join(headers), " | ".join("-" * len(item) for item in headers)]
    for row in rows:
        lines.append(
            " | ".join(
                [
                    str(row.get("pipeline_status") or "")[:14],
                    str(row.get("score_total") or "")[:6],
                    str(row.get("source") or "")[:12],
                    str(row.get("assigned_post_type") or row.get("media_type") or "")[:10],
                    str(row.get("assigned_slot") or "")[:5],
                    str(row.get("content_key") or "")[:10],
                    str(row.get("title") or "").replace("\n", " ")[:70],
                ]
            )
        )
    return "\n".join(lines)


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def _configure_console_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass


if __name__ == "__main__":
    main()

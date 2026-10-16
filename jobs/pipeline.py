from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence
from zoneinfo import ZoneInfo

from analytics.service import AnalyticsCollector
from editorial.service import EditorialAI
from extractors.holasalta.keys import tweet_id_from_url
from extractors.registry import SourceRegistry
from extractors.x.service import XExtractionService
from formatter.service import AssetFormatter
from growth.feedback import GrowthFeedbackService
from growth.reporting import DailyReportService
from growth.source_ranking import SourceRankingService
from growth.validation import ScoreValidationService
from jobs.content_policy import ContentPolicy, normalize_title_fingerprint
from jobs.salta_priority import is_salta_source
from jobs.scheduler import PeakScheduler
from publishers.duo_web import DUO_WEB_PLATFORM, build_duo_web_publisher
from publishers.meta_api import MetaGraphPublisher
from scoring.virality import ViralityScorer
from storage.media_hash import hamming_distance
from storage.models import Asset, DedupDecision, FormattedPackage, PublicationRecord
from storage.settings import PipelineSettings, get_settings
from storage.sqlite_store import PipelineStore


class DuoPipeline:
    def __init__(self, settings: PipelineSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self.store = PipelineStore(self.settings)
        self.source_registry = SourceRegistry(self.settings)
        self.x_extractor = XExtractionService(self.settings)
        self.scorer = ViralityScorer(self.settings)
        self.editorial = EditorialAI(self.settings)
        self.formatter = AssetFormatter(self.settings)
        self.publisher = MetaGraphPublisher(self.settings)
        self.duo_web = build_duo_web_publisher(self.settings)
        self.analytics = AnalyticsCollector(self.store, self.publisher, self.settings)
        self.growth = GrowthFeedbackService(self.store, self.settings)
        self.source_ranking = SourceRankingService(self.store, self.settings)
        self.validator = ScoreValidationService(self.store, self.settings)
        self.scheduler = PeakScheduler(self.settings)
        self.content_policy = ContentPolicy(self.settings)
        self.reporting = DailyReportService(
            self.store,
            self.growth,
            self.validator,
            self.source_ranking,
            self.settings,
        )
        self.logger = logging.getLogger("duo.pipeline")

    def run_pipeline(
        self,
        *,
        max_news: int | None = None,
        x_handles: Sequence[str] | None = None,
        dry_run: bool = False,
        max_posts: int | None = None,
        safe_mode: bool = False,
        fixed_slot_publish: bool = False,
    ) -> Dict[str, Any]:
        summary = {
            "ingested": 0,
            "scored": 0,
            "editorialized": 0,
            "formatted": 0,
            "scheduled": 0,
            "published": 0,
            "analytics": 0,
            "comment_actions": 0,
            "recovered_failed": 0,
            "recovery_skipped": 0,
            "stale_skipped": 0,
            "daily_reports": 0,
            "dry_run": dry_run,
            "safe_mode": safe_mode,
            "publish_cap": self._resolve_publish_cap(max_posts=max_posts, safe_mode=safe_mode),
        }
        summary["ingested"] += self.run_scraper(max_news=max_news, x_handles=x_handles, dry_run=dry_run)
        if not dry_run:
            recovery = self.recover_failed_queue()
            summary["recovered_failed"] += int(recovery.get("reset") or 0)
            summary["recovery_skipped"] += int(recovery.get("skipped") or 0)
            summary["stale_skipped"] += int(recovery.get("stale_skipped") or 0)
        dry_limit = 3 if dry_run or safe_mode else None
        cycle_slot = self._active_schedule_slot() if fixed_slot_publish else None
        summary["scored"] += self.run_scoring(limit=dry_limit)
        summary["editorialized"] += self.run_editorial(limit=dry_limit, force_fallback=bool(dry_run or safe_mode))
        summary["formatted"] += self.run_formatter(limit=dry_limit, dry_run=bool(dry_run or safe_mode))
        summary["scheduled"] += self.run_scheduler(limit=dry_limit)
        if not dry_run and fixed_slot_publish and cycle_slot:
            refill = self._top_up_slot_videos(active_slot=cycle_slot)
            for key, value in refill.items():
                summary[key] += value
        if not dry_run:
            summary["published"] += self.run_publisher(
                max_posts=max_posts,
                safe_mode=safe_mode,
                fixed_slot_only=fixed_slot_publish,
                active_slot_override=cycle_slot,
            )
            if summary["published"] == 0:
                upcoming = self.upcoming_publications(limit=3)
                if upcoming:
                    summary["publish_blocked_reason"] = "no_due_publications"
                    summary["next_scheduled"] = upcoming
                else:
                    summary["publish_blocked_reason"] = "no_scheduled_publications"
            summary["analytics"] += self.run_analytics()
            summary["comment_actions"] += self.run_comment_engagement()
            summary["daily_reports"] += self._maybe_build_daily_report()
        return summary

    def run_scraper(
        self,
        *,
        max_news: int | None = None,
        x_handles: Sequence[str] | None = None,
        dry_run: bool = False,
    ) -> int:
        if max_news == 0:
            return 0
        ingested = 0
        for source in self.source_registry.enabled_source_names():
            try:
                rows = self.source_registry.scan_source(source, max_items=max_news)
            except Exception as exc:
                self.logger.exception("News extractor failed for %s: %s", source, exc)
                continue
            ingested += self._ingest_rows(rows)

        ingested += self._import_holasalta_x_jobs(max_items=max_news, dry_run=dry_run)

        if self.settings.x_mode != "manual":
            handles = list(x_handles or self.source_ranking.prioritize_handles(self.settings.x_sources))
            try:
                x_rows = self.x_extractor.extract(
                    handles=handles,
                    limit_per_handle=max_news if max_news is not None else self.settings.x_default_items_per_handle,
                )
            except Exception as exc:
                self.logger.exception("X extractor failed: %s", exc)
                x_rows = []
            ingested += self._ingest_rows(x_rows)
        return ingested

    def scan_source(self, source: str, *, max_items: int | None = None) -> int:
        return self._ingest_rows(self.source_registry.scan_source(source, max_items=max_items))

    def _import_holasalta_x_jobs(self, *, max_items: int | None = None, dry_run: bool = False) -> int:
        """Route X links queued in HolaSalta through the regular X import flow."""
        try:
            urls = self.source_registry.holasalta_video_urls(max_items=max_items)
        except Exception as exc:
            self.logger.exception("HolaSalta video jobs failed: %s", exc)
            return 0
        imported = 0
        for url in urls:
            if self.store.has_source_item("x", tweet_id_from_url(url)):
                continue
            try:
                self.import_x_url(url, dry_run=dry_run)
                imported += 1
            except Exception as exc:
                self.logger.warning("HolaSalta X job import failed for %s: %s", url, exc)
        return imported

    def import_x_url(self, url: str, *, dry_run: bool = False) -> str:
        content = self.x_extractor.import_url(url, dry_run=dry_run)
        content_key = self.store.upsert_content(content)
        decision = self._dedupe_content(content, content_key)
        self.store.save_dedup(content_key, decision)
        return content_key

    def run_scoring(self, *, limit: int | None = None) -> int:
        recent = self.store.performance_rows(lookback_days=14, latest_only=True)[:20]
        processed = 0
        for row in self.store.list_pending_scoring(limit=limit or 50):
            try:
                policy = self.content_policy.evaluate_row(row)
                if not policy.accepted:
                    self.store.skip_content(str(row["content_key"]), policy.reason)
                    continue
                score = self.scorer.score_item(row, recent_winners=recent)
                self.store.save_score(str(row["content_key"]), score)
                processed += 1
            except Exception as exc:
                self.store.mark_status(str(row["content_key"]), "score_failed", str(exc))
        return processed

    def run_editorial(self, *, limit: int | None = None, force_fallback: bool = False) -> int:
        feedback = self.growth.build_feedback_summary()
        processed = 0
        for row in self.store.list_pending_editorial(limit=limit or 25):
            try:
                editorial = self.editorial.generate(row, growth_feedback=feedback, force_fallback=force_fallback)
                self.store.save_editorial(str(row["content_key"]), editorial)
                processed += 1
            except Exception as exc:
                self.store.mark_status(str(row["content_key"]), "editorial_failed", str(exc))
        return processed

    def run_formatter(self, *, limit: int | None = None, dry_run: bool = False) -> int:
        processed = 0
        for row in self.store.list_pending_formatter(limit=limit or 20):
            try:
                package = self.formatter.format_row(row, dry_run=dry_run)
                self.store.save_formatted(str(row["content_key"]), package)
                processed += 1
            except Exception as exc:
                self.store.mark_status(str(row["content_key"]), "format_failed", str(exc))
        return processed

    def run_scheduler(self, *, limit: int | None = None) -> int:
        block_capacity = max(
            1,
            int(self.settings.schedule_videos_per_slot) + int(self.settings.schedule_posts_per_slot),
        )
        default_limit = max(20, block_capacity * max(1, len(self.settings.schedule_slots)))
        rows = self.store.list_pending_scheduling(limit=limit or default_limit)
        if not rows:
            return 0
        rows = self._filter_policy_rows(rows, stage="schedule")
        if not rows:
            return 0
        history = self.store.recent_schedule_context()
        now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        existing = self.store.future_schedule_context(now_iso, limit=default_limit * 4)
        decisions = self.scheduler.assign(rows, recent_context=history, existing_context=existing)
        for content_key, decision in decisions.items():
            self.store.save_schedule(content_key, decision)
        return len(decisions)

    def preview_publications(self, *, max_posts: int | None = None, safe_mode: bool = False) -> List[Dict[str, object]]:
        cap = self._resolve_publish_cap(max_posts=max_posts, safe_mode=safe_mode)
        now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        min_extracted_at = self._min_publish_content_timestamp()
        rows = self.store.list_due_for_publish(
            now_iso,
            limit=200,
            min_extracted_at=min_extracted_at,
        )
        rows = self._filter_policy_rows(rows, stage="preview", persist=False)
        rows = [row for row in rows if not self._formatted_publish_block_reason(row)]
        return self._publication_preview(self._select_publish_block(rows, cap or self.settings.publish_default_max_posts))

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
        if not row.get("formatted_json"):
            return {"live": False, "blocked_reason": "not_formatted", "preview": preview}
        policy = self.content_policy.evaluate_row(row)
        if not policy.accepted:
            return {"live": False, "blocked_reason": policy.reason, "preview": preview}
        if self._formatted_is_dry_run(row):
            return {"live": False, "blocked_reason": "dry_run_formatted_rebuild_required", "preview": preview}
        block_reason = self._formatted_publish_block_reason(row)
        if block_reason:
            return {"live": False, "blocked_reason": block_reason, "preview": preview}
        requested_platforms = self._requested_platforms(platform)
        if not force:
            statuses = self.store.publication_statuses(content_key)
            requested_platforms = [
                item
                for item in requested_platforms
                if str(statuses.get(item, {}).get("status") or "") != "published"
            ]
            if not requested_platforms:
                return {"live": False, "blocked_reason": "already_published", "preview": preview}
        package = self._formatted_from_row(row)
        scheduled_for = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        results = []
        publication_ids = []
        for result in self._publish_platform_records(package, scheduled_for=scheduled_for, platforms=requested_platforms):
            publication_ids.append(self.store.save_publication(content_key, result))
            results.append(result.as_dict())
        self.store.refresh_content_publish_state(content_key, self._requested_platforms(platform))
        return {
            "live": True,
            "publication_ids": publication_ids,
            "results": results,
            "preview": preview,
        }

    def upcoming_publications(self, *, limit: int = 3) -> List[Dict[str, object]]:
        rows = self.store.list_upcoming_scheduled(limit=limit)
        return self._publication_preview(rows)

    def run_publisher(
        self,
        *,
        max_posts: int | None = None,
        safe_mode: bool = False,
        fixed_slot_only: bool = False,
        active_slot_override: str | None = None,
        content_type: str | None = None,
        force_due: bool = False,
    ) -> int:
        # content_type: "reels" = X clips only, "news" = image/carousel only, None = all
        if safe_mode or not self.settings.live_publish_enabled:
            self.logger.warning("Live publishing blocked by safe mode or DUO_LIVE_PUBLISH_ENABLED=0")
            return 0
        target_platforms = self._enabled_publish_platforms()
        if not target_platforms:
            self.logger.warning("No enabled publish platforms")
            return 0
        active_slot = active_slot_override if fixed_slot_only else None
        if fixed_slot_only and not active_slot:
            active_slot = self._active_schedule_slot()
        if fixed_slot_only and not active_slot:
            self.logger.info("No active publication slot; live publish deferred")
            return 0
        skipped = self._skip_unpublishable_queue()
        if skipped:
            self.logger.info("Skipped %s unpublishable queue items", skipped)
        published = 0
        cap = self._resolve_publish_cap(max_posts=max_posts, safe_mode=safe_mode)
        now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        min_extracted_at = self._min_publish_content_timestamp()
        stale_skipped = self.store.skip_stale_publish_queue(min_extracted_at)
        if stale_skipped:
            self.logger.info("Skipped %s stale queue items older than %s", stale_skipped, min_extracted_at)
        due_rows = self.store.list_due_for_publish(
            now_iso,
            limit=200,
            slot_label=active_slot,
            min_extracted_at=min_extracted_at,
            content_type=content_type,
            force_due=force_due,
        )
        if fixed_slot_only and active_slot and not due_rows:
            due_rows = self.store.list_due_for_publish(
                now_iso,
                limit=200,
                min_extracted_at=min_extracted_at,
                content_type=content_type,
                force_due=force_due,
            )
            if due_rows:
                self.logger.info(
                    "No due items in active slot %s; using overdue same-day backlog",
                    active_slot,
                )
        due_rows = self._filter_policy_rows(due_rows, stage="publish")
        for row in self._select_publish_block(due_rows, cap or self.settings.publish_default_max_posts):
            content_key = str(row["content_key"])
            try:
                block_reason = self._formatted_publish_block_reason(row)
                if block_reason:
                    self.store.mark_status(content_key, "format_failed", block_reason)
                    continue
                package = self._formatted_from_row(row)
                schedule = self._load_json(row.get("schedule_json"))
                statuses = self.store.publication_statuses(content_key)
                pending_platforms = [
                    platform
                    for platform in target_platforms
                    if str(statuses.get(platform, {}).get("status") or "") != "published"
                ]
                if not pending_platforms:
                    self.store.refresh_content_publish_state(content_key, target_platforms)
                    published += 1
                    continue
                for result in self._publish_platform_records(
                    package,
                    scheduled_for=str(schedule.get("scheduled_for") or ""),
                    platforms=pending_platforms,
                ):
                    self.store.save_publication(content_key, result)
                self.store.refresh_content_publish_state(content_key, target_platforms)
                final_statuses = self.store.publication_statuses(content_key)
                if all(str(final_statuses.get(platform, {}).get("status") or "") == "published" for platform in target_platforms):
                    published += 1
            except Exception as exc:
                self.store.mark_status(content_key, "publish_failed", str(exc))
        return published

    def _top_up_slot_videos(self, *, active_slot: str) -> Dict[str, int]:
        target = max(0, int(self.settings.schedule_videos_per_slot))
        summary = {
            "ingested": 0,
            "scored": 0,
            "editorialized": 0,
            "formatted": 0,
            "scheduled": 0,
        }
        if target <= 0 or not active_slot or self.settings.x_mode == "manual":
            return summary
        current_videos = self._count_due_slot_videos(active_slot=active_slot)
        if current_videos >= target:
            return summary
        handles = list(self.source_ranking.prioritize_handles(self.settings.x_sources))
        if not handles:
            return summary
        for attempt in range(2):
            missing = target - current_videos
            if missing <= 0:
                break
            limit_per_handle = max(
                self.settings.x_default_items_per_handle,
                self.settings.x_default_items_per_handle + (missing * 3) + (attempt * 2),
            )
            try:
                x_rows = self.x_extractor.extract(handles=handles, limit_per_handle=limit_per_handle)
            except Exception as exc:
                self.logger.exception("X top-up extractor failed: %s", exc)
                break
            ingested = self._ingest_rows(x_rows)
            summary["ingested"] += ingested
            if ingested <= 0:
                break
            summary["scored"] += self.run_scoring(limit=200)
            summary["editorialized"] += self.run_editorial(limit=100, force_fallback=False)
            summary["formatted"] += self.run_formatter(limit=100, dry_run=False)
            summary["scheduled"] += self.run_scheduler(limit=200)
            current_videos = self._count_due_slot_videos(active_slot=active_slot)
        return summary

    def run_analytics(self) -> int:
        snapshots = self.analytics.collect_due_snapshots()
        return len(snapshots)

    def run_comment_engagement(self) -> int:
        if not self.settings.enable_comment_engagement:
            return 0
        now = datetime.now(timezone.utc).replace(microsecond=0)
        min_ts = (now - timedelta(minutes=self.settings.comment_max_age_minutes)).isoformat()
        max_ts = (now - timedelta(minutes=self.settings.comment_min_age_minutes)).isoformat()
        actions_count = 0
        with self.store.connection() as conn:
            rows = conn.execute(
                """
                SELECT p.id, p.platform, p.platform_media_id
                FROM publications p
                LEFT JOIN comment_actions c ON c.publication_id = p.id
                WHERE p.platform = 'instagram'
                  AND p.status = 'published'
                  AND p.published_at BETWEEN ? AND ?
                  AND c.id IS NULL
                """,
                (min_ts, max_ts),
            ).fetchall()
        for row in rows:
            try:
                actions = self.publisher.engage_instagram_comments(
                    str(row["platform_media_id"]),
                    self.settings.comment_reply_emoji,
                )
            except Exception:
                continue
            for action in actions:
                self.store.save_comment_action(
                    int(row["id"]),
                    platform="instagram",
                    comment_id=str(action["comment_id"]),
                    author_username=str(action["author_username"]),
                    comment_text=str(action["comment_text"]),
                    liked=bool(action["liked"]),
                    replied=bool(action["replied"]),
                    reply_id=str(action["reply_id"]),
                    payload=dict(action["payload"]),
                )
                actions_count += 1
        return actions_count

    def validate_scoring(self, *, lookback_days: int = 30, checkpoint_label: str | None = "T3") -> Dict[str, object]:
        return self.validator.validate(lookback_days=lookback_days, checkpoint_label=checkpoint_label)

    def show_source_ranking(self, *, lookback_days: int | None = None) -> List[Dict[str, object]]:
        return self.source_ranking.rank_sources(lookback_days=lookback_days)

    def build_daily_report(self, *, report_date: date | None = None, write_json: bool = True) -> Dict[str, object]:
        return self.reporting.build_report(report_date, write_json=write_json)

    def recover_failed_queue(self, *, retry_limit: int | None = None) -> Dict[str, int]:
        limit = retry_limit if retry_limit is not None else self._safe_recovery_retry_limit()
        min_extracted_at = self._min_publish_content_timestamp()
        summary = {
            "reset": 0,
            "skipped": 0,
            "stale_skipped": self.store.skip_stale_publish_queue(min_extracted_at),
        }
        for status, target in (
            ("score_failed", "extracted"),
            ("editorial_failed", "scored"),
            ("format_failed", "editorialized"),
            ("publish_failed", "scheduled"),
        ):
            for row in self.store.rows_by_status(status, limit=200):
                content_key = str(row.get("content_key") or "")
                if not content_key:
                    continue
                if self._row_is_stale_for_recovery(row, min_extracted_at):
                    if self.store.skip_content(content_key, f"recovery:stale:{status}"):
                        summary["skipped"] += 1
                    continue
                retry_count = int(row.get("retry_count") or 0)
                if retry_count >= limit:
                    reason = str(row.get("last_error") or status).strip()[:180]
                    if self.store.skip_content(content_key, f"recovery:retry_limit_exceeded:{status}:{reason}"):
                        summary["skipped"] += 1
                    continue
                if self.store.reset_failed_for_retry(content_key, target):
                    summary["reset"] += 1
        return summary

    def retry_failed(self) -> int:
        reset = 0
        for status, target in (
            ("score_failed", "extracted"),
            ("editorial_failed", "scored"),
            ("format_failed", "editorialized"),
            ("publish_failed", "scheduled"),
        ):
            rows = self.store.rows_by_status(status, limit=200)
            for row in rows:
                self.store.mark_status(str(row["content_key"]), target, "")
                reset += 1
        return reset

    def show_stats(self) -> Dict[str, Any]:
        return self.store.stats_summary()

    def show_queue(self) -> List[Dict[str, Any]]:
        return self.store.queue_summary()

    def queue_rows(self, limit: int = 50) -> List[Dict[str, Any]]:
        return self.store.queue_rows(limit=limit)

    def inspect(self, content_key: str) -> Dict[str, Any] | None:
        return self.store.inspect_content(content_key)

    def skip(self, content_key: str, reason: str) -> bool:
        return self.store.skip_content(content_key, reason)

    def retry(self, content_key: str) -> bool:
        return self.store.retry_content(content_key)

    def requeue_pending_for_rebuild(self) -> int:
        return self.store.requeue_unpublished_for_rebuild()

    def _resolve_publish_cap(self, *, max_posts: int | None, safe_mode: bool) -> int | None:
        block_size = max(1, int(self.settings.schedule_videos_per_slot) + int(self.settings.schedule_posts_per_slot))
        if max_posts is not None and max_posts > 0:
            return min(max_posts, block_size)
        return min(max(1, self.settings.publish_default_max_posts), block_size)

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
        if value == "instagram":
            return ["instagram"]
        if value == "facebook":
            return ["facebook"]
        if value == DUO_WEB_PLATFORM:
            return [DUO_WEB_PLATFORM]
        return ["instagram", "facebook"]

    def _publish_platform_records(
        self,
        package: FormattedPackage,
        *,
        scheduled_for: str,
        platforms: Sequence[str],
    ) -> List[PublicationRecord]:
        records: List[PublicationRecord] = []
        cleanup_hook = getattr(self.publisher, "cleanup_package_assets", None)
        sentinel = object()
        previous_defer = package.meta.get("defer_cleanup", sentinel)
        package.meta["defer_cleanup"] = True
        try:
            for platform in platforms:
                try:
                    if platform == "instagram":
                        records.append(self.publisher.publish_instagram(package, scheduled_for=scheduled_for))
                    elif platform == "facebook":
                        records.append(self.publisher.publish_facebook(package, scheduled_for=scheduled_for))
                    elif platform == DUO_WEB_PLATFORM and self.duo_web is not None:
                        row = self.store.find_content(package.content_key) or {}
                        records.append(self.duo_web.publish(package, row=row, scheduled_for=scheduled_for))
                except Exception as platform_exc:
                    self.logger.warning("Platform %s publish error: %s", platform, platform_exc)
                    records.append(
                        PublicationRecord(
                            platform=platform,
                            status="publish_failed",
                            error_message=str(platform_exc),
                            mode="live",
                            dry_run=False,
                        )
                    )
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

    def _select_publish_block(self, rows: Sequence[Dict[str, Any]], cap: int) -> List[Dict[str, Any]]:
        requested_cap = max(0, int(cap or 0))
        video_cap = max(0, int(self.settings.schedule_videos_per_slot))
        post_cap = max(0, int(self.settings.schedule_posts_per_slot))
        block_cap = min(requested_cap, video_cap + post_cap)
        if block_cap <= 0:
            return []
        ordered_rows = sorted(rows, key=self._publish_priority_key)
        video_rows = [row for row in ordered_rows if self._is_video_publish_row(row)][:video_cap]
        post_rows = [row for row in ordered_rows if not self._is_video_publish_row(row)][:post_cap]
        return self._interleave_publish_rows(video_rows, post_rows, block_cap)

    def _publish_priority_key(self, row: Dict[str, Any]) -> tuple[int, str, int]:
        is_local = is_salta_source(row.get("source"), self.settings)
        scheduled = str(row.get("assigned_time") or "")
        try:
            rank = int(self._load_json(row.get("schedule_json")).get("priority_rank") or 9999)
        except Exception:
            rank = 9999
        return (0 if is_local else 1, scheduled, rank)

    @staticmethod
    def _is_video_publish_row(row: Dict[str, Any]) -> bool:
        post_type = str(row.get("assigned_post_type") or row.get("media_type") or "").strip().lower()
        return post_type in {"reel", "video"}

    def _interleave_publish_rows(
        self,
        video_rows: List[Dict[str, Any]],
        post_rows: List[Dict[str, Any]],
        cap: int,
    ) -> List[Dict[str, Any]]:
        selected: List[Dict[str, Any]] = []
        last_group = ""
        recent_sources: List[str] = []
        source_counts: Dict[str, int] = {}
        videos = list(video_rows)
        posts = list(post_rows)
        while len(selected) < cap and (videos or posts):
            next_group = self._next_publish_group(last_group=last_group, videos=videos, posts=posts)
            pool = videos if next_group == "video" else posts
            row = self._pop_publish_candidate(
                pool,
                recent_sources=recent_sources,
                source_counts=source_counts,
            )
            if row is None:
                fallback_pool = posts if next_group == "video" else videos
                row = self._pop_publish_candidate(
                    fallback_pool,
                    recent_sources=recent_sources,
                    source_counts=source_counts,
                )
                if row is None:
                    break
                next_group = "post" if next_group == "video" else "video"
            selected.append(row)
            last_group = next_group
            source = self._publish_row_source(row)
            if source:
                recent_sources.insert(0, source)
                recent_sources = recent_sources[:3]
                source_counts[source] = int(source_counts.get(source, 0)) + 1
        return selected

    @staticmethod
    def _next_publish_group(
        *,
        last_group: str,
        videos: Sequence[Dict[str, Any]],
        posts: Sequence[Dict[str, Any]],
    ) -> str:
        if videos and posts:
            if last_group == "video":
                return "post"
            if last_group == "post":
                return "video"
            return "video"
        if videos:
            return "video"
        return "post"

    def _pop_publish_candidate(
        self,
        pool: List[Dict[str, Any]],
        *,
        recent_sources: Sequence[str],
        source_counts: Dict[str, int],
    ) -> Dict[str, Any] | None:
        if not pool:
            return None
        cap = max(1, int(self.settings.publish_max_per_source_per_block))
        if not recent_sources:
            for index, row in enumerate(pool):
                source = self._publish_row_source(row)
                if not source or int(source_counts.get(source, 0)) < cap:
                    return pool.pop(index)
            return pool.pop(0)
        for index, row in enumerate(pool):
            source = self._publish_row_source(row)
            if source and int(source_counts.get(source, 0)) >= cap:
                continue
            if source not in recent_sources:
                return pool.pop(index)
        for index, row in enumerate(pool):
            source = self._publish_row_source(row)
            if not source or int(source_counts.get(source, 0)) < cap:
                return pool.pop(index)
        return pool.pop(0)

    @staticmethod
    def _publish_row_source(row: Dict[str, Any]) -> str:
        return str(row.get("source_handle") or row.get("source") or "").strip().lower()

    def _min_publish_content_timestamp(self) -> str:
        max_age_hours = max(1, int(self.settings.publish_max_content_age_hours))
        return (
            datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        ).replace(microsecond=0).isoformat()

    @staticmethod
    def _safe_recovery_retry_limit() -> int:
        raw = os.getenv("DUO_SAFE_RECOVERY_MAX_RETRIES", "3").strip()
        try:
            return max(1, int(raw))
        except ValueError:
            return 3

    @staticmethod
    def _row_is_stale_for_recovery(row: Dict[str, Any], min_extracted_at: str) -> bool:
        timestamp = str(row.get("extracted_at") or row.get("created_at") or "").strip()
        if not timestamp:
            return False
        try:
            row_dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            min_dt = datetime.fromisoformat(min_extracted_at.replace("Z", "+00:00"))
        except ValueError:
            return timestamp < min_extracted_at
        if row_dt.tzinfo is None:
            row_dt = row_dt.replace(tzinfo=timezone.utc)
        if min_dt.tzinfo is None:
            min_dt = min_dt.replace(tzinfo=timezone.utc)
        return row_dt.astimezone(timezone.utc) < min_dt.astimezone(timezone.utc)

    def _maybe_build_daily_report(self) -> int:
        try:
            zone = ZoneInfo(self.settings.timezone)
        except Exception:
            return 0
        now = datetime.now(zone).replace(microsecond=0)
        if not self._daily_report_window_open(now):
            return 0
        report_date = now.date()
        if self.store.get_daily_report(report_date.isoformat()):
            return 0
        if not self.store.report_publications_for_date(report_date):
            return 0
        report = self.reporting.build_report(report_date, write_json=True)
        return 1 if int(report.get("posts_published") or 0) > 0 else 0

    def _daily_report_window_open(self, now: datetime) -> bool:
        latest_minutes: int | None = None
        for slot in self.settings.schedule_slots:
            try:
                hour, minute = (int(part) for part in str(slot).split(":", 1))
            except Exception:
                continue
            candidate = hour * 60 + minute
            latest_minutes = candidate if latest_minutes is None else max(latest_minutes, candidate)
        if latest_minutes is None:
            return False
        now_minutes = now.hour * 60 + now.minute
        return now_minutes >= latest_minutes + max(0, int(self.settings.publish_slot_window_minutes))

    def _count_due_slot_videos(self, *, active_slot: str) -> int:
        if not active_slot:
            return 0
        now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        min_extracted_at = self._min_publish_content_timestamp()
        rows = self.store.list_due_for_publish(
            now_iso,
            limit=500,
            slot_label=active_slot,
            min_extracted_at=min_extracted_at,
        )
        rows = self._filter_policy_rows(rows, stage="slot_video_count", persist=False)
        return sum(
            1
            for row in rows
            if str(row.get("assigned_post_type") or row.get("media_type") or "").strip().lower() in {"reel", "video"}
        )

    def _active_schedule_slot(self) -> str | None:
        try:
            zone = ZoneInfo(self.settings.timezone)
        except Exception:
            return None
        now = datetime.now(zone).replace(microsecond=0)
        window_minutes = max(0, int(self.settings.publish_slot_window_minutes))
        for slot in self.settings.schedule_slots:
            try:
                hour, minute = (int(part) for part in str(slot).split(":", 1))
            except Exception:
                continue
            slot_time = datetime(
                year=now.year,
                month=now.month,
                day=now.day,
                hour=hour,
                minute=minute,
                tzinfo=zone,
            )
            elapsed_minutes = (now - slot_time).total_seconds() / 60
            if 0 <= elapsed_minutes <= window_minutes:
                return str(slot)
        return None

    def _ingest_rows(self, rows: Sequence[Any]) -> int:
        processed = 0
        for content in rows:
            content_key = self.store.upsert_content(content)
            decision = self._dedupe_content(content, content_key)
            self.store.save_dedup(content_key, decision)
            if decision.status != "discarded":
                policy = self.content_policy.evaluate_content(content)
                if not policy.accepted:
                    self.store.skip_content(content_key, policy.reason)
                elif self._already_published_like(content.as_dict()):
                    self.store.skip_content(content_key, "already_published_similar")
            processed += 1
        return processed

    def _dedupe_content(self, content: Any, content_key: str) -> DedupDecision:
        phash = ""
        for asset in content.assets:
            if asset.perceptual_hash:
                phash = asset.perceptual_hash
                break
        candidates = self.store.recent_hash_candidates(content.source_type)
        for candidate in candidates:
            existing_key = str(candidate.get("content_key") or "")
            existing_hash = str(candidate.get("perceptual_hash") or "")
            if existing_key == content_key or not existing_hash or not phash:
                continue
            if hamming_distance(phash, existing_hash) <= 6:
                return DedupDecision(
                    status="discarded",
                    reason="perceptual_duplicate",
                    matched_content_key=existing_key,
                    perceptual_hash=phash,
                )
        return DedupDecision(status="accepted", reason="fresh_content", perceptual_hash=phash)

    def _filter_policy_rows(
        self,
        rows: Sequence[Dict[str, Any]],
        *,
        stage: str,
        persist: bool = True,
    ) -> List[Dict[str, Any]]:
        accepted: List[Dict[str, Any]] = []
        for row in rows:
            content_key = str(row.get("content_key") or "")
            policy = self.content_policy.evaluate_row(row)
            if not policy.accepted:
                if persist and content_key:
                    self.store.skip_content(content_key, f"{stage}:{policy.reason}")
                continue
            if self._already_published_like(row):
                if persist and content_key:
                    self.store.skip_content(content_key, f"{stage}:already_published_similar")
                continue
            accepted.append(row)
        return accepted

    def _skip_unpublishable_queue(self) -> int:
        skipped = 0
        rows = self.store.list_publish_queue_candidates(limit=500)
        for row in rows:
            content_key = str(row.get("content_key") or "")
            if not content_key:
                continue
            policy = self.content_policy.evaluate_row(row)
            if not policy.accepted:
                self.store.skip_content(content_key, f"publish_queue:{policy.reason}")
                skipped += 1
                continue
            if self._already_published_like(row):
                self.store.skip_content(content_key, "publish_queue:already_published_similar")
                skipped += 1
                continue
            block_reason = self._formatted_publish_block_reason(row)
            if block_reason:
                self.store.mark_status(content_key, "format_failed", block_reason)
                skipped += 1
        return skipped

    def _already_published_like(self, row: Dict[str, Any]) -> bool:
        content_key = str(row.get("content_key") or "")
        source_item_id = str(row.get("source_item_id") or "").strip()
        canonical_url = str(row.get("canonical_url") or "").strip().rstrip("/")
        title_fp = normalize_title_fingerprint(row.get("title"))
        if not (source_item_id or canonical_url or title_fp):
            return False
        for item in self.store.published_fingerprints(limit=500):
            if str(item.get("content_key") or "") == content_key:
                continue
            if canonical_url and canonical_url == str(item.get("canonical_url") or "").strip().rstrip("/"):
                return True
            if source_item_id and source_item_id == str(item.get("source_item_id") or "").strip():
                return True
            other_title = normalize_title_fingerprint(item.get("title"))
            if title_fp and other_title and (title_fp == other_title or title_fp in other_title or other_title in title_fp):
                return True
        return False

    def _formatted_is_dry_run(self, row: Dict[str, Any]) -> bool:
        payload = self._load_json(row.get("formatted_json"))
        meta = payload.get("meta") if isinstance(payload, dict) else {}
        return bool(isinstance(meta, dict) and meta.get("dry_run"))

    def _formatted_publish_block_reason(self, row: Dict[str, Any]) -> str:
        payload = self._load_json(row.get("formatted_json"))
        if not payload:
            return "not_formatted"
        meta = payload.get("meta") if isinstance(payload, dict) else {}
        meta_dict = meta if isinstance(meta, dict) else {}
        if meta_dict.get("dry_run"):
            return "dry_run_formatted_rebuild_required"

        post_type = str(
            payload.get("post_type")
            or row.get("assigned_post_type")
            or row.get("media_type")
            or ""
        ).strip().lower()
        if post_type not in {"reel", "video"}:
            return ""

        assets = payload.get("assets") if isinstance(payload, dict) else []
        has_video_asset = any(
            isinstance(asset, dict)
            and str(asset.get("kind") or "").lower() == "video"
            and (str(asset.get("path") or "").strip() or str(asset.get("remote_url") or "").strip())
            for asset in (assets if isinstance(assets, list) else [])
        )
        if not has_video_asset:
            return "reel_without_video_asset"

        layout_required = os.getenv("IG_VIDEO_USE_LAYOUT", "1").strip().lower() not in {"0", "false", "no", "off"}
        if not layout_required:
            return ""
        layout_template = str(meta_dict.get("layout_template") or "").strip()
        if not layout_template:
            return "video_layout_missing_rebuild_required"
        if not Path(layout_template).exists():
            return "video_layout_template_missing_rebuild_required"
        return ""

    @staticmethod
    def _load_json(raw: object) -> Dict[str, Any]:
        try:
            payload = json.loads(str(raw or ""))
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _formatted_from_row(self, row: Dict[str, object]) -> FormattedPackage:
        payload = self._load_json(row.get("formatted_json"))
        assets: List[Asset] = []
        for item in payload.get("assets") or []:
            if not isinstance(item, dict):
                continue
            assets.append(
                Asset(
                    kind=str(item.get("kind") or ""),
                    path=str(item.get("path") or ""),
                    remote_url=str(item.get("remote_url") or ""),
                    mime_type=str(item.get("mime_type") or ""),
                    duration_seconds=float(item.get("duration_seconds") or 0.0) or None,
                    sha1=str(item.get("sha1") or ""),
                    perceptual_hash=str(item.get("perceptual_hash") or ""),
                    meta=dict(item.get("meta") or {}),
                )
            )
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
        preview = []
        for row in rows:
            preview.append(
                {
                    "content_key": row.get("content_key"),
                    "title": row.get("title"),
                    "source": row.get("source"),
                    "source_handle": row.get("source_handle"),
                    "score_total": row.get("score_total"),
                    "slot": row.get("assigned_slot"),
                    "scheduled_for": row.get("assigned_time"),
                    "post_type": row.get("assigned_post_type"),
                }
            )
        return preview
